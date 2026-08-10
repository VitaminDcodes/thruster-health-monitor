# THRUST-HM API Specification

This document details the FastAPI HTTP endpoints and WebSocket streaming protocol for **THRUST-HM V1**.

---

## 1. REST Endpoints (HTTP JSON)

### 1.1 `GET /api/thruster`
Returns a list of all registered thruster profiles.
*   **Response (JSON)**:
    ```json
    [
      {
        "id": "T200-001",
        "model": "T200",
        "serial_number": "SN-T200-A01",
        "manufacturer": "Blue Robotics",
        "total_operating_hours": 12.35,
        "max_current": 24.5
      }
    ]
    ```

### 1.2 `GET /api/thruster/{id}`
Returns details for a specific thruster.

### 1.3 `POST /api/thruster`
Registers or updates a thruster profile.

### 1.4 `GET /api/telemetry/history`
Fetches a list of historical telemetry samples for the charts.
*   **Query Parameters**:
    *   `thruster_id` (string, default: `"T200-001"`)
    *   `limit` (integer, range: 1–1000, default: `100`)
*   **Response (JSON)**: List of telemetry records sorted chronologically.

### 1.5 `GET /api/health/current`
Returns a summary of the current health score, state, component splits, and text interpretation.

### 1.6 `GET /api/lifetime`
Returns calculated lifetime parameters (calendar age, operating hours, operating cycles, energy consumed, maximum metrics).

### 1.7 `GET /api/events`
Returns list of warning events.

---

## 2. Control Endpoints (HTTP POST)

### 2.1 `POST /api/control/source`
Switches the telemetry source.
*   **Request (JSON)**:
    ```json
    { "source_type": "simulation" } // Options: "simulation", "replay"
    ```

### 2.2 `POST /api/control/pwm`
Commands the simulated thruster PWM throttle (simulation mode only).
*   **Request (JSON)**:
    ```json
    { "pwm": 1650 }
    ```

### 2.3 `POST /api/control/fault`
Injects or clears simulation anomalies.
*   **Request (JSON)**:
    ```json
    { "fault_type": "friction", "value": 1.35 }
    { "fault_type": "clear", "value": null }
    ```

### 2.4 `POST /api/control/replay`
Controls CSV log playback (replay mode only).
*   **Request (JSON)**:
    ```json
    { "action": "pause" } // Options: "play", "pause", "speed", "seek"
    ```

---

## 3. Real-Time Streaming (WebSockets)

### 3.1 Connection Endpoint
`WS /ws/telemetry`

### 3.2 Server Output Payload
Real-time JSON telemetry ticks are streamed at 10 Hz:
```json
{
  "type": "telemetry",
  "source_type": "simulation",
  "data": {
    "timestamp": "2026-08-10T15:20:00.123Z",
    "pwm": 1700,
    "voltage": 15.9,
    "current_raw": 6.25,
    "current_filtered": 6.12,
    "expected_current": 6.02,
    "current_residual": 0.1,
    "current_residual_pct": 1.66,
    "health_score": 98.5,
    "health_state": "HEALTHY"
  },
  "events": [],
  "replay_info": null
}
```
