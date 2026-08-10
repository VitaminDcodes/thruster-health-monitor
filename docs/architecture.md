# THRUST-HM System Architecture

This document describes the software architecture and data pipelines for **THRUST-HM V1**.

---

## 1. Component Block Diagram

```mermaid
graph TD
    subgraph Data Layer [Data Source & Database]
        CSV[Sample csv logs]
        SIM[Physical Simulator]
        DB[(SQLite DB)]
    end

    subgraph Backend [FastAPI Engine]
        TS[Telemetry Source Handler]
        QA[Data Quality Validator]
        LPF[Low-Pass Filters]
        REF[2D Reference Interpolator]
        HE[Health Engine]
        STATS[Baseline Stats Manager]
        WS[WebSocket Broadcast Server]
    end

    subgraph Frontend [React Workstation]
        UI[Industrial Dashboard]
        RC[Replay / Sim Controls]
        PLOT[Recharts Time-Series Charts]
        EVENT[Anomaly Log Table]
    end

    CSV -->|Read CSV Replay| TS
    SIM -->|Simulate Physics| TS
    TS -->|Raw Telemetry| QA
    QA -->|Valid Signals| LPF
    LPF -->|Filtered Signals| HE
    REF -->|Expected Values| HE
    HE -->|Residuals| STATS
    STATS -->|Standardized Residuals| HE
    HE -->|Assessed Health & Events| DB
    HE -->|Assessed Health & Events| WS
    WS -->|Live JSON Packets| UI
    RC -->|HTTP POST Control| Backend
    UI --> PLOT
    UI --> EVENT
```

---

## 2. Telemetry Ingestion Pipeline

1.  **Ingestion Interval**: Telemetry runs inside a background loop at **10 Hz** (defined in `config/system.yaml`).
2.  **TelemetrySource**: Abstract interface handles data retrieval.
    *   `CSVReplaySource`: Paces lines from a CSV log using timestamps.
    *   `SimulationTelemetrySource`: Updates synthetic physical states and applies active fault injection (friction, dropouts, thermal runaways, sag).
3.  **Data Quality Validation**: Check for dropouts, NaNs, sensor bounds, and stuck telemetry. Degraded samples are discarded, triggering info events to prevent model corruption.
4.  **Signal Filtering**: Filters raw noise on current and temperature using first-order low-pass (exponential) digital filters.
5.  **Reference Model Comparison**: Queries the 2D calibration grid via SciPy's bilinear/RegularGrid interpolator using filtered PWM and Voltage to compute expected values.
6.  **Anomaly Detection**: Evaluates running statistics, EWMA, and CUSUM deviations.
7.  **Database Storage**: Inserts raw/processed telemetry and triggered event alerts into SQLite.
8.  **WebSocket Broadcast**: Emits a combined JSON payload of telemetry, alerts, and replay status to all active client dashboards.
