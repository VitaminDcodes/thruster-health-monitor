# THRUST-HM Project Versioning Roadmap

This document outlines the roadmap for the THRUST-HM system.

---

## 1. Version Releases

### V1.0 (Current Stable Version)
*   **Scope**: Single-Thruster Health Monitoring System.
*   **Features**:
    *   2D Reference Model interpolation (SciPy).
    *   Data quality checking (dropouts, stuck values, spikes).
    *   Exponential Low-Pass Filters on input signals.
    *   Real-time statistics (Welford's running variance).
    *   EWMA and CUSUM tracking of normalized residuals.
    *   Condition health score (0-100) and confidence.
    *   SQLite database storage & WebSocket broadcasting.
    *   Industrial test-bench dashboard (Vite + React + TS + Recharts).
    *   Replay from CSV logs & Physical simulator with fault injection.

---

### V2.0 (Future Multi-Thruster Architecture)
*   **Scope**: Multi-Thruster ROV Propulsion Health.
*   **Architecture Goals**:
    *   Expand backend ingestion to support independent `HealthEngine` instances mapped to unique `Thruster IDs` (e.g. `T200-001`, `T200-002`, ...).
    *   Modify database relations to support concurrent telemetry indexing by thruster.
    *   Do not rewrite the core health-monitoring algorithms. Keep the statistical and reference engines decoupled.

---

### V3.0 (ROV-Level Fault Localization)
*   **Scope**: Propulsion system cross-comparison.
*   **Features**:
    *   Implement an **ROV Propulsion Coordinator Engine** that compares thrusters against each other.
    *   If a vehicle is commanding forward thrust, all thrusters should see similar loads. If one thruster draws 40% more current than other identical thrusters, the vehicle-level coordinator can declare a localized fault on that specific thruster.
    *   Enables decoupling of environmental thrust loading from physical degradation.

---

### V4.0 (Advanced Predictive Maintenance)
*   **Scope**: Remaining Useful Life (RUL) estimation.
*   **Features**:
    *   Incorporate machine learning models (Isolation Forests, Autoencoders, LSTMs) once sufficient destruction testing logs have been gathered.
    *   Estimate MTBF (Mean Time Between Failures) and forecast maintenance windows based on historical cycle counts and temperature-current exposure integrals.
