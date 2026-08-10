# THRUST-HM Anomaly Validation Principles

This document explains the validation principles implemented in **THRUST-HM V1** to avoid misleading diagnostic declarations.

---

## 1. Anomaly Detection vs. Fault Classification

### 1.1 Anomaly Detection (Implemented in V1)
Anomaly detection focuses on identifying deviations from a known healthy baseline:
*   **Question Answered**: *"Is the thruster behaving normally right now?"*
*   **Method**: Evaluates residuals between the actual telemetry and the 2D reference model. If the residuals deviate beyond statistical boundaries (Z-score, EWMA, CUSUM), an anomaly is declared.
*   **Actionable Output**: *"Measured current is 25% above expected. Health Index reduced."*
*   **Note**: The system does **NOT** attempt to diagnose the underlying mechanical or electrical cause (e.g. bearing wear vs shaft wrap).

### 1.2 Fault Classification (Future Roadmap)
Fault classification maps specific anomaly patterns (signatures) to physical failure modes:
*   **Question Answered**: *"What is wrong with the thruster?"*
*   **Method**: Pattern matching or machine learning models (e.g., Random Forest, XGBoost) trained on labeled failure datasets.
*   **Actionable Output**: *"Shaft binding detected (94% confidence) due to kelp wrapping."*

> [!WARNING]
> Without experimental validation data, declaring specific physical faults is scientifically invalid. Therefore, THRUST-HM V1 restricts itself to declaring "abnormal deviations" rather than naming specific physical failures.

---

## 2. Statistical Accuracy Reporting

### The Principle:
**Never report an "accuracy percentage" without a labeled validation dataset.**

*   Statements like *"The algorithm is 95% accurate"* are meaningless in engineering without stating the validation parameters (size, noise, labeled anomalies).
*   In THRUST-HM, the Health Index is a **condition indicator**, not an estimation of accuracy.
*   Future algorithms must be evaluated against independent, experimentally labeled datasets using robust metrics:
    *   **Precision**: Fraction of declared anomalies that are true faults.
    *   **Recall (Sensitivity)**: Fraction of true faults detected by the algorithm.
    *   **F1 Score**: Harmonic mean of Precision and Recall.
    *   **False Alarm Rate**: Rate of false alerts during healthy operation.
    *   **Detection Delay**: Time elapsed between fault onset and alert generation.
