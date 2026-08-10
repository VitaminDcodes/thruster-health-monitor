# THRUST-HM Database Schema

This document details the SQLite database design and tables for **THRUST-HM V1**.

---

## 1. Schema Diagram

```mermaid
erDiagram
    thrusters {
        TEXT id PK
        TEXT model
        TEXT serial_number
        TEXT manufacturer
        TEXT manufacture_date
        TEXT installation_date
        REAL total_operating_hours
        REAL total_energy_wh
        INTEGER operating_cycles
        REAL max_current
        REAL max_temp
        TEXT notes
    }

    telemetry {
        INTEGER id PK
        TEXT timestamp
        TEXT thruster_id FK
        INTEGER pwm
        REAL voltage
        REAL current_raw
        REAL current_filtered
        REAL esc_temperature_raw
        REAL esc_temperature_filtered
        REAL expected_current
        REAL expected_power
        REAL current_residual
        REAL current_residual_pct
        REAL power_residual
        REAL power_residual_pct
        REAL ewma_value
        REAL cusum_pos
        REAL cusum_neg
        REAL health_score
        TEXT health_state
        REAL confidence_score
    }

    health_events {
        INTEGER id PK
        TEXT timestamp
        TEXT thruster_id FK
        TEXT severity
        TEXT source
        TEXT message
        TEXT reason_code
        TEXT associated_metric
        REAL measured_value
        REAL expected_value
    }

    baseline_statistics {
        TEXT thruster_id PK
        TEXT operating_region PK
        INTEGER sample_count
        REAL mean_residual
        REAL m2_residual
        REAL min_residual
        REAL max_residual
    }

    thrusters ||--o{ telemetry : "contains history"
    thrusters ||--o{ health_events : "logs events"
    thrusters ||--o{ baseline_statistics : "calculates baseline"
```

---

## 2. Table Fields Reference

### 2.1 Table: `thrusters`
Stores metadata and accumulated lifetime characteristics of the thrusters.
*   `id`: Primary key (e.g. `"T200-001"`).
*   `total_operating_hours`: Total runtime hours accumulated while thruster is in an active operating state.
*   `total_energy_wh`: Integrated electric energy consumed over time (\(\int V \cdot I \cdot dt\) in Watt-hours).
*   `operating_cycles`: Count of transitions from a neutral state to an active state.

### 2.2 Table: `telemetry`
Primary time-series data table containing raw inputs and calculations.
*   Indexed by `timestamp` and `thruster_id` to guarantee fast retrieval for plotting.

### 2.3 Table: `health_events`
Stores warning logs, limits violations, sensor dropouts, and diagnostic status flags.
*   `severity`: `INFO`, `WARNING`, `CRITICAL`.
*   `source`: `DATA_QUALITY`, `ELECTRICAL`, `THERMAL`, `STABILITY`.

### 2.4 Table: `baseline_statistics`
Stores running statistical accumulators for Z-score checks across regions (NEUTRAL, LOW_PWM, FORWARD, REVERSE).
*   Uses Welford's algorithm variables (`mean_residual`, `m2_residual` sum of squares) to enable incremental updates.
