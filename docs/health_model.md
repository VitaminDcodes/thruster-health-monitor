# THRUST-HM Health Model Documentation

This document describes the mathematical and statistical algorithms used in **THRUST-HM V1** to compute residuals, detect drifts, and formulate health index scoring.

---

## 1. Mathematical Formulations

### 1.1 Expected Behavior
The reference model predicts nominal performance based on a 2D calibration grid (Voltage vs. PWM):
\[ I_{expected} = f_{current}(PWM, Voltage) \]
\[ P_{expected} = f_{power}(PWM, Voltage) \]

### 1.2 Residual Calculations
To detect discrepancies between nominal and actual performance, we calculate residuals at each sample:
*   **Absolute Current Residual (\(R_I\))**:
    \[ R_I = I_{measured} - I_{expected} \]
*   **Normalized Current Residual (\(R_{I, norm}\))**:
    \[ R_{I, norm} = \frac{I_{measured} - I_{expected}}{\max(I_{expected}, 0.2\text{ A})} \]
*   **Absolute Power Residual (\(R_P\))**:
    \[ R_P = P_{measured} - P_{expected} \]
*   **Normalized Power Residual (\(R_{P, norm}\))**:
    \[ R_{P, norm} = \frac{P_{measured} - P_{expected}}{\max(P_{expected}, 2.0\text{ W})} \]

> [!NOTE]
> The division denominators are safeguarded near zero throttle regions to prevent numerical instability or extreme percentages caused by dividing by near-zero quiescent values.

---

## 2. Statistical Analysis Modules

### 2.1 EWMA (Exponentially Weighted Moving Average)
The EWMA is used to filter random sensor noise and highlight persistent shifts in normalized residuals:
\[ z_t = \lambda \cdot x_t + (1 - \lambda) \cdot z_{t-1} \]
Where:
*   \(x_t\) is the standardized residual Z-score at time \(t\).
*   \(\lambda\) is the smoothing coefficient (default: `0.15`), defining the memory depth.
*   An anomaly is flagged when \(|z_t| > \text{threshold}_{z} = 3.0\).

### 2.2 CUSUM (Cumulative Sum Control Chart)
CUSUM is optimized to detect small, persistent, gradual drifts or degradation (e.g. from bearing wear or fouling):
\[ S^+_t = \max(0, S^+_{t-1} + e_t - k) \]
\[ S^-_t = \max(0, S^-_{t-1} - e_t - k) \]
Where:
*   \(e_t\) is the standardized residual Z-score at time \(t\).
*   \(k\) is the slack parameter (default: `0.25`), representing the minimum shift size of interest.
*   A "Persistent deviation detected" warning is triggered if \(S^+_t > h\) or \(S^-_t > h\) (threshold \(h = 4.0\)).

### 2.3 Incremental Statistical Baseline (Welford's Algorithm)
To establish healthy operating parameters without consuming excessive memory, we calculate baseline stats dynamically per operating region using Welford's algorithm:
*   \(M_{1} = x_1, M_{k} = M_{k-1} + \frac{x_k - M_{k-1}}{k}\)
*   \(S_1 = 0, S_k = S_{k-1} + (x_k - M_{k-1})(x_k - M_k)\)
*   Variance: \(\sigma^2 = \frac{S_k}{k - 1}\)

If the baseline sample count \(k\) in a given region is less than the `min_samples_for_baseline` threshold (default: `150`), the system reports **"Baseline not established"** and overrides Z-scores.

---

## 3. Engineering Limitations & Caveats

> [!IMPORTANT]
> 1.  **Fault Localization**: Telemetry sensors (voltage, current, temperature, PWM) can identify the presence of behavioral anomalies but **cannot uniquely diagnose specific physical failure modes** (e.g., distinguishing between a cracked propeller blade and minor seaweed wrap).
> 2.  **Environmental Variability**: Operating context changes (e.g. water temperature, salinity, vehicle velocity, current, thruster fouling) alter the load on the thruster, shifting the measured current draw from static bollard reference specs. Platform-specific baselines are required.
> 3.  **Health Index Interpretation**: The Health Index is a **condition indicator (0-100)** describing consistency with a baseline, **NOT remaining useful physical life (RUL)**.
> 4.  **RUL Requirements**: Predicting actual remaining life requires run-to-failure experiments or validated long-term degradation models under controlled conditions.
