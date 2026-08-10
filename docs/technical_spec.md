# Thruster Health Monitoring System – Technical Specification

## Overview
The **Thruster Health Monitoring (THM) System** provides real‑time health assessment, fault detection, and diagnostic insight for single‑thruster propulsion units used in spacecraft test‑beds and operational missions.  It is an engineering‑oriented desktop application that aggregates telemetry, applies statistical and model‑based health metrics, and visualises the results in a concise dashboard.

---

## Architecture
- **Backend** – FastAPI service running in an embedded `uvicorn` server (daemon thread).  All health‑logic resides here.
- **Frontend** – HTML/JS UI bundled with the backend, rendered through **pywebview** to provide a native window without a browser console.
- **Packaging** – PyInstaller spec (`thrust-hm.spec`) builds a single executable (`.exe`) with `console=False` (no terminal) and includes required hidden imports (`pywebview`, `clr`, `pythonnet`, etc.).
- **Data Sources** – Telemetry CSVs / live socket streams feeding the backend via the `DataIngestor` component.

---

## Core Components
| Component | Responsibility | Key Classes/Modules |
|-----------|----------------|---------------------|
| **DataIngestor** | Reads raw telemetry, normalises timestamps, validates sampling rate. | `backend/app/ingest.py` |
| **ReferenceModel** | Stores nominal thrust curves (e.g., T200 reference data) and provides interpolation for expected performance. | `backend/app/models/reference.py` |
| **HealthEngine** | Computes health scores, confidence intervals, and anomaly flags using rolling‑window statistics (median, MAD, percentiles). | `backend/app/health/engine.py` |
| **AnomalyDetector** | Implements CUSUM drift detection and EWMA smoothing for early fault detection. | `backend/app/health/anomaly.py` |
| **ExplainabilityLayer** | Generates “Why” narratives based on rule‑based explanations (e.g., sensor dropout, packet loss). | `backend/app/health/explain.py` |
| **EventHandler** | Captures threshold breaches, logs events, and triggers UI notifications. | `backend/app/events.py` |
| **LifetimeCalculator** | Estimates remaining usable life using cumulative degradation metrics. | `backend/app/lifetime.py` |
| **API Router** | Exposes `/health`, `/reference`, `/events` endpoints consumed by the UI. | `backend/app/main.py` |
| **Frontend UI** | Tabbed dashboard (Overview, Diagnostics, T200 Reference) with plots (Plotly) and overlay panels. | `frontend/*.html`, `frontend/*.js` |

---

## Health Calculation Logic
1. **Pre‑processing** – Raw thrust, voltage, temperature streams are filtered for out‑of‑range values and resampled to a fixed 1 Hz grid.
2. **Rolling Statistics** – A configurable window (default 60 s) computes:
   - Median thrust
   - Median Absolute Deviation (MAD)
   - 5th/95th percentiles
3. **Health Score** – Normalised deviation from the reference thrust curve:
   ```
   health = 1 - |measured - reference| / reference
   ```
   Scores are clipped to `[0, 1]`.
4. **Confidence** – Bootstrap resampling of the window provides 95 % confidence bounds on the health score.
5. **Anomaly Detection** –
   - **CUSUM** detects sustained bias beyond a tolerance (`k=0.5`, `h=5`).
   - **EWMA** filters high‑frequency noise (`lambda=0.3`).
   - Flags are propagated to the UI and logged.

---

## Reference‑Model Integration (T200)
- Reference data (`data/T200_reference.csv`) contains thrust vs. command voltage curves for the T200 thruster.
- The model interpolates expected thrust for any commanded voltage using a cubic spline.
- The UI presents a tab where live data points overlay the reference curve, enabling visual deviation analysis.

---

## Explainability & Confidence Estimation
- The **ExplainabilityLayer** maps each health degradation event to a set of heuristics:
  - Sensor dropout → “Telemetry missing for > 2 s”.
  - Packet loss → “Lost X packets in last window”.
  - Statistical outlier → “Measured thrust deviates > 3 σ from median”.
- Confidence intervals derived from bootstrap are displayed alongside health scores; low confidence triggers a warning badge.

---

## Event Handling & Lifetime Calculations
- **EventHandler** emits JSON events (`event_type`, `timestamp`, `details`) consumed by the UI via Server‑Sent Events.
- Lifetime is calculated as:
  ```
  cumulative_degradation += (1 - health) * Δt
  remaining_life = max_life * (1 - cumulative_degradation)
  ```
  where `max_life` is a configurable design limit (default 10 000 s).

---

## Dashboard Information Architecture
- **Header** – System status, current health score, confidence badge.
- **Tabs** – Overview (summary), Diagnostics (plots, “Why” panel), T200 Reference (scatter + curve).
- **Overlay Panels** – Data‑quality indicators, anomaly alerts, event log.
- Designed for engineers: minimal colour palettes, clear units, no decorative animations.

---

## Engineering Credibility Measures
- All statistical thresholds are tunable via `config/health_config.yaml` and documented with rationale.
- Unit tests (`tests/`) cover ingestion, health calculation, anomaly detection, and API contracts.
- Continuous integration (GitHub Actions) runs linting (`flake8`), type checking (`mypy`), and test suite on each push.

---

## Build & Execution
1. **Development** – `pip install -r requirements.txt` then `python -m backend.app.main` (runs the embedded UI).
2. **Packaging** – `pyinstaller thrust-hm.spec` creates `dist/thruster_hm.exe` (no console, native window).
3. **Distribution** – Executable and source are hosted at <https://github.com/VitaminDcodes/thruster-health-monitor>.

---

## Repository Layout
```
thruster-health-monitor-main/
├── backend/                 # FastAPI service & health logic
├── frontend/                # HTML/JS UI assets
├── config/                  # YAML configuration files
├── data/                    # Reference curves, sample telemetry
├── docs/technical_spec.md   # This document
├── tests/                   # Unit and integration tests
├── thrust-hm.spec           # PyInstaller spec
├── README.md                # User guide & build instructions
└── .gitignore
```

---

*The THM system is intentionally engineered for robustness, transparency, and reproducibility. All algorithms are documented, configurable, and validated against synthetic and flight‑derived datasets.*
