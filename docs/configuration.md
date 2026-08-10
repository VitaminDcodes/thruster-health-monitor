# THRUST-HM Configuration Reference

This document details the configuration parameters in **THRUST-HM V1** yaml configuration files.

---

## 1. System Config (`config/system.yaml`)

Defines network, SQLite database paths, simulation coefficients, and replay rules.

*   `server`:
    *   `host`: Server binding address (default: `"127.0.0.1"`).
    *   `port`: FastAPI listener port (default: `8000`).
*   `database`:
    *   `db_path`: Absolute file path to SQLite database.
*   `paths`:
    *   `reference_dir`: Folder containing T200 CSV performance maps.
    *   `sample_dir`: Folder containing CSV telemetry logs.
*   `simulation`:
    *   `noise`: Standard deviation of Gaussian sensor noise for voltage, current, and temperature.
    *   `esc_resistance`: ESC internal winding resistance (Ohms) used for simulation heat dissipation.
    *   `thermal_coupling`: Multiplier for ESC core heating per Watt of electrical power load.
    *   `thermal_dissipation`: Multiplier defining ESC cooling rate relative to water ambient temperature.

---

## 2. Health Engine Config (`config/health.yaml`)

Defines engineering bounds, analysis parameters, weights, and category thresholds.

*   `thruster`:
    *   `pwm_neutral`: Mid-point neutral signal in \(\mu\text{s}\) (default: `1500`).
    *   `pwm_deadband`: Inactive deadband threshold in \(\mu\text{s}\) (default: `25`). Bypasses expected current/power residual mapping when inside.
    *   `pwm_min` / `pwm_max`: Operational bounds of thruster (default: `1100` / `1900`).
    *   `voltage_min` / `voltage_max`: Nominal supply voltage bounds.
    *   `current_max` / `temp_max`: Absolute safe physical thresholds. Exceeding triggers CRITICAL event alerts.
*   `data_quality`:
    *   `stuck_limit`: Consecutive samples with identical sensor readings before a warning event is raised (default: `20`).
    *   `gap_limit_seconds`: Ingestion interval gaps before raising timestamp warnings (default: `3.0`).
*   `ewma`:
    *   `lambda`: Weight of the latest sample (default: `0.15`). Range `[0.0, 1.0]`. Lower values provide higher smoothing and slower detection delays.
    *   `threshold_zscore`: Standard deviation multiplier for anomaly triggers (default: `3.0`).
*   `cusum`:
    *   `k`: Slack parameter (default: `0.25`).
    *   `h`: Decision threshold for persistent deviation alerts (default: `4.0`).
*   `scoring_weights`:
    *   `electrical`: Weight of the electrical deviation index (default: `0.50`).
    *   `thermal`: Weight of the temperature index (default: `0.30`).
    *   `stability`: Weight of the statistical stability index (default: `0.20`).
*   `health_thresholds`:
    *   `healthy_min`: Minimum score for HEALTHY category (default: `90.0`).
    *   `monitor_min`: Minimum score for MONITOR category (default: `75.0`).
    *   `warning_min`: Minimum score for WARNING category (default: `50.0`).
