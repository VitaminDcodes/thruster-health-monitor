# THRUST-HM Reference Model Documentation

This document explains the design, data structure, and implementation of the **T200 Thruster Reference Model** in **THRUST-HM V1**.

---

## 1. Mathematical Design

The performance curves supplied by Blue Robotics represent nominal operating limits in static "bollard pull" water conditions. Because current draw depends highly on both the input PWM throttle signal and the supply voltage (which fluctuates under load), a simple 1D curve is insufficient.

The system uses **2D bilinear interpolation** to map inputs to expected values:
*   Input dimension 1: **PWM Command** (\(\text{pwm}\) in \(\mu\text{s}\))
*   Input dimension 2: **Supply Voltage** (\(\text{voltage}\) in \(\text{V}\))

Outputs:
*   Expected Current (\(\text{A}\))
*   Expected Power (\(\text{W}\))
*   Expected Thrust (\(\text{kgf}\))
*   Expected RPM
*   Expected Efficiency (\(\text{gf/W}\))

---

## 2. Characterization Dataset Grid

The calibration datasets are located under `data/reference/t200/` as CSV files:
- `current_map.csv`
- `thrust_map.csv`
- `power_map.csv`
- `rpm_map.csv`
- `efficiency_map.csv`

### Schema Format:
Each file contains columns:
*   `pwm` (integer, e.g. 1100 to 1900 in increments of 25 µs)
*   `voltage` (float, e.g. 10.0, 12.0, 14.0, 16.0, 18.0, 20.0 V)
*   `value` (float, representing the calibrated metric value)

---

## 3. Interpolation Implementation (`app/models/reference_model.py`)

1.  **Grid Structuring**: On startup, the reference model loader pivots the CSV dataframe using the unique sorted values of `pwm` and `voltage` to build a structured 2D coordinate mesh and values array.
2.  **RegularGridInterpolator**: SciPy's `RegularGridInterpolator` is instantiated for each map. This is highly efficient and offers fast lookup speeds suitable for real-time loops.
3.  **Bypassing Neutral Zone (Deadband)**:
    For PWM inputs falling inside the deadband:
    \[ 1475 \le \text{PWM} \le 1525 \mu\text{s} \]
    The interpolator is bypassed. Expected current is set to the ESC's static quiescent draw (\(0.05\text{ A}\)) and expected power, thrust, and RPM are set to \(0.0\) (or quiescent power). This prevents false residual alarms when the motor is stopped.
4.  **Edge Behavior / Clipping**:
    If voltage or PWM inputs go outside the calibrated grid boundaries, the system clips the values to the min/max edges:
    *   \(\text{voltage}_{\text{clipped}} = \max(10.0, \min(20.0, \text{voltage}))\)
    *   \(\text{pwm}_{\text{clipped}} = \max(1100, \min(1900, \text{pwm}))\)
    This prevents SciPy from throwing out-of-bounds extrapolation errors, while the data-quality module generates alerts indicating that the inputs have exceeded safe calibration bounds.
