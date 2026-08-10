import asyncio
import json
import logging
import time
import os
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_system_config, get_health_config, resolve_path
from app.database import DatabaseManager
from app.models.reference_model import ReferenceModel
from app.telemetry.sources import CSVReplaySource, SimulationTelemetrySource, TelemetrySource
from app.engine.health_engine import HealthEngine

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("thrust_hm_main")

# Load Configuration
sys_cfg = get_system_config()
health_cfg = get_health_config()

# Global instances
db_manager: Optional[DatabaseManager] = None
ref_model: Optional[ReferenceModel] = None
health_engine: Optional[HealthEngine] = None

sim_source: Optional[SimulationTelemetrySource] = None
csv_source: Optional[CSVReplaySource] = None
current_source: Optional[TelemetrySource] = None
active_source_type: str = "simulation" # "simulation" or "replay"

# Latest processed sample cache for quick API access
latest_processed_sample: Dict[str, Any] = {}

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, data: Dict[str, Any]):
        message = json.dumps(data)
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                # Connection might be dead, handled during cleanup
                pass

manager = ConnectionManager()

# Background telemetry ingestion task running flag
telemetry_loop_task = None
keep_running_loop = True

async def telemetry_ingestion_loop():
    global latest_processed_sample, current_source
    logger.info("Starting telemetry ingestion loop...")
    while keep_running_loop:
        try:
            if current_source is None:
                await asyncio.sleep(0.1)
                continue
                
            # Fetch next sample (this will block/sleep internally according to source constraints)
            sample = await current_source.get_next_sample()
            if sample is None:
                continue
                
            # Parse time and format ISO
            t = sample.get("timestamp", time.time())
            sample["timestamp_iso"] = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(t)) + f".{int((t%1)*1000):03d}Z"
            
            # Feed telemetry to health engine
            processed, events = health_engine.process_telemetry(sample)
            
            # Update latest sample cache
            latest_processed_sample = processed
            
            # Append telemetry source metadata for frontend
            payload = {
                "type": "telemetry",
                "source_type": active_source_type,
                "data": processed,
                "events": events
            }
            
            # If in replay mode, add index/progress info
            if active_source_type == "replay" and csv_source is not None:
                payload["replay_info"] = {
                    "current_index": csv_source.current_idx,
                    "total_samples": len(csv_source.samples),
                    "progress_pct": (csv_source.current_idx / max(1, len(csv_source.samples))) * 100.0,
                    "is_playing": csv_source.is_playing,
                    "playback_speed": csv_source.playback_speed
                }
                
            # Broadcast to WebSocket clients
            await manager.broadcast(payload)
            
        except Exception as e:
            logger.error(f"Error in telemetry ingestion loop: {str(e)}", exc_info=True)
            await asyncio.sleep(0.5)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global db_manager, ref_model, health_engine, sim_source, csv_source, current_source, active_source_type, telemetry_loop_task, keep_running_loop
    
    # 1. Initialize SQLite Database
    db_path = resolve_path(sys_cfg.get("database", {}).get("db_path", "data/thruster_health.db"))
    db_manager = DatabaseManager(db_path)
    
    # 2. Register/Ensure default thruster profile exists
    default_thruster_id = "T200-001"
    thruster_profile = db_manager.get_thruster(default_thruster_id)
    if not thruster_profile:
        logger.info(f"Creating default thruster profile for {default_thruster_id}")
        db_manager.save_thruster({
            "id": default_thruster_id,
            "model": "T200",
            "serial_number": "SN-T200-A01",
            "manufacturer": "Blue Robotics",
            "manufacture_date": "2024-01-15",
            "installation_date": "2024-02-10",
            "notes": "Primary ROV port side horizontal propulsion thruster."
        })
        
    # 3. Initialize Reference Model (2D Interpolator)
    ref_dir = resolve_path(sys_cfg.get("paths", {}).get("reference_dir", "data/reference/t200"))
    ref_model = ReferenceModel(
        reference_dir=ref_dir,
        pwm_neutral=health_cfg.get("thruster", {}).get("pwm_neutral", 1500),
        pwm_deadband=health_cfg.get("thruster", {}).get("pwm_deadband", 25)
    )
    
    # 4. Initialize Health Engine
    health_engine = HealthEngine(
        thruster_id=default_thruster_id,
        ref_model=ref_model,
        config_health=health_cfg,
        db_manager=db_manager
    )
    
    # 5. Setup Telemetry Sources
    sim_settings = sys_cfg.get("simulation", {})
    sim_source = SimulationTelemetrySource(
        update_rate_hz=sys_cfg.get("telemetry", {}).get("update_rate_hz", 10.0),
        config_sim=sim_settings
    )
    
    replay_settings = sys_cfg.get("replay", {})
    sample_dir = resolve_path(sys_cfg.get("paths", {}).get("sample_dir", "data/sample"))
    replay_file = os.path.join(sample_dir, replay_settings.get("default_file", "sample_telemetry.csv"))
    try:
        csv_source = CSVReplaySource(
            file_path=replay_file,
            playback_speed=replay_settings.get("playback_speed", 1.0)
        )
    except FileNotFoundError:
        logger.error(f"Replay telemetry file not found at: {replay_file}. Replay mode will be unavailable.")
        csv_source = None
        
    # Set default source
    default_src_type = sys_cfg.get("telemetry", {}).get("default_source", "simulation")
    if default_src_type == "replay" and csv_source is not None:
        current_source = csv_source
        active_source_type = "replay"
    else:
        current_source = sim_source
        active_source_type = "simulation"
        
    await current_source.connect()
    
    # Start background ingestion loop
    keep_running_loop = True
    telemetry_loop_task = asyncio.create_task(telemetry_ingestion_loop())
    
    yield
    
    # Shutdown
    keep_running_loop = False
    if telemetry_loop_task:
        telemetry_loop_task.cancel()
    if current_source:
        await current_source.disconnect()
    logger.info("Application shutdown complete.")

app = FastAPI(
    title="THRUST-HM API",
    description="Backend API and Telemetry Router for Thruster Health Monitoring",
    version="1.0.0",
    lifespan=app_lifespan
)

# Enable CORS for frontend Vite dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins for V1 development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Schemas for Requests ---
class ThrusterRegister(BaseModel):
    id: str
    model: str
    serial_number: Optional[str] = None
    manufacturer: Optional[str] = None
    manufacture_date: Optional[str] = None
    installation_date: Optional[str] = None
    notes: Optional[str] = None

class PWMCommand(BaseModel):
    pwm: int

class FaultInjection(BaseModel):
    fault_type: str
    value: Any

class ReplayControl(BaseModel):
    action: str  # "play", "pause", "speed", "seek"
    speed: Optional[float] = None
    seek_percent: Optional[float] = None

class SourceSwitch(BaseModel):
    source_type: str  # "simulation", "replay"
    file_name: Optional[str] = None

# --- HTTP API Endpoints ---

@app.get("/api/thruster")
def get_thrusters():
    """List all registered thruster profiles."""
    return db_manager.get_all_thrusters()

@app.get("/api/thruster/{thruster_id}")
def get_thruster_profile(thruster_id: str):
    """Get metadata profile for a specific thruster."""
    profile = db_manager.get_thruster(thruster_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Thruster profile not found")
    return profile

@app.post("/api/thruster")
def register_thruster(thruster: ThrusterRegister):
    """Create or update a thruster profile."""
    try:
        db_manager.save_thruster(thruster.model_dump())
        return {"status": "SUCCESS", "message": f"Thruster {thruster.id} registered."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/telemetry/latest")
def get_latest_telemetry():
    """Returns the most recent processed telemetry sample."""
    if not latest_processed_sample:
        raise HTTPException(status_code=404, detail="No telemetry samples received yet")
    return latest_processed_sample

@app.get("/api/telemetry/history")
def get_telemetry_history(thruster_id: str = "T200-001", limit: int = Query(100, ge=1, le=1000)):
    """Fetch history of processed telemetry for plotting."""
    try:
        history = db_manager.get_telemetry_history(thruster_id, limit)
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/health/current")
def get_current_health(thruster_id: str = "T200-001"):
    """Get current health summary and interpretation."""
    profile = db_manager.get_thruster(thruster_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Thruster not found")
        
    if not latest_processed_sample:
        return {
            "health_score": 100.0,
            "health_state": "UNKNOWN",
            "confidence_score": 0.0,
            "interpretation": "Waiting for telemetry connection..."
        }
        
    score = latest_processed_sample.get("health_score", 100.0)
    state = latest_processed_sample.get("health_state", "HEALTHY")
    confidence = latest_processed_sample.get("confidence_score", 0.0)
    
    # Textual explanations (Interpretations)
    if state == "HEALTHY":
        interpretation = "Current behavior is consistent with the established healthy operating envelope."
    elif state == "MONITOR":
        interpretation = "Minor deviation detected. Monitor thruster signals and baseline logs closely."
    elif state == "WARNING":
        interpretation = "Significant deviation from nominal envelope. Inspect thruster for mechanical fouling or ESC wear."
    else:
        interpretation = "Severe operational deviation detected. Immediate action recommended to prevent thruster damage."
        
    return {
        "health_score": score,
        "health_state": state,
        "confidence_score": confidence,
        "interpretation": interpretation,
        "electrical_health": latest_processed_sample.get("electrical_health", 100.0),
        "thermal_health": latest_processed_sample.get("thermal_health", 100.0),
        "stability_health": latest_processed_sample.get("stability_health", 100.0)
    }

@app.get("/api/events")
def get_events(thruster_id: str = "T200-001", limit: int = Query(50, ge=1, le=200)):
    """Fetch the warning event log."""
    return db_manager.get_events(thruster_id, limit)

@app.get("/api/lifetime")
def get_lifetime_metrics(thruster_id: str = "T200-001"):
    """Fetch lifetime condition counters."""
    profile = db_manager.get_thruster(thruster_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Thruster not found")
        
    # Calculate calendar age from installation date
    install_date_str = profile.get("installation_date")
    calendar_age_days = 0
    if install_date_str:
        try:
            install_time = time.strptime(install_date_str, "%Y-%m-%d")
            install_epoch = time.mktime(install_time)
            calendar_age_days = int((time.time() - install_epoch) / 86400.0)
        except Exception:
            pass
            
    # Format age
    if calendar_age_days >= 365:
        age_str = f"{calendar_age_days / 365.0:.1f} years"
    else:
        age_str = f"{calendar_age_days} days"
        
    return {
        "thruster_id": thruster_id,
        "calendar_age": age_str,
        "operating_hours": round(profile.get("total_operating_hours", 0.0), 3),
        "energy_consumed_kwh": round(profile.get("total_energy_wh", 0.0) / 1000.0, 5),
        "operating_cycles": profile.get("operating_cycles", 0),
        "max_current_seen": round(profile.get("max_current", 0.0), 2),
        "max_temp_seen": round(profile.get("max_temp", 0.0), 1)
    }

# --- Control Endpoints ---

@app.post("/api/control/source")
async def switch_source(source_req: SourceSwitch):
    """Switch active source between simulation and CSV replay."""
    global current_source, active_source_type, csv_source
    target = source_req.source_type.lower()
    
    if target == "simulation":
        new_source = sim_source
    elif target == "replay":
        if source_req.file_name:
            sample_dir = resolve_path(sys_cfg.get("paths", {}).get("sample_dir", "data/sample"))
            replay_file = os.path.join(sample_dir, source_req.file_name)
            try:
                logger.info(f"Loading custom CSV file for replay: {replay_file}")
                csv_source = CSVReplaySource(
                    file_path=replay_file,
                    playback_speed=sys_cfg.get("replay", {}).get("playback_speed", 1.0)
                )
            except FileNotFoundError:
                raise HTTPException(status_code=404, detail=f"Custom CSV file not found: {source_req.file_name}")
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to load CSV: {str(e)}")
        
        if csv_source is None:
            raise HTTPException(status_code=400, detail="Replay source is unavailable (CSV not loaded)")
        new_source = csv_source
    else:
        raise HTTPException(status_code=400, detail="Invalid source type. Use 'simulation' or 'replay'")
        
    # Safely swap sources
    logger.info(f"Switching telemetry source to {target}")
    
    # 1. Stop current source
    if current_source:
        await current_source.disconnect()
    
    # 2. Connect new source
    await new_source.connect()
    
    # 3. Swap global reference
    current_source = new_source
    active_source_type = target
    
    # Reset data quality history
    health_engine.validator.clear_history()
    
    return {"status": "SUCCESS", "message": f"Telemetry source switched to {target}"}

@app.post("/api/control/pwm")
def send_pwm_command(cmd: PWMCommand):
    """Updates PWM value in simulation mode."""
    if active_source_type != "simulation" or sim_source is None:
        raise HTTPException(status_code=400, detail="PWM commands can only be sent in simulation mode")
    sim_source.set_pwm(cmd.pwm)
    return {"status": "SUCCESS", "pwm": cmd.pwm}

@app.post("/api/control/fault")
def inject_fault(fault: FaultInjection):
    """Injects or clears anomalies in simulation mode."""
    if active_source_type != "simulation" or sim_source is None:
        raise HTTPException(status_code=400, detail="Fault injection is only supported in simulation mode")
        
    f_type = fault.fault_type.lower()
    val = fault.value
    
    if f_type == "clear":
        sim_source.clear_faults()
        return {"status": "SUCCESS", "message": "All faults cleared"}
        
    sim_source.set_fault(f_type, val)
    return {"status": "SUCCESS", "fault": f_type, "value": val}

@app.post("/api/control/replay")
def control_replay(control: ReplayControl):
    """Controls the CSV replay parameters (play, pause, seek, speed)."""
    if active_source_type != "replay" or csv_source is None:
        raise HTTPException(status_code=400, detail="Replay controls are only supported in replay mode")
        
    action = control.action.lower()
    if action == "play":
        csv_source.resume()
    elif action == "pause":
        csv_source.pause()
    elif action == "speed":
        if control.speed is None:
            raise HTTPException(status_code=400, detail="Playback speed factor is required")
        csv_source.set_speed(control.speed)
    elif action == "seek":
        if control.seek_percent is None:
            raise HTTPException(status_code=400, detail="Seek percentage (0-100) is required")
        csv_source.seek(control.seek_percent)
    else:
        raise HTTPException(status_code=400, detail="Invalid replay control action")
        
    return {"status": "SUCCESS", "action": action}

# --- WebSocket Route ---

@app.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """WebSocket endpoint for real-time telemetry streaming."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep socket alive and receive client messages (e.g. commands)
            data = await websocket.receive_text()
            # We don't process complex actions via WS for now, keep it simple
            # but log it
            logger.info(f"WS client message: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        manager.disconnect(websocket)

# --- Static Frontend Serving ---
static_dir = resolve_path("frontend/dist")
if os.path.exists(static_dir):
    logger.info(f"Mounting static files from {static_dir}")
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
else:
    logger.warning(f"Static directory not found at {static_dir}. Static web serving will be disabled.")

if __name__ == "__main__":
    import uvicorn
    import sys
    import threading
    import webview
    
    host = sys_cfg.get("server", {}).get("host", "127.0.0.1")
    port = sys_cfg.get("server", {}).get("port", 8000)
    
    # 1. Start uvicorn server in a daemon thread
    def run_server():
        logger.info(f"Starting uvicorn server on {host}:{port}...")
        uvicorn.run(app, host=host, port=port, log_level="info", reload=False)
        
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # 2. Start desktop window wrapper on the main thread (blocks until closed)
    logger.info("Initializing desktop window manager...")
    webview.create_window(
        title="THRUST-HM // Thruster Health Monitoring System",
        url=f"http://{host}:{port}",
        width=1280,
        height=800,
        resizable=True,
        min_size=(1024, 768)
    )
    webview.start()
    logger.info("Desktop window closed. Exiting.")

