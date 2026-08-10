import sqlite3
import os
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        # Ensure directory exists
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # 1. Thrusters table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS thrusters (
            id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            serial_number TEXT,
            manufacturer TEXT,
            manufacture_date TEXT,
            installation_date TEXT,
            total_operating_hours REAL DEFAULT 0.0,
            total_energy_wh REAL DEFAULT 0.0,
            operating_cycles INTEGER DEFAULT 0,
            max_current REAL DEFAULT 0.0,
            max_temp REAL DEFAULT 0.0,
            notes TEXT
        );
        """)
        
        # 2. Telemetry table (indexed by timestamp & thruster_id)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            thruster_id TEXT NOT NULL,
            pwm INTEGER NOT NULL,
            voltage REAL NOT NULL,
            current_raw REAL NOT NULL,
            current_filtered REAL NOT NULL,
            esc_temperature_raw REAL NOT NULL,
            esc_temperature_filtered REAL NOT NULL,
            expected_current REAL NOT NULL,
            expected_power REAL NOT NULL,
            current_residual REAL NOT NULL,
            current_residual_pct REAL NOT NULL,
            power_residual REAL NOT NULL,
            power_residual_pct REAL NOT NULL,
            ewma_value REAL NOT NULL,
            cusum_pos REAL NOT NULL,
            cusum_neg REAL NOT NULL,
            health_score REAL NOT NULL,
            health_state TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            FOREIGN KEY (thruster_id) REFERENCES thrusters(id)
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_timestamp ON telemetry(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_thruster_id ON telemetry(thruster_id);")

        # 3. Health events table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            thruster_id TEXT NOT NULL,
            severity TEXT NOT NULL,
            source TEXT NOT NULL,
            message TEXT NOT NULL,
            reason_code TEXT,
            associated_metric TEXT,
            measured_value REAL,
            expected_value REAL,
            end_time TEXT,
            duration REAL,
            deviation REAL,
            status TEXT DEFAULT 'RESOLVED',
            event_id TEXT,
            FOREIGN KEY (thruster_id) REFERENCES thrusters(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON health_events(timestamp);")
        
        # Run migrations dynamically for existing SQLite database schemas
        cursor.execute("PRAGMA table_info(health_events);")
        existing_cols = [row["name"] for row in cursor.fetchall()]
        
        columns_to_add = [
            ("end_time", "TEXT"),
            ("duration", "REAL"),
            ("deviation", "REAL"),
            ("status", "TEXT DEFAULT 'RESOLVED'"),
            ("event_id", "TEXT")
        ]
        
        for col, col_type in columns_to_add:
            if col not in existing_cols:
                logger.info(f"Adding missing column {col} to health_events table...")
                try:
                    cursor.execute(f"ALTER TABLE health_events ADD COLUMN {col} {col_type};")
                except Exception as e:
                    logger.error(f"Migration warning adding column {col}: {e}")
                    
        # Create unique index after checking/migrating the event_id column
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_event_id ON health_events(event_id);")
        
        # 4. Baseline statistics table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS baseline_statistics (
            thruster_id TEXT NOT NULL,
            operating_region TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            mean_residual REAL NOT NULL,
            m2_residual REAL NOT NULL,
            min_residual REAL NOT NULL,
            max_residual REAL NOT NULL,
            PRIMARY KEY (thruster_id, operating_region),
            FOREIGN KEY (thruster_id) REFERENCES thrusters(id)
        );
        """)

        # 5. Lifetime statistics table (Section 50)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS lifetime_statistics (
            thruster_id TEXT PRIMARY KEY,
            operating_hours REAL DEFAULT 0.0,
            energy_wh REAL DEFAULT 0.0,
            operating_cycles INTEGER DEFAULT 0,
            max_current REAL DEFAULT 0.0,
            max_temp REAL DEFAULT 0.0,
            FOREIGN KEY (thruster_id) REFERENCES thrusters(id) ON DELETE CASCADE
        );
        """)

        # 6. Health assessments table (Section 50)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS health_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            thruster_id TEXT NOT NULL,
            health_score REAL NOT NULL,
            health_state TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            electrical_health REAL NOT NULL,
            thermal_health REAL NOT NULL,
            stability_health REAL NOT NULL,
            anomaly_score REAL NOT NULL,
            contributors TEXT,
            reason_codes TEXT,
            coverage_status TEXT,
            FOREIGN KEY (thruster_id) REFERENCES thrusters(id) ON DELETE CASCADE
        );
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_assessments_timestamp ON health_assessments(timestamp);")

        # 7. Reference models table (Section 50)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reference_models (
            model_name TEXT PRIMARY KEY,
            manufacturer TEXT,
            voltage_min REAL,
            voltage_max REAL,
            pwm_min REAL,
            pwm_max REAL,
            metadata_json TEXT
        );
        """)

        # 8. Configuration table (Section 50)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuration (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    # --- Thruster Profile Operations ---
    
    def save_thruster(self, t_profile: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        
        record = {
            "id": t_profile.get("id"),
            "model": t_profile.get("model", "T200"),
            "serial_number": t_profile.get("serial_number"),
            "manufacturer": t_profile.get("manufacturer"),
            "manufacture_date": t_profile.get("manufacture_date"),
            "installation_date": t_profile.get("installation_date"),
            "notes": t_profile.get("notes")
        }
        
        cursor.execute("""
        INSERT INTO thrusters (
            id, model, serial_number, manufacturer, manufacture_date, installation_date, notes
        ) VALUES (
            :id, :model, :serial_number, :manufacturer, :manufacture_date, :installation_date, :notes
        ) ON CONFLICT(id) DO UPDATE SET
            model = excluded.model,
            serial_number = excluded.serial_number,
            manufacturer = excluded.manufacturer,
            manufacture_date = excluded.manufacture_date,
            installation_date = excluded.installation_date,
            notes = excluded.notes;
        """, record)
        # Ensure default row exists in lifetime_statistics
        cursor.execute("""
        INSERT OR IGNORE INTO lifetime_statistics (thruster_id) VALUES (?);
        """, (t_profile["id"],))
        conn.commit()
        conn.close()

    def get_thruster(self, thruster_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM thrusters WHERE id = ?;", (thruster_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_all_thrusters(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM thrusters;")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_thruster_lifetime_metrics(self, thruster_id: str, 
                                         hours_increment: float, 
                                         energy_wh_increment: float,
                                         cycles_increment: int, 
                                         max_current: float, 
                                         max_temp: float):
        conn = self._get_connection()
        cursor = conn.cursor()
        # 1. Update thrusters table for compatibility
        cursor.execute("""
        UPDATE thrusters SET
            total_operating_hours = total_operating_hours + ?,
            total_energy_wh = total_energy_wh + ?,
            operating_cycles = operating_cycles + ?,
            max_current = CASE WHEN ? > max_current THEN ? ELSE max_current END,
            max_temp = CASE WHEN ? > max_temp THEN ? ELSE max_temp END
        WHERE id = ?;
        """, (hours_increment, energy_wh_increment, cycles_increment, 
              max_current, max_current, max_temp, max_temp, thruster_id))
        
        # 2. Update lifetime_statistics table
        cursor.execute("""
        UPDATE lifetime_statistics SET
            operating_hours = operating_hours + ?,
            energy_wh = energy_wh + ?,
            operating_cycles = operating_cycles + ?,
            max_current = CASE WHEN ? > max_current THEN ? ELSE max_current END,
            max_temp = CASE WHEN ? > max_temp THEN ? ELSE max_temp END
        WHERE thruster_id = ?;
        """, (hours_increment, energy_wh_increment, cycles_increment, 
              max_current, max_current, max_temp, max_temp, thruster_id))
        
        conn.commit()
        conn.close()

    def get_lifetime_statistics(self, thruster_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM lifetime_statistics WHERE thruster_id = ?;", (thruster_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    # --- Telemetry Operations ---

    def insert_telemetry(self, t_record: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO telemetry (
            timestamp, thruster_id, pwm, voltage, current_raw, current_filtered,
            esc_temperature_raw, esc_temperature_filtered, expected_current, expected_power,
            current_residual, current_residual_pct, power_residual, power_residual_pct,
            ewma_value, cusum_pos, cusum_neg, health_score, health_state, confidence_score
        ) VALUES (
            :timestamp, :thruster_id, :pwm, :voltage, :current_raw, :current_filtered,
            :esc_temperature_raw, :esc_temperature_filtered, :expected_current, :expected_power,
            :current_residual, :current_residual_pct, :power_residual, :power_residual_pct,
            :ewma_value, :cusum_pos, :cusum_neg, :health_score, :health_state, :confidence_score
        );
        """, t_record)
        conn.commit()
        conn.close()

    def get_telemetry_history(self, thruster_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM telemetry 
        WHERE thruster_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?;
        """, (thruster_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in reversed(rows)]

    # --- Event Log Operations ---

    def insert_event(self, event_record: Dict[str, Any]):
        # Fallback to save_or_update_event if event_id is supplied
        if "event_id" in event_record and event_record["event_id"]:
            return self.save_or_update_event(event_record)
            
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO health_events (
            timestamp, thruster_id, severity, source, message, reason_code,
            associated_metric, measured_value, expected_value, status
        ) VALUES (
            :timestamp, :thruster_id, :severity, :source, :message, :reason_code,
            :associated_metric, :measured_value, :expected_value, 'RESOLVED'
        );
        """, event_record)
        conn.commit()
        conn.close()

    def save_or_update_event(self, event_record: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO health_events (
            timestamp, thruster_id, severity, source, message, reason_code,
            associated_metric, measured_value, expected_value, end_time, duration, deviation, status, event_id
        ) VALUES (
            :timestamp, :thruster_id, :severity, :source, :message, :reason_code,
            :associated_metric, :measured_value, :expected_value, 
            :end_time, :duration, :deviation, :status, :event_id
        ) ON CONFLICT(event_id) DO UPDATE SET
            message = excluded.message,
            measured_value = excluded.measured_value,
            expected_value = excluded.expected_value,
            end_time = excluded.end_time,
            duration = excluded.duration,
            deviation = excluded.deviation,
            status = excluded.status,
            severity = excluded.severity;
        """, event_record)
        conn.commit()
        conn.close()

    def get_events(self, thruster_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM health_events 
        WHERE thruster_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?;
        """, (thruster_id, limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Health Assessments Operations ---

    def save_health_assessment(self, record: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO health_assessments (
            timestamp, thruster_id, health_score, health_state, confidence_score,
            electrical_health, thermal_health, stability_health, anomaly_score,
            contributors, reason_codes, coverage_status
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        );
        """, (
            record["timestamp"], record["thruster_id"], record["health_score"], record["health_state"],
            record["confidence_score"], record["electrical_health"], record["thermal_health"],
            record["stability_health"], record["anomaly_score"],
            json.dumps(record.get("contributors", [])),
            json.dumps(record.get("reason_codes", [])),
            record.get("coverage_status", "VALID")
        ))
        conn.commit()
        conn.close()

    def get_health_assessment_history(self, thruster_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT * FROM health_assessments 
        WHERE thruster_id = ? 
        ORDER BY timestamp DESC 
        LIMIT ?;
        """, (thruster_id, limit))
        rows = cursor.fetchall()
        conn.close()
        result = []
        for r in rows:
            d = dict(r)
            d["contributors"] = json.loads(d["contributors"] or "[]")
            d["reason_codes"] = json.loads(d["reason_codes"] or "[]")
            result.append(d)
        return result

    # --- Baseline Statistics Operations ---

    def save_baseline_stats(self, thruster_id: str, region: str, stats: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO baseline_statistics (
            thruster_id, operating_region, sample_count, mean_residual, m2_residual, min_residual, max_residual
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?
        ) ON CONFLICT(thruster_id, operating_region) DO UPDATE SET
            sample_count = excluded.sample_count,
            mean_residual = excluded.mean_residual,
            m2_residual = excluded.m2_residual,
            min_residual = excluded.min_residual,
            max_residual = excluded.max_residual;
        """, (thruster_id, region, stats["count"], stats["mean"], stats["m2"], stats["min"], stats["max"]))
        conn.commit()
        conn.close()

    def get_baseline_stats(self, thruster_id: str) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT operating_region, sample_count, mean_residual, m2_residual, min_residual, max_residual 
        FROM baseline_statistics 
        WHERE thruster_id = ?;
        """, (thruster_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # --- Reference Model Operations ---

    def save_reference_model(self, model: Dict[str, Any]):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO reference_models (
            model_name, manufacturer, voltage_min, voltage_max, pwm_min, pwm_max, metadata_json
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?
        ) ON CONFLICT(model_name) DO UPDATE SET
            manufacturer = excluded.manufacturer,
            voltage_min = excluded.voltage_min,
            voltage_max = excluded.voltage_max,
            pwm_min = excluded.pwm_min,
            pwm_max = excluded.pwm_max,
            metadata_json = excluded.metadata_json;
        """, (
            model["model_name"], model["manufacturer"], model["voltage_min"], model["voltage_max"],
            model["pwm_min"], model["pwm_max"], json.dumps(model.get("metadata", {}))
        ))
        conn.commit()
        conn.close()

    def get_reference_model(self, model_name: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reference_models WHERE model_name = ?;", (model_name,))
        row = cursor.fetchone()
        conn.close()
        if row:
            d = dict(row)
            d["metadata"] = json.loads(d["metadata_json"] or "{}")
            return d
        return None

    # --- Configuration Operations ---

    def save_config(self, key: str, value: Any):
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO configuration (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """, (key, json.dumps(value)))
        conn.commit()
        conn.close()

    def get_config(self, key: str) -> Optional[Any]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM configuration WHERE key = ?;", (key,))
        row = cursor.fetchone()
        conn.close()
        return json.loads(row["value"]) if row else None
