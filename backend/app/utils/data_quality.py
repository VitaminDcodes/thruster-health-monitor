import math
import numpy as np
import logging
from typing import Dict, Any, Tuple, List, Optional

logger = logging.getLogger(__name__)

class DataQualityValidator:
    def __init__(self, config_dq: Dict[str, Any]):
        self.config = config_dq
        
        # Operational limits
        self.pwm_min = self.config.get("pwm_min", 1100)
        self.pwm_max = self.config.get("pwm_max", 1900)
        self.min_voltage = self.config.get("min_voltage", 5.0)
        self.max_voltage = self.config.get("max_voltage", 24.0)
        self.min_current = self.config.get("min_current", -1.0)
        self.max_current = self.config.get("max_current", 40.0)
        self.temp_max = self.config.get("temp_max", 70.0)
        self.temp_rate_max = self.config.get("temp_rate_max", 1.5)
        
        # Stuck checks
        self.stuck_limit = self.config.get("stuck_limit", 20)
        self.history: Dict[str, List[float]] = {
            "pwm": [],
            "voltage": [],
            "current": [],
            "esc_temperature": []
        }
        
        # Continuity check
        self.last_timestamp: Optional[float] = None
        self.gap_limit = self.config.get("gap_limit_seconds", 3.0)

        # Dynamic data quality counters
        self.sensor_dropouts = 0
        self.timestamp_discontinuities = 0
        self.stuck_sensor_count = 0
        self.total_received_samples = 0
        self.t_start: Optional[float] = None
        
        # Sample rate tracking
        self.sample_times: List[float] = []
        self.sample_rate_hz = 10.0 # Default starting Hz

    def validate_sample(self, sample: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates a telemetry sample.
        Returns:
            - is_valid (bool): True if data can be processed.
            - error_msg (str): Summary error message.
            - details (dict): Quality reports per sensor and global metrics.
        """
        details = {
            "pwm": {"status": "GOOD", "msg": ""},
            "voltage": {"status": "GOOD", "msg": ""},
            "current": {"status": "GOOD", "msg": ""},
            "esc_temperature": {"status": "GOOD", "msg": ""}
        }
        
        is_valid = True
        error_reasons = []
        
        t = sample.get("timestamp")
        if t is None:
            return False, "Missing timestamp", details

        # Track sample times and compute rolling sample rate (Hz)
        self.sample_times.append(t)
        if len(self.sample_times) > 50:
            self.sample_times.pop(0)
        if len(self.sample_times) >= 2:
            dts = [self.sample_times[i] - self.sample_times[i-1] for i in range(1, len(self.sample_times))]
            # Filter zero/negative dts to avoid divisions by zero
            valid_dts = [d for d in dts if d > 0]
            if valid_dts:
                self.sample_rate_hz = round(1.0 / (sum(valid_dts) / len(valid_dts)), 1)

        # Start timer for packet loss calculations
        if self.t_start is None:
            self.t_start = t
        self.total_received_samples += 1
            
        if self.last_timestamp is not None:
            dt = t - self.last_timestamp
            if dt <= 0:
                is_valid = False
                error_reasons.append("Timestamp regression or duplicate")
            elif dt > self.gap_limit:
                self.timestamp_discontinuities += 1
                details["timestamp"] = {"status": "GAP", "msg": f"Discontinuity: Gap of {dt:.2f}s exceeded threshold"}
                logger.warning(details["timestamp"]["msg"])
        self.last_timestamp = t
        
        # Stuck sensor track counter resets for this sample
        current_stuck_warnings = 0

        # Helper to validate a specific numerical signal
        def check_signal(name: str, val: Any, low_limit: float, high_limit: float) -> Tuple[str, str]:
            nonlocal current_stuck_warnings
            if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
                self.sensor_dropouts += 1
                return "CRITICAL", f"Sensor dropout: {name} is NaN or Inf"
                
            if val < low_limit or val > high_limit:
                return "CRITICAL", f"{name} value {val} is outside physical bounds [{low_limit}, {high_limit}]"
                
            hist = self.history[name]
            hist.append(val)
            if len(hist) > self.stuck_limit:
                hist.pop(0)
                
            if len(hist) == self.stuck_limit:
                if all(x == hist[0] for x in hist):
                    if name != "pwm" or val != 1500:
                        current_stuck_warnings += 1
                        return "WARNING", f"Sensor stuck: {name} stuck at {val} for {self.stuck_limit} samples"
                        
            return "GOOD", ""

        # Validate parameters
        for field, (low, high) in {
            "pwm": (self.pwm_min - 100, self.pwm_max + 100),
            "voltage": (self.min_voltage, self.max_voltage),
            "current": (self.min_current, self.max_current),
            "esc_temperature": (-10.0, self.temp_max + 20.0)
        }.items():
            status, msg = check_signal(field, sample.get(field), low, high)
            details[field] = {"status": status, "msg": msg}
            if status == "CRITICAL":
                is_valid = False
                error_reasons.append(msg)

        # Update stuck sensor count register
        self.stuck_sensor_count = current_stuck_warnings

        # Estimate packet loss
        elapsed = t - self.t_start
        expected_samples = 1
        if elapsed > 0:
            # Replay or simulation nominal rate is 10Hz
            expected_samples = max(1, int(elapsed * 10.0))
        packet_loss = 100.0 * max(0.0, expected_samples - self.total_received_samples) / expected_samples
        packet_loss = round(min(100.0, packet_loss), 1)

        # Pack quality summary indicators
        details["metrics"] = {
            "sample_rate_hz": self.sample_rate_hz,
            "packet_loss_pct": packet_loss,
            "sensor_dropouts": self.sensor_dropouts,
            "timestamp_discontinuities": self.timestamp_discontinuities,
            "stuck_sensor_count": self.stuck_sensor_count,
            "total_received_samples": self.total_received_samples
        }
                
        error_msg = "; ".join(error_reasons) if error_reasons else ""
        return is_valid, error_msg, details
        
    def clear_history(self):
        for key in self.history:
            self.history[key].clear()
        self.last_timestamp = None
        self.sensor_dropouts = 0
        self.timestamp_discontinuities = 0
        self.stuck_sensor_count = 0
        self.total_received_samples = 0
        self.t_start = None
        self.sample_times.clear()
        self.sample_rate_hz = 10.0
