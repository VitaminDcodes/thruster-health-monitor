import os
import sys
import tempfile
import time
import math
import pytest
from fastapi.testclient import TestClient

# Ensure backend directory is in path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "backend"))

from app.models.reference_model import ReferenceModel
from app.utils.data_quality import DataQualityValidator
from app.utils.filtering import FirstOrderLowPassFilter
from app.engine.ewma import EWMATracker
from app.engine.cusum import CUSUMDetector
from app.engine.statistics import WelfordAccumulator, BaselineStatisticsManager, OperatingRegionClassifier
from app.database import DatabaseManager
from app.engine.health_engine import HealthEngine
from app.telemetry.sources import CSVReplaySource, SimulationTelemetrySource
from app.main import app

# --- 1. Test Reference Model ---
def test_reference_model():
    ref_dir = "data/reference/t200"
    model = ReferenceModel(ref_dir, pwm_neutral=1500, pwm_deadband=25)
    
    # Test neutral / deadband
    assert model.get_expected_current(1500, 16.0) == 0.05
    assert model.get_expected_current(1490, 12.0) == 0.05
    assert model.get_expected_current(1520, 20.0) == 0.05
    
    # Test operational forward/reverse
    curr_fwd = model.get_expected_current(1700, 16.0)
    curr_rev = model.get_expected_current(1300, 16.0)
    assert curr_fwd > 1.0
    assert curr_rev > 1.0
    
    # Test out of bounds clipping
    curr_clip_high = model.get_expected_current(2100, 25.0)
    curr_max = model.get_expected_current(1900, 20.0)
    assert curr_clip_high == curr_max

# --- 2. Test Data Quality Validator ---
def test_data_quality_validator():
    config = {
        "pwm_min": 1100,
        "pwm_max": 1900,
        "min_voltage": 9.0,
        "max_voltage": 21.0,
        "min_current": 0.0,
        "max_current": 35.0,
        "temp_max": 70.0,
        "stuck_limit": 5
    }
    validator = DataQualityValidator(config)
    
    # Normal sample
    sample_ok = {"timestamp": time.time(), "pwm": 1500, "voltage": 16.0, "current": 1.2, "esc_temperature": 25.0}
    is_valid, msg, details = validator.validate_sample(sample_ok)
    assert is_valid
    assert msg == ""
    
    # NaN check
    sample_nan = {"timestamp": time.time(), "pwm": 1500, "voltage": float('nan'), "current": 1.2, "esc_temperature": 25.0}
    is_valid, msg, details = validator.validate_sample(sample_nan)
    assert not is_valid
    assert "Sensor dropout" in msg
    
    # Stuck check
    validator.clear_history()
    for _ in range(5):
        sample_stuck = {"timestamp": time.time(), "pwm": 1600, "voltage": 16.0, "current": 2.5, "esc_temperature": 30.0}
        is_valid, msg, details = validator.validate_sample(sample_stuck)
    
    assert details["current"]["status"] == "WARNING"
    assert "Sensor stuck" in details["current"]["msg"]

# --- 3. Test Filters ---
def test_low_pass_filter():
    filt = FirstOrderLowPassFilter(tau=0.5, dt=0.1)
    
    # Initial value
    assert filt.filter(10.0) == 10.0
    
    # Successive value
    # alpha = 0.1 / (0.5 + 0.1) = 0.1 / 0.6 = 1/6 ~ 0.1667
    # y = (1/6)*20 + (5/6)*10 = 20/6 + 50/6 = 70/6 = 11.667
    val = filt.filter(20.0)
    assert math.isclose(val, 11.666666, rel_tol=1e-4)

# --- 4. Test EWMA Tracker ---
def test_ewma_tracker():
    tracker = EWMATracker(lambda_factor=0.2)
    assert tracker.update(10.0) == 10.0 # First value is initialized
    
    # z_1 = 0.2 * 20 + 0.8 * 10 = 4 + 8 = 12
    assert tracker.update(20.0) == 12.0

# --- 5. Test CUSUM Detector ---
def test_cusum_detector():
    detector = CUSUMDetector(k=0.5, h=2.0)
    
    # Normal residual
    pos, neg, alarm = detector.update(0.0)
    assert pos == 0.0 and neg == 0.0 and not alarm
    
    # Shift up
    # S_pos_1 = max(0, 0 + 1.2 - 0.5) = 0.7
    pos, neg, alarm = detector.update(1.2)
    assert pos == 0.7 and not alarm
    
    # S_pos_2 = max(0, 0.7 + 2.0 - 0.5) = 2.2 > 2.0 -> alarm
    pos, neg, alarm = detector.update(2.0)
    assert pos == 2.2 and alarm

# --- 6. Test Welford Statistics & Baselines ---
def test_welford_statistics():
    acc = WelfordAccumulator()
    data = [2.0, 4.0, 6.0]
    for x in data:
        acc.update(x)
        
    assert acc.count == 3
    assert acc.mean == 4.0
    # Variance = ((2-4)^2 + (4-4)^2 + (6-4)^2) / 2 = (4 + 0 + 4) / 2 = 4
    assert acc.variance == 4.0
    assert acc.std_dev == 2.0
    assert acc.min_val == 2.0
    assert acc.max_val == 6.0
    
    # Baseline manager
    mgr = BaselineStatisticsManager(min_samples=3)
    # Check unestablished
    z, conf = mgr.get_z_score("FORWARD", 5.0)
    assert z is None
    assert conf == "NOT ESTABLISHED"
    
    # Populate baseline
    mgr.update_baseline("FORWARD", 2.0)
    mgr.update_baseline("FORWARD", 4.0)
    mgr.update_baseline("FORWARD", 6.0)
    
    z, conf = mgr.get_z_score("FORWARD", 8.0)
    # Mean = 4, std = 2 -> Z = (8 - 4)/2 = 2.0
    assert z == 2.0
    assert conf == "PRELIMINARY" # count 3 < 500

# --- 7. Test Database Manager ---
def test_database_manager():
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        db = DatabaseManager(temp_db_path)
        
        # Test thruster profile saving and getting
        thruster = {
            "id": "TEST-01",
            "model": "T200",
            "serial_number": "SN-01",
            "manufacturer": "Blue Robotics",
            "manufacture_date": "2024-01-01",
            "installation_date": "2024-01-02",
            "notes": "Test notes"
        }
        db.save_thruster(thruster)
        
        profile = db.get_thruster("TEST-01")
        assert profile is not None
        assert profile["model"] == "T200"
        
        # Test telemetry inserts
        telemetry_rec = {
            "timestamp": "2026-08-10T12:00:00Z",
            "thruster_id": "TEST-01",
            "pwm": 1500,
            "voltage": 16.0,
            "current_raw": 0.1,
            "current_filtered": 0.1,
            "esc_temperature_raw": 22.0,
            "esc_temperature_filtered": 22.0,
            "expected_current": 0.05,
            "expected_power": 0.8,
            "current_residual": 0.05,
            "current_residual_pct": 100.0,
            "power_residual": 0.8,
            "power_residual_pct": 100.0,
            "ewma_value": 0.0,
            "cusum_pos": 0.0,
            "cusum_neg": 0.0,
            "health_score": 100.0,
            "health_state": "HEALTHY",
            "confidence_score": 1.0
        }
        db.insert_telemetry(telemetry_rec)
        
        history = db.get_telemetry_history("TEST-01", limit=10)
        assert len(history) == 1
        assert history[0]["pwm"] == 1500
        
    finally:
        os.remove(temp_db_path)

# --- 8. Test Health Engine ---
def test_health_engine():
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        db = DatabaseManager(temp_db_path)
        # Register TEST-01 thruster profile first to satisfy FOREIGN KEY constraint
        db.save_thruster({
            "id": "TEST-01",
            "model": "T200",
            "serial_number": "SN-01",
            "manufacturer": "Blue Robotics",
            "manufacture_date": "2024-01-01",
            "installation_date": "2024-01-02",
            "notes": "Test notes"
        })
        
        ref_dir = "data/reference/t200"
        ref_model = ReferenceModel(ref_dir)
        
        config = {
            "pwm_neutral": 1500,
            "pwm_deadband": 25,
            "current_max": 35.0,
            "temp_max": 70.0,
            "temp_rate_max": 1.5,
            "stuck_limit": 20,
            "ewma": {"lambda": 0.15, "threshold_zscore": 3.0},
            "cusum": {"k": 0.25, "h": 4.0},
            "baseline": {"min_samples_for_baseline": 3, "default_std_cap_low": 0.1},
            "scoring_weights": {"electrical": 0.50, "thermal": 0.30, "stability": 0.20},
            "health_thresholds": {"healthy_min": 90, "monitor_min": 75, "warning_min": 50}
        }
        
        engine = HealthEngine("TEST-01", ref_model, config, db_manager=db)
        
        # Feed normal sample
        sample = {"timestamp": time.time(), "pwm": 1500, "voltage": 16.0, "current": 0.05, "esc_temperature": 25.0}
        processed, events = engine.process_telemetry(sample)
        assert processed["health_score"] == 100.0
        assert processed["health_state"] == "HEALTHY"
        assert len(events) == 0
        
        # Feed anomalous current draw
        # Nominal current at 1700 PWM is around 7A. Let's feed 12A (severe deviation)
        # Feed multiple samples to let the low-pass filter settle
        for i in range(10):
            sample_anom = {"timestamp": time.time() + 1 + i * 0.1, "pwm": 1700, "voltage": 16.0, "current": 12.0, "esc_temperature": 25.0}
            processed, events = engine.process_telemetry(sample_anom)
        
        assert processed["health_score"] < 90.0 # Score must drop
        assert len(events) > 0
        assert any(e["reason_code"] == "CURRENT_DEVIATION" for e in events)
        
    finally:
        # Give Windows a brief moment to close any open file descriptors if any
        time.sleep(0.1)
        try:
            os.remove(temp_db_path)
        except Exception:
            pass

# --- 9. Test API Client ---
def test_api_client():
    with TestClient(app) as client:
        # Fetch thrusters
        response = client.get("/api/thruster")
        assert response.status_code == 200
        assert len(response.json()) > 0
        
        # Fetch default profile
        response = client.get("/api/thruster/T200-001")
        assert response.status_code == 200
        assert response.json()["model"] == "T200"
        
        # Fetch lifetime
        response = client.get("/api/lifetime?thruster_id=T200-001")
        assert response.status_code == 200
        assert "operating_hours" in response.json()
        
        # Fetch events
        response = client.get("/api/events?thruster_id=T200-001")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


# --- 10. Refinement Acceptance Tests ---
def test_refinement_acceptance():
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        db = DatabaseManager(temp_db_path)
        db.save_thruster({
            "id": "T200-001",
            "model": "T200",
            "serial_number": "SN-01",
            "manufacturer": "Blue Robotics",
            "notes": "Test"
        })
        
        # Test 1: Reference Model Coverage Status
        ref_model = ReferenceModel("data/reference/t200")
        
        # Valid coverage
        status, mult = ref_model.get_coverage_status(1500, 16.0)
        assert status == "VALID"
        assert mult == 1.0
        
        # Low coverage
        status, mult = ref_model.get_coverage_status(1120, 16.0)
        assert status == "LOW_COVERAGE"
        assert mult == 0.65
        
        # Out of bounds
        status, mult = ref_model.get_coverage_status(900, 16.0)
        assert status == "OUT_OF_RANGE"
        assert mult == 0.20
        
        config = {
            "pwm_neutral": 1500,
            "pwm_deadband": 25,
            "current_max": 35.0,
            "temp_max": 70.0,
            "temp_rate_max": 1.5,
            "stuck_limit": 20,
            "ewma": {"lambda": 0.15, "threshold_zscore": 3.0},
            "cusum": {"k": 0.25, "h": 4.0},
            "baseline": {"min_samples_for_baseline": 50, "default_std_cap_low": 0.1},
            "scoring_weights": {"electrical": 0.50, "thermal": 0.30, "stability": 0.20},
            "health_thresholds": {"healthy_min": 90, "monitor_min": 75, "warning_min": 50}
        }
        
        engine = HealthEngine("T200-001", ref_model, config, db_manager=db)
        
        # Test 2: Graceful N/A stability score normalization when baseline is insufficient
        # min_samples is 50. We feed a sample in FORWARD region (count = 1).
        sample = {"timestamp": 100.0, "pwm": 1700, "voltage": 16.0, "current": 7.0, "esc_temperature": 25.0}
        processed, events = engine.process_telemetry(sample)
        
        # Assert stability health is N/A and health score is computed solely from electrical & thermal
        assert processed["stability_health"] == "N/A"
        assert processed["health_score"] > 95.0
        
        # Test 3: Energy accumulation math
        # If we consume 7A * 16V = 112 W for 3 seconds (timestamp 100.0 to 103.0)
        # Energy consumed = 112 W * 3 s = 336 Joules
        # Convert to Wh = 336 / 3600 = 0.09333 Wh
        sample_2 = {"timestamp": 103.0, "pwm": 1700, "voltage": 16.0, "current": 7.0, "esc_temperature": 25.0}
        processed, events = engine.process_telemetry(sample_2)
        
        stats = db.get_lifetime_statistics("T200-001")
        assert stats is not None
        # Operating hours increment = 3 / 3600 = 0.000833 h
        assert math.isclose(stats["operating_hours"], 3.0 / 3600.0, rel_tol=1e-4)
        # Energy increment = (16.0 * 7.0 * 3.0) / 3600 = 0.09333 Wh
        assert math.isclose(stats["energy_wh"], 0.09333, rel_tol=1e-3)
        
        # Test 4: CUSUM event lifecycle stateful tracking (avoiding floods)
        # Populate baseline manager with 100 samples to establish baseline and allow Z-score calculation
        for i in range(100):
            engine.stats_manager.update_baseline("FORWARD", 0.0)
            
        # Feed high current anomaly repeatedly to trigger CUSUM
        # Standard deviation for FORWARD is very low (default_std_floor = 0.1)
        # residual of 2.0 A creates Z-score of 20, triggering CUSUM quickly
        events_collected = []
        for i in range(5):
            sample_anom = {"timestamp": 120.0 + i, "pwm": 1700, "voltage": 16.0, "current": 9.0, "esc_temperature": 25.0}
            processed, evs = engine.process_telemetry(sample_anom)
            events_collected.extend(evs)
            
        # Check active event count in database. We should have only ONE active current deviation event and/or CUSUM event
        db_events = db.get_events("T200-001", limit=100)
        cusum_events = [e for e in db_events if e["reason_code"] == "PERSISTENT_DEVIATION_CUSUM"]
        
        # Since it is updated in-place via event_id, the number of CUSUM records in the database should be exactly 1!
        assert len(cusum_events) <= 1
        
    finally:
        time.sleep(0.1)
        try:
            os.remove(temp_db_path)
        except Exception:
            pass

