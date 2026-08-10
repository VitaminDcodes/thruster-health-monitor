import os
import csv
import time
import asyncio
import numpy as np
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class TelemetrySource(ABC):
    @abstractmethod
    async def connect(self):
        """Establish connection to the telemetry source."""
        pass
        
    @abstractmethod
    async def disconnect(self):
        """Close connection to the telemetry source."""
        pass
        
    @abstractmethod
    async def get_next_sample(self) -> Optional[Dict[str, Any]]:
        """
        Fetch the next telemetry sample.
        Returns a dict with: 'timestamp', 'pwm', 'voltage', 'current', 'esc_temperature'
        or None if no data is available (e.g. paused or EOF).
        """
        pass


class CSVReplaySource(TelemetrySource):
    def __init__(self, file_path: str, playback_speed: float = 1.0):
        self.file_path = file_path
        self.playback_speed = playback_speed
        
        self.samples: List[Dict[str, Any]] = []
        self.current_idx = 0
        self.is_connected = False
        self.is_playing = False
        
        # State control
        self.last_emitted_time: Optional[float] = None
        self.last_row_timestamp: Optional[float] = None
        
        self._load_csv()

    def _load_csv(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Replay CSV file not found: {self.file_path}")
            
        with open(self.file_path, mode="r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Expect columns: timestamp, pwm, voltage, current, esc_temperature
                try:
                    self.samples.append({
                        "timestamp": float(row["timestamp"]),
                        "pwm": int(row["pwm"]),
                        "voltage": float(row["voltage"]),
                        "current": float(row["current"]),
                        "esc_temperature": float(row["esc_temperature"])
                    })
                except (ValueError, KeyError) as e:
                    logger.warning(f"Skipping malformed row in replay CSV: {row}. Error: {e}")
                    
        logger.info(f"Loaded {len(self.samples)} samples from {self.file_path} for replay.")

    async def connect(self):
        self.is_connected = True
        self.is_playing = True
        self.current_idx = 0
        self.last_emitted_time = None
        self.last_row_timestamp = None
        logger.info("CSV Replay Source connected.")

    async def disconnect(self):
        self.is_connected = False
        self.is_playing = False
        logger.info("CSV Replay Source disconnected.")

    def pause(self):
        self.is_playing = False
        logger.info("CSV Replay paused.")

    def resume(self):
        self.is_playing = True
        self.last_emitted_time = None
        self.last_row_timestamp = None
        logger.info("CSV Replay resumed.")

    def set_speed(self, speed: float):
        if speed <= 0:
            logger.warning("Playback speed must be positive.")
            return
        self.playback_speed = speed
        logger.info(f"CSV Replay speed set to {speed}x.")

    def seek(self, progress_percent: float):
        """Seek to a position in the replay (0.0 to 100.0)."""
        if not self.samples:
            return
        idx = int((progress_percent / 100.0) * (len(self.samples) - 1))
        self.current_idx = max(0, min(idx, len(self.samples) - 1))
        self.last_emitted_time = None
        self.last_row_timestamp = None
        logger.info(f"Seeked replay to index {self.current_idx}/{len(self.samples)} ({progress_percent:.1f}%)")

    async def get_next_sample(self) -> Optional[Dict[str, Any]]:
        if not self.is_connected or not self.is_playing:
            await asyncio.sleep(0.1)
            return None
            
        if self.current_idx >= len(self.samples):
            # Loop playback or stop
            logger.info("Replay completed. Looping back to start.")
            self.current_idx = 0
            self.last_emitted_time = None
            self.last_row_timestamp = None
            
        sample = self.samples[self.current_idx]
        current_time = time.time()
        
        # Pace the playback
        if self.last_emitted_time is not None and self.last_row_timestamp is not None:
            # Time delta in CSV
            dt_csv = sample["timestamp"] - self.last_row_timestamp
            
            # Scaled delay
            delay = max(0.0, dt_csv / self.playback_speed)
            
            # Wait for appropriate duration
            elapsed = current_time - self.last_emitted_time
            remaining = delay - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
                
        self.last_emitted_time = time.time()
        self.last_row_timestamp = sample["timestamp"]
        
        # Update index
        self.current_idx += 1
        
        # Override timestamp with live system clock in UTC to make it feel "live"
        live_sample = sample.copy()
        live_sample["timestamp"] = time.time()
        return live_sample


class SimulationTelemetrySource(TelemetrySource):
    def __init__(self, update_rate_hz: float = 10.0, config_sim: Dict[str, Any] = None):
        self.update_rate_hz = update_rate_hz
        self.dt = 1.0 / update_rate_hz
        self.config = config_sim or {}
        
        # Models settings
        self.esc_resistance = self.config.get("esc_resistance", 0.02)
        self.thermal_coupling = self.config.get("thermal_coupling", 0.05)
        self.thermal_dissipation = self.config.get("thermal_dissipation", 0.02)
        self.ambient_temp = self.config.get("ambient_temp", 20.0)
        self.noise = self.config.get("noise", {"voltage": 0.05, "current": 0.08, "temperature": 0.1})
        
        # Live state
        self.is_connected = False
        self.pwm = 1500
        self.voltage = 16.0
        self.temperature = self.ambient_temp
        
        # Fault injection state
        self.faults: Dict[str, Any] = {
            "friction": 1.0,         # Multiplier to current draw (1.0 = normal)
            "dropout": False,        # If True, returns NaNs
            "thermal_runaway": False, # If True, temperature escalates
            "stuck_sensor": None,    # Dict with fields and values to keep stuck
            "voltage_sag": False     # If True, drops supply voltage below limits
        }

    async def connect(self):
        self.is_connected = True
        self.temperature = self.ambient_temp
        logger.info("Simulation Telemetry Source connected.")

    async def disconnect(self):
        self.is_connected = False
        logger.info("Simulation Telemetry Source disconnected.")

    def set_pwm(self, pwm: int):
        self.pwm = max(1000, min(2000, pwm))

    def set_fault(self, fault_type: str, value: Any):
        if fault_type in self.faults:
            self.faults[fault_type] = value
            logger.info(f"Simulation fault '{fault_type}' set to {value}.")
        else:
            logger.warning(f"Unknown fault type: {fault_type}")

    def clear_faults(self):
        self.faults = {
            "friction": 1.0,
            "dropout": False,
            "thermal_runaway": False,
            "stuck_sensor": None,
            "voltage_sag": False
        }
        logger.info("Simulation faults cleared.")

    async def get_next_sample(self) -> Optional[Dict[str, Any]]:
        if not self.is_connected:
            await asyncio.sleep(self.dt)
            return None
            
        # Run physics update loop step
        await asyncio.sleep(self.dt)
        
        # 1. Voltage Model
        # Basic supply: 16V nominal.
        # Under load, battery drops slightly. If voltage_sag fault is active, it drops to ~8.0V
        base_voltage = 8.5 if self.faults["voltage_sag"] else 16.2
        
        # 2. Current Model
        # Base T200 current model (similar to scripts/generate_reference_data.py)
        dp = self.pwm - 1500
        if abs(dp) <= 25:
            expected_current = 0.05
        else:
            u = (abs(dp) - 25) / (400 - 25)
            max_curr = 24.0 if dp > 0 else 20.2
            # Add voltage dependency
            voltage_factor = base_voltage / 16.0
            expected_current = max_curr * (0.3 * u + 0.7 * (u ** 2)) * voltage_factor
            
        # Apply friction fault multiplier
        simulated_current = expected_current * self.faults["friction"]
        
        # Apply battery voltage sag under load
        voltage = base_voltage - (simulated_current * 0.03)
        
        # 3. ESC Temperature Model
        # self-heating = I^2 * R
        heat_power = (simulated_current ** 2) * self.esc_resistance
        # thermal rate of change
        temp_rate = (heat_power * self.thermal_coupling) - (self.temperature - self.ambient_temp) * self.thermal_dissipation
        
        # Apply thermal runaway fault
        if self.faults["thermal_runaway"]:
            temp_rate += 1.8 # Rapidly heat up
            
        self.temperature += temp_rate * self.dt
        
        # Add noise
        v_noise = np.random.normal(0, self.noise.get("voltage", 0.05))
        i_noise = np.random.normal(0, self.noise.get("current", 0.08))
        t_noise = np.random.normal(0, self.noise.get("temperature", 0.1))
        
        final_voltage = max(0.0, voltage + v_noise)
        final_current = max(0.0, simulated_current + i_noise)
        final_temp = self.temperature + t_noise
        
        # Create output sample
        sample = {
            "timestamp": time.time(),
            "pwm": self.pwm,
            "voltage": round(final_voltage, 2),
            "current": round(final_current, 2),
            "esc_temperature": round(final_temp, 1)
        }
        
        # Apply faults: Stuck sensor values
        if self.faults["stuck_sensor"]:
            for field, stuck_val in self.faults["stuck_sensor"].items():
                if field in sample:
                    sample[field] = stuck_val
                    
        # Apply faults: Sensor dropout (NaN values)
        if self.faults["dropout"]:
            sample["voltage"] = float('nan')
            sample["current"] = float('nan')
            sample["esc_temperature"] = float('nan')
            
        return sample
