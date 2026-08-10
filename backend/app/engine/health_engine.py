import time
import math
import logging
from typing import Dict, Any, List, Tuple, Optional

from app.models.reference_model import ReferenceModel
from app.utils.data_quality import DataQualityValidator
from app.utils.filtering import FirstOrderLowPassFilter
from app.engine.ewma import EWMATracker
from app.engine.cusum import CUSUMDetector
from app.engine.statistics import BaselineStatisticsManager, OperatingRegionClassifier, WelfordAccumulator

logger = logging.getLogger(__name__)

class HealthEngine:
    def __init__(self, thruster_id: str, ref_model: ReferenceModel, 
                 config_health: Dict[str, Any], db_manager: Any = None):
        self.thruster_id = thruster_id
        self.ref_model = ref_model
        self.config = config_health
        self.db = db_manager
        
        # Load configuration parameters
        self.pwm_neutral = self.config.get("pwm_neutral", 1500)
        self.pwm_deadband = self.config.get("pwm_deadband", 25)
        self.current_max = self.config.get("current_max", 35.0)
        self.temp_max = self.config.get("temp_max", 70.0)
        self.temp_rate_max = self.config.get("temp_rate_max", 1.5)
        
        # Scoring settings
        self.weights = self.config.get("scoring_weights", {"electrical": 0.50, "thermal": 0.30, "stability": 0.20})
        self.thresholds = self.config.get("health_thresholds", {"healthy_min": 90, "monitor_min": 75, "warning_min": 50})
        
        # Utilities setup
        self.validator = DataQualityValidator(self.config)
        
        # Filters (using first order low pass filter with tau = 0.5s, dt = 0.1s)
        self.current_filter = FirstOrderLowPassFilter(tau=0.5, dt=0.1)
        self.temp_filter = FirstOrderLowPassFilter(tau=1.0, dt=0.1)
        
        # Trackers
        ewma_cfg = self.config.get("ewma", {})
        self.ewma_tracker = EWMATracker(lambda_factor=ewma_cfg.get("lambda", 0.15))
        
        cusum_cfg = self.config.get("cusum", {})
        self.cusum_detector = CUSUMDetector(k=cusum_cfg.get("k", 0.25), h=cusum_cfg.get("h", 4.0))
        
        baseline_cfg = self.config.get("baseline", {})
        self.stats_manager = BaselineStatisticsManager(
            min_samples=baseline_cfg.get("min_samples_for_baseline", 150),
            default_std_floor=baseline_cfg.get("default_std_cap_low", 0.1)
        )
        
        # Load existing baseline statistics from database if available
        if self.db:
            baseline_records = self.db.get_baseline_stats(self.thruster_id)
            if baseline_records:
                self.stats_manager.load_from_db_records(baseline_records)
                
        # Internal states for state transition and tracking
        self.last_pwm: Optional[int] = None
        self.last_temp: Optional[float] = None
        self.last_temp_time: Optional[float] = None
        
        # Stateful event tracking cache to prevent database floods (Section 18 & 19)
        self.active_events: Dict[str, Dict[str, Any]] = {}
        
        # Operational cycle counter state
        self.cycle_in_progress = False
        
        # Diagnostic results
        self.last_health_score = 100.0
        self.last_health_state = "HEALTHY"
        self.total_energy_acc_wh = 0.0
        self.last_sample_time: Optional[float] = None

    def _track_event(self, event_key: str, active: bool, severity: str, source: str,
                     message: str, reason_code: str, metric: str,
                     measured_val: float, expected_val: float,
                     timestamp_str: str, t_now: float, events_list: List[Dict[str, Any]]):
        """
        Manages the lifecycle of a stateful alarm event (NORMAL -> ACTIVE -> RESOLVED)
        to prevent database event flooding (Section 18 & 19).
        """
        if active:
            if event_key not in self.active_events:
                # 1. Start a new event
                event_id = f"{event_key}_{int(t_now)}"
                event = {
                    "timestamp": timestamp_str,
                    "thruster_id": self.thruster_id,
                    "severity": severity,
                    "source": source,
                    "message": message,
                    "reason_code": reason_code,
                    "associated_metric": metric,
                    "measured_value": round(measured_val, 2),
                    "expected_value": round(expected_val, 2),
                    "end_time": None,
                    "duration": 0.0,
                    "deviation": round(measured_val - expected_val, 2),
                    "status": "ACTIVE",
                    "event_id": event_id,
                    "start_time": t_now
                }
                self.active_events[event_key] = event
                events_list.append(event)
                if self.db:
                    self.db.save_or_update_event(event)
            else:
                # 2. Update existing active event
                event = self.active_events[event_key]
                duration = t_now - event["start_time"]
                
                # Escalation logic (Section 19)
                current_severity = "ESCALATED" if duration > 15.0 else severity
                
                # Update metrics
                event["duration"] = round(duration, 1)
                event["measured_value"] = round(measured_val, 2)
                event["expected_value"] = round(expected_val, 2)
                event["deviation"] = round(measured_val - expected_val, 2)
                event["status"] = "ACTIVE"
                event["severity"] = current_severity
                event["message"] = f"{message} (Active for {duration:.1f}s, current deviation: {event['deviation']:+.2f})"
                
                events_list.append(event)
                if self.db:
                    self.db.save_or_update_event(event)
        else:
            if event_key in self.active_events:
                # 3. Resolve active event
                event = self.active_events.pop(event_key)
                duration = t_now - event["start_time"]
                event["end_time"] = timestamp_str
                event["duration"] = round(duration, 1)
                event["status"] = "RESOLVED"
                event["severity"] = "INFO"
                event["message"] = f"Resolved: {message} after {duration:.1f} seconds"
                
                events_list.append(event)
                if self.db:
                    self.db.save_or_update_event(event)

    def process_telemetry(self, raw_sample: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Processes a raw telemetry sample through the health analysis pipeline.
        Returns:
            - processed_sample (dict): Detailed computed fields.
            - generated_events (list): Triggered health warning/status events.
        """
        timestamp_str = raw_sample.get("timestamp_iso") or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        t_now = raw_sample.get("timestamp", time.time())
        
        pwm = raw_sample["pwm"]
        voltage = raw_sample["voltage"]
        current_raw = raw_sample["current"]
        temp_raw = raw_sample["esc_temperature"]
        
        events = []
        
        # 1. Validate Data Quality
        is_valid, dq_msg, dq_details = self.validator.validate_sample(raw_sample)
        if not is_valid:
            # Emit critical data quality event
            event = self._create_event_record(
                timestamp_str, "CRITICAL", "DATA_QUALITY",
                f"Data quality check failed: {dq_msg}", "DQ_FAULT",
                "telemetry", current_raw, 0.0
            )
            events.append(event)
            
            # Return degraded fallback state
            return {
                "timestamp": timestamp_str,
                "thruster_id": self.thruster_id,
                "pwm": pwm,
                "voltage": voltage,
                "current_raw": current_raw,
                "current_filtered": current_raw,
                "esc_temperature_raw": temp_raw,
                "esc_temperature_filtered": temp_raw,
                "expected_current": 0.05,
                "expected_power": 0.0,
                "current_residual": 0.0,
                "current_residual_pct": 0.0,
                "power_residual": 0.0,
                "power_residual_pct": 0.0,
                "ewma_value": 0.0,
                "cusum_pos": 0.0,
                "cusum_neg": 0.0,
                "health_score": 0.0,
                "health_state": "UNKNOWN",
                "confidence_score": 0.0,
                "operating_region": "UNKNOWN",
                "electrical_health": 0.0,
                "thermal_health": 0.0,
                "stability_health": "N/A",
                "anomaly_score": 0.0,
                "warnings": f"Degraded telemetry: {dq_msg}",
                "coverage_status": "OUT_OF_RANGE",
                "contributors": ["Data validation fault"],
                "reason_codes": ["DQ_FAULT"],
                "baseline_state": "NOT ESTABLISHED",
                "data_quality_metrics": dq_details.get("metrics", {})
            }, events

        # 2. Filter raw signals
        current_filt = self.current_filter.filter(current_raw)
        temp_filt = self.temp_filter.filter(temp_raw)
        
        # 3. Classify operating region (stateful transition checking)
        region = OperatingRegionClassifier.get_region(pwm, self.last_pwm, self.pwm_neutral, self.pwm_deadband)
        self.last_pwm = pwm
        
        # 4. Reference Model lookup & Coverage (Section 10 & 27)
        expected_current = self.ref_model.get_expected_current(pwm, voltage)
        expected_power = self.ref_model.get_expected_power(pwm, voltage)
        measured_power = voltage * current_filt
        
        coverage_status, coverage_mult = self.ref_model.get_coverage_status(pwm, voltage)
        
        # 5. Residuals calculation
        current_res = current_filt - expected_current
        power_res = measured_power - expected_power
        
        # Safeguards near neutral/zero operating points
        if region == "NEUTRAL":
            current_res_pct = 0.0
            power_res_pct = 0.0
        else:
            # Prevent division by zero near zero-current expected envelope
            safe_expected_curr = max(0.2, expected_current)
            current_res_pct = (current_res / safe_expected_curr) * 100.0
            
            safe_expected_power = max(2.0, expected_power)
            power_res_pct = (power_res / safe_expected_power) * 100.0
            
        # 6. Accumulate Running Statistics
        # We only update statistics when operation is stable (outside deadband & not starting up)
        if region != "NEUTRAL":
            self.stats_manager.update_baseline(region, current_res)
            if self.db and (int(time.time()) % 60 == 0): # Save periodically
                summary = self.stats_manager.get_stats_summary(region)
                if summary:
                    summary["m2"] = self.stats_manager.accumulators[region].m2
                    self.db.save_baseline_stats(self.thruster_id, region, summary)

        # 7. EWMA & CUSUM Updates
        # Skip EWMA/CUSUM in neutral region or if baseline is insufficient
        z_score_val, baseline_status = self.stats_manager.get_z_score(region, current_res)
        
        ewma_val = 0.0
        cusum_pos = 0.0
        cusum_neg = 0.0
        cusum_alarm = False
        ewma_alarm = False
        z_score = 0.0
        
        if region != "NEUTRAL" and z_score_val is not None:
            z_score = z_score_val
            # Update EWMA
            ewma_val = self.ewma_tracker.update(z_score)
            ewma_alarm = abs(ewma_val) > self.config.get("ewma", {}).get("threshold_zscore", 3.0)
            
            # Update CUSUM
            cusum_pos, cusum_neg, cusum_alarm = self.cusum_detector.update(z_score)
            
        # 8. Thermal Rate validation
        temp_rate = 0.0
        if self.last_temp is not None and self.last_temp_time is not None:
            dt = t_now - self.last_temp_time
            if dt > 0:
                temp_rate = (temp_filt - self.last_temp) / dt
        self.last_temp = temp_filt
        self.last_temp_time = t_now

        # 9. Anomaly detection & Event generation (stateful event tracking)
        # Apply wider tolerance for negative residuals (e.g. running in air / no-load)
        penalized_current_res_pct = current_res_pct
        if current_res_pct < 0:
            penalized_current_res_pct = current_res_pct * 0.20

        # Alarms triggers
        curr_dev_active = (region != "NEUTRAL" and abs(penalized_current_res_pct) > 25.0)
        temp_rate_active = (temp_rate > self.temp_rate_max)
        temp_limit_active = (temp_filt > self.temp_max)
        curr_limit_active = (current_filt > self.current_max)

        # Track stateful warnings (lifecycle handling)
        self._track_event(
            "CUSUM_DRIFT", cusum_alarm, "WARNING", "STABILITY",
            "Persistent current deviation detected by CUSUM algorithm",
            "PERSISTENT_DEVIATION_CUSUM", "current_residual", current_res, 0.0,
            timestamp_str, t_now, events
        )
        self._track_event(
            "CURRENT_DEVIATION", curr_dev_active,
            "CRITICAL" if abs(penalized_current_res_pct) > 40.0 else "WARNING", "ELECTRICAL",
            "Measured current deviates from T200 reference curve",
            "CURRENT_DEVIATION", "current", current_filt, expected_current,
            timestamp_str, t_now, events
        )
        self._track_event(
            "TEMP_RATE_LIMIT", temp_rate_active, "WARNING", "THERMAL",
            f"ESC temperature rising rapidly at {temp_rate:.2f}°C/s",
            "TEMP_RATE_LIMIT", "esc_temperature", temp_filt, self.last_temp or 0.0,
            timestamp_str, t_now, events
        )
        self._track_event(
            "TEMP_LIMIT_EXCEEDED", temp_limit_active, "CRITICAL", "THERMAL",
            f"ESC Temperature {temp_filt:.1f}°C exceeded safe limit of {self.temp_max}°C",
            "TEMP_LIMIT_EXCEEDED", "esc_temperature", temp_filt, self.temp_max,
            timestamp_str, t_now, events
        )
        self._track_event(
            "CURRENT_LIMIT_EXCEEDED", curr_limit_active, "CRITICAL", "ELECTRICAL",
            f"Supply current {current_filt:.1f}A exceeded safe operating envelope of {self.current_max}A",
            "CURRENT_LIMIT_EXCEEDED", "current", current_filt, self.current_max,
            timestamp_str, t_now, events
        )

        # 10. Compute health dimension scores
        # A. Electrical Health (decays from 100 based on current residual percentage)
        elec_score = 100.0 * math.exp(-abs(penalized_current_res_pct) / 20.0)
        
        # B. Thermal Health (decays as temp approaches temp_max, or if rate of change is high)
        temp_margin = self.temp_max - temp_filt
        if temp_margin <= 0:
            thermal_score = 0.0
        elif temp_filt <= 45.0:
            thermal_score = 100.0
        else:
            # Drop from 100 to 0 between 45C and temp_max (70C)
            thermal_score = 100.0 * (temp_margin / (self.temp_max - 45.0))
            
        # Penalize thermal score if rate of change is high
        if temp_rate > 0.5:
            thermal_score = max(0.0, thermal_score - (temp_rate - 0.5) * 15.0)
            
        # C. Stability Health (penalized by CUSUM values and EWMA deviation)
        # Graceful N/A Initialization if baseline is insufficient (Section 22)
        if z_score_val is None:
            stability_score = None
            stability_status_str = "N/A"
        else:
            stability_penalty = max(0.0, max(cusum_pos, cusum_neg) * 10.0)
            if ewma_alarm:
                stability_penalty += 15.0
            stability_score = max(0.0, 100.0 - stability_penalty)
            stability_status_str = f"{stability_score:.1f}"
        
        # D. Combined Health Index (0 to 100) (Redistribute weights if Stability is N/A)
        if stability_score is None:
            health_score = elec_score * 0.625 + thermal_score * 0.375
        else:
            health_score = (
                elec_score * self.weights.get("electrical", 0.50) +
                thermal_score * self.weights.get("thermal", 0.30) +
                stability_score * self.weights.get("stability", 0.20)
            )
        health_score = round(max(0.0, min(100.0, health_score)), 1)
        
        # Classify state
        if health_score >= self.thresholds.get("healthy_min", 90):
            health_state = "HEALTHY"
        elif health_score >= self.thresholds.get("monitor_min", 75):
            health_state = "MONITOR"
        elif health_score >= self.thresholds.get("warning_min", 50):
            health_state = "WARNING"
        else:
            health_state = "CRITICAL"
            
        self.last_health_score = health_score
        self.last_health_state = health_state
        
        # 11. Health Confidence Score (0.0 to 1.0)
        # Confidence depends on the quantity of baseline statistics samples
        if region != "NEUTRAL":
            stats_count = self.stats_manager.accumulators.get(region, WelfordAccumulator()).count
            if stats_count < self.stats_manager.min_samples:
                confidence = 0.20
            elif stats_count < 500:
                confidence = 0.65
            else:
                confidence = 0.95
        else:
            confidence = 0.95
            
        # Scale confidence based on Reference Model Coverage (Section 27)
        confidence = confidence * coverage_mult
        
        # Reduce confidence if we have severe sensor dropouts or validation details show warnings
        warning_counts = sum(1 for k, v in dq_details.items() if k != "metrics" and v.get("status") == "WARNING")
        confidence = max(0.0, confidence - warning_counts * 0.15)
        confidence = round(confidence, 2)
        
        # 12. Accumulate Lifetime parameters
        hours_inc = 0.0
        energy_wh_inc = 0.0
        cycles_inc = 0
        
        if self.last_sample_time is not None:
            dt = t_now - self.last_sample_time
            if dt > 0 and dt < 5.0: # exclude large telemetry gaps
                # Add operating hours if thruster is active (non-neutral PWM)
                if region != "NEUTRAL":
                    hours_inc = dt / 3600.0
                # Add energy consumed: Power (W) * dt (s) / 3600 = Wh
                energy_wh_inc = (measured_power * dt) / 3600.0
        self.last_sample_time = t_now
        
        # Track cycles
        if region != "NEUTRAL" and not self.cycle_in_progress:
            cycles_inc = 1
            self.cycle_in_progress = True
        elif region == "NEUTRAL":
            self.cycle_in_progress = False
            
        if self.db and (hours_inc > 0 or energy_wh_inc > 0 or cycles_inc > 0):
            self.db.update_thruster_lifetime_metrics(
                self.thruster_id, hours_inc, energy_wh_inc, cycles_inc,
                current_filt, temp_filt
            )

        # Collect contributors for explainability (Section 23 & 24)
        contributors = []
        reason_codes = []
        if region != "NEUTRAL" and abs(current_res_pct) > 15.0:
            contributors.append(f"Current deviation: {current_res_pct:+.1f}%")
            reason_codes.append("CURRENT_DEVIATION")
        if abs(power_res_pct) > 15.0:
            contributors.append(f"Power deviation: {power_res_pct:+.1f}%")
            reason_codes.append("POWER_DEVIATION")
        if temp_filt > 45.0:
            contributors.append(f"Elevated Temperature: {temp_filt:.1f}°C")
            reason_codes.append("ELEVATED_TEMPERATURE")
        if cusum_alarm:
            contributors.append("Stability penalty: CUSUM alarm active")
            reason_codes.append("CUSUM_ALARM")
        if ewma_alarm:
            contributors.append("Stability penalty: EWMA alarm active")
            reason_codes.append("EWMA_ALARM")
        if coverage_status != "VALID":
            contributors.append(f"Reference Coverage: {coverage_status}")
            reason_codes.append("COVERAGE_LIMITATION")

        processed_record = {
            "timestamp": timestamp_str,
            "thruster_id": self.thruster_id,
            "pwm": pwm,
            "voltage": round(voltage, 2),
            "current_raw": round(current_raw, 2),
            "current_filtered": round(current_filt, 2),
            "esc_temperature_raw": round(temp_raw, 1),
            "esc_temperature_filtered": round(temp_filt, 1),
            "expected_current": round(expected_current, 2),
            "expected_power": round(expected_power, 1),
            "current_residual": round(current_res, 3),
            "current_residual_pct": round(current_res_pct, 2),
            "power_residual": round(power_res, 2),
            "power_residual_pct": round(power_res_pct, 2),
            "ewma_value": round(ewma_val, 3),
            "cusum_pos": round(cusum_pos, 3),
            "cusum_neg": round(cusum_neg, 3),
            "health_score": health_score,
            "health_state": health_state,
            "confidence_score": confidence,
            "operating_region": region,
            "electrical_health": round(elec_score, 1),
            "thermal_health": round(thermal_score, 1),
            "stability_health": stability_status_str,
            "anomaly_score": round(abs(ewma_val), 2),
            "warnings": dq_msg,
            "coverage_status": coverage_status,
            "contributors": contributors,
            "reason_codes": reason_codes,
            "baseline_state": baseline_status,
            "data_quality_metrics": dq_details.get("metrics", {})
        }
        
        # Save to DB history
        if self.db:
            db_record = processed_record.copy()
            db_record["stability_health"] = -1.0 if stability_score is None else stability_score
            self.db.insert_telemetry(db_record)
            self.db.save_health_assessment(db_record)
            
        return processed_record, events

    def _create_event_record(self, timestamp: str, severity: str, source: str,
                              message: str, reason_code: str, associated_metric: str,
                              measured_value: float, expected_value: float) -> Dict[str, Any]:
        return {
            "timestamp": timestamp,
            "thruster_id": self.thruster_id,
            "severity": severity,
            "source": source,
            "message": message,
            "reason_code": reason_code,
            "associated_metric": associated_metric,
            "measured_value": round(measured_value, 2),
            "expected_value": round(expected_value, 2)
        }
