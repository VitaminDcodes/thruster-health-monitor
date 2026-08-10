# THRUST-HM // Thruster Health Monitoring System

THRUST-HM is a professional engineering-grade telemetry monitoring, drift analysis, and condition scoring dashboard designed for underwater ROV thrusters (T200-class). 

---

## Key Features

1.  **Physics-Informed Reference Model**: Leverages 2D regular grid interpolation (SciPy) over calibration maps (Voltage & PWM) to establish expected current draw and electrical power. Features grid proximity checks to identify VALID, LOW COVERAGE, or OUT OF RANGE inputs, degrading diagnostics confidence near or beyond limits.
2.  **State-of-the-Art Statistical Baseline**: Composes Welford's running statistics with a `collections.deque` (size 1000) rolling window array of residuals to compute exact Median, MAD (Median Absolute Deviation), and percentiles (P5, P25, P75, P95) on the fly.
3.  **Graceful Health Score Adaptation**: Prevents initial false alarms by checking baseline collection states (NOT ESTABLISHED, INSUFFICIENT, PRELIMINARY, VALIDATED). If the baseline is unestablished, Stability is marked N/A, and Electrical (62.5%) and Thermal (37.5%) weights are dynamically redistributed.
4.  **Sequential Drift (EWMA & CUSUM)**: Computes exponentially weighted moving averages and cumulative sum control charts on residuals to detect small or gradual drift.
5.  **Stateful Event Lifecycle Manager**: Avoids event database flooding by managing alarm states (NORMAL -> DETECTED -> ACTIVE -> RESOLVED) and updating a single row on active alarms.
6.  **Data Quality Safeguard**: Validates incoming packets for NaN dropouts, physical sensor out-of-bounds, stuck values, and timestamp gaps. Dynamically displays sample rate (Hz), packet loss %, dropout, and stuck registers counts.
7.  **Interactive Curve Overlay page**: Allows engineers to view live measured current and expected reference points overlaid in real-time on manufacturer T200 current curves at discrete voltages.
8.  **Single-Click Desktop Executable**: Compiles into a single-file executable `dist/thrust-hm.exe` that spins up the FastAPI backend and automatically launches the default web browser to the dashboard upon double-clicking.

---

## File Structure

```
thruster-health-monitor/
├── backend/                   # FastAPI Server, Database, Health Engines
│   ├── app/
│   │   ├── main.py            # API routes, websockets, worker loop
│   │   ├── database.py        # SQLite repository layer
│   │   ├── models/            # 2D Interpolation engine
│   │   └── engine/            # Health scoring, EWMA, CUSUM, Welford
│   └── requirements.txt       # Python backend dependencies
├── frontend/                  # Vite + React + TypeScript Dashboard
│   ├── src/
│   │   ├── App.tsx            # Main layout grids & control integrations
│   │   ├── index.css          # Monospace typography & clean css
│   │   ├── hooks/             # WebSocket connections & history fetchers
│   │   └── charts/            # Recharts technical chart components
│   └── package.json
├── config/                    # YAML configuration files
│   ├── system.yaml            # Paths, ports, simulation settings
│   └── health.yaml            # Physical bounds, filters, scoring weights
├── data/
│   ├── reference/             # Calibration performance curves (CSVs)
│   └── sample/                # Replay telemetry logs
├── docs/                      # Extensive engineering documentation
└── tests/                     # Automated backend test suites
```

---

## Installation & Setup

### Requirements
*   Python 3.10+ (tested up to 3.14)
*   Node.js (tested v24) / npm

### Step 1: Set up Backend Virtual Environment
```bash
# Navigate to repository directory
cd thruster-health-monitor-main

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (CMD):
.\venv\Scripts\activate.bat
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### Step 2: Set up Frontend node modules
```bash
cd frontend
npm install
```

---

## Running the Application

### 1. Start Python Backend
Make sure you are in the repository root folder with active venv:
```bash
# Run with uvicorn (FastAPI server)
uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
The server will start on `http://127.0.0.1:8000`. The WebSocket endpoint will run on `ws://127.0.0.1:8000/ws/telemetry`.

### 2. Start Frontend Dev Server
In a separate terminal shell inside the `frontend/` folder:
```bash
npm run dev
```
Open your browser at the displayed local URL (typically `http://localhost:5173`).

---

## Compiling Standalone Executable
You can compile a standalone, single-file Windows executable using PyInstaller:
```bash
# 1. Build the production assets of the React application
cd frontend
cmd.exe /c npm run build
cd ..

# 2. Compile using PyInstaller and the spec file
.\venv\Scripts\pyinstaller --clean thrust-hm.spec
```
The compiled program will be saved at `dist/thrust-hm.exe`. Double-clicking this file spins up the FastAPI backend server in the background and opens the dashboard inside a native, standalone desktop GUI application window (without showing any terminal console or opening an external browser). Closing the desktop window automatically shuts down the background server.

---

## Running Tests
Run pytest from the repository root:
```bash
# Run pytest tests inside venv
.\venv\Scripts\python -m pytest tests/
```

---

## Engineering Limitations
1.  **Fault Localization**: Telemetry indicators detect behavioral anomalies but cannot uniquely classify specific physical failures without custom signature models.
2.  **Environmental Influences**: External loading (e.g. biofouling, water density, currents) shifts actual current from static bollard specs. Dynamic baseline adaptation is required.
3.  **Health Index vs. RUL**: The Health Index is a condition consistency score (0-100), not an estimation of remaining physical lifetime.