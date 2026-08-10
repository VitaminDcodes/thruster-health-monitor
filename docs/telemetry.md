# THRUST-HM Telemetry Specification

This document details the telemetry format, signal processing, validation rules, and playback sources for **THRUST-HM V1**.

---

## 1. Available Inputs

| PARAMETER | SYMBOL | DESCRIPTION | SIGNAL SOURCE | UNIT |
| :--- | :--- | :--- | :--- | :--- |
| **PWM Command** | \(PWM\) | Throttle control signal sent to ESC | Flight Controller / ESC | \(\mu\text{s}\) |
| **Supply Voltage** | \(V\) | DC Voltage of the power supply bus | ESC Telemetry / Power Module | \(\text{V}\) |
| **Current Draw** | \(I\) | DC Current drawn from power supply | ESC Telemetry / Current Shunt | \(\text{A}\) |
| **ESC Temperature** | \(T_{esc}\) | ESC core internal board temperature | ESC onboard NTC thermistor | \(\text{°C}\) |

---

## 2. Telemetry Sources Interface

All data ingestions implement the `TelemetrySource` interface:

```python
class TelemetrySource(ABC):
    @abstractmethod
    async def connect(self): ...
    @abstractmethod
    async def disconnect(self): ...
    @abstractmethod
    async def get_next_sample(self) -> Optional[dict]: ...
```

### 2.1 CSV Replay Source
Paces and parses pre-recorded lines from a CSV log:
*   Paces execution by computing delta timestamps and dividing by the speed factor.
*   Emits live timestamps overriding CSV epochs to make it synchronize with charts.
*   Supports Play, Pause, Seek (Scrub), and Speed adjustments.

### 2.2 Simulation Telemetry Source
Generates physical states in real time:
*   Current is simulated by scaling the T200 nominal curve.
*   Supply voltage drops dynamically (battery sag) proportional to current load.
*   ESC temperature is simulated using a first-order thermal model:
    \[ T_t = T_{t-1} + dt \times \left( I^2 \cdot R_{esc} \cdot c_{thermal} - (T_{t-1} - T_{ambient}) \cdot d_{thermal} \right) \]

---

## 3. Data Quality Checks

Each incoming telemetry packet is validated before ingestion:
1.  **Dropouts / NaN Check**: Discards packet if \(V\), \(I\), or \(T_{esc}\) contain `NaN` or `Inf`.
2.  **Physical Boundaries**: Discards packet if parameters exceed physical sensor limits (e.g. \(V < 5.0\text{V}\) or \(V > 24.0\text{V}\)).
3.  **Sensor Stuck check**: If a sensor value (excluding neutral PWM) remains identical for more than 20 consecutive samples, a warning event is raised.
4.  **Discontinuity check**: Flags a warning if the time interval between packets exceeds 3.0 seconds.

---

## 4. Signal Filtering

To prevent measurement noise from triggering false alarms, the raw current and temperature values are smoothed:
*   **Filter Type**: First-Order Digital Low-Pass Filter (Exponential Moving Average).
*   **Formula**:
    \[ y[k] = \alpha \cdot x[k] + (1 - \alpha) \cdot y[k-1] \]
    Where:
    *   \(\alpha = \frac{dt}{\tau + dt}\)
    *   \(dt = 0.1\text{ s}\) (sample interval)
    *   \(\tau_{current} = 0.5\text{ s}\) (time constant)
    *   \(\tau_{temp} = 1.0\text{ s}\) (time constant)
*   The raw signals are preserved in the database for post-analysis, and the filtered signals are used by the health engine.
