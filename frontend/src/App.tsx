import React, { useState, useEffect } from "react";
import { useWebSocket } from "./hooks/useWebSocket";
import { RealTimeChart } from "./charts/RealTimeChart";
import * as Recharts from "recharts";

// Dynamic API and WebSocket configuration
const getBackendUrls = () => {
  const protocol = window.location.protocol || "http:";
  
  // Dev mode (Vite running on port 5173) -> target backend on port 8000
  if (window.location.port === "5173") {
    return {
      api: "http://127.0.0.1:8000",
      ws: "ws://127.0.0.1:8000/ws/telemetry"
    };
  }
  
  // Prod mode (served by the FastAPI app / executable) -> use current host
  return {
    api: `${protocol}//${window.location.host}`,
    ws: `${protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/telemetry`
  };
};

const urls = getBackendUrls();
const API_URL = urls.api;
const WS_URL = urls.ws;

export const App: React.FC = () => {
  const {
    connected,
    telemetry,
    history,
    events,
    sourceType,
    replayInfo,
    refreshHistory
  } = useWebSocket(WS_URL, API_URL);

  const [lifetime, setLifetime] = useState<any>({
    calendar_age: "0 days",
    operating_hours: 0,
    energy_consumed_kwh: 0,
    operating_cycles: 0,
    max_current_seen: 0,
    max_temp_seen: 0
  });

  const [simPwm, setSimPwm] = useState<number>(1500);
  const [activeFaults, setActiveFaults] = useState<string[]>([]);
  const [selectedCsv, setSelectedCsv] = useState<string>("sample_telemetry.csv");
  const [activeTab, setActiveTab] = useState<"charts" | "reference">("charts");

  const generateReferenceCurvesData = () => {
    const data = [];
    for (let pwm = 1100; pwm <= 1900; pwm += 20) {
      const dp = pwm - 1500;
      const abs_dp = Math.abs(dp);
      const c12 = abs_dp < 25 ? 0.05 : (abs_dp - 25) ** 2 * 0.000075 * (pwm > 1500 ? 1.0 : 0.92);
      const c16 = abs_dp < 25 ? 0.05 : (abs_dp - 25) ** 2 * 0.000115 * (pwm > 1500 ? 1.0 : 0.92);
      const c20 = abs_dp < 25 ? 0.05 : (abs_dp - 25) ** 2 * 0.000165 * (pwm > 1500 ? 1.0 : 0.92);
      data.push({
        pwm,
        "T200 Ref @ 12V (A)": parseFloat(c12.toFixed(2)),
        "T200 Ref @ 16V (A)": parseFloat(c16.toFixed(2)),
        "T200 Ref @ 20V (A)": parseFloat(c20.toFixed(2)),
      });
    }
    return data;
  };

  const referenceCurvesData = generateReferenceCurvesData();
  const liveOperatingPoint = telemetry ? [{
    pwm: telemetry.pwm,
    "Live Operating Point (Measured)": telemetry.current_filtered,
    "Live Operating Point (Expected)": telemetry.expected_current
  }] : [];

  const getStabilityHealthText = (val: any) => {
    if (val === "N/A" || val === null || val === undefined) return "N/A";
    const num = typeof val === "number" ? val : parseFloat(val);
    return isNaN(num) ? "N/A" : `${num.toFixed(1)}%`;
  };

  const getStabilityHealthPercent = (val: any): number => {
    if (val === "N/A" || val === null || val === undefined) return 0;
    const num = typeof val === "number" ? val : parseFloat(val);
    return isNaN(num) ? 0 : num;
  };

  // Fetch lifetime data periodically
  useEffect(() => {
    const fetchLifetime = async () => {
      try {
        const res = await fetch(`${API_URL}/api/lifetime?thruster_id=T200-001`);
        if (res.ok) {
          const data = await res.json();
          setLifetime(data);
        }
      } catch (e) {
        console.error("Error fetching lifetime metrics:", e);
      }
    };

    fetchLifetime();
    const interval = setInterval(fetchLifetime, 2000);
    return () => clearInterval(interval);
  }, [telemetry]);

  // Synchronize simulation slider state when telemetry arrives
  useEffect(() => {
    if (telemetry && sourceType === "simulation") {
      setSimPwm(telemetry.pwm);
    }
  }, [telemetry, sourceType]);


  // Control APIs
  const handleSourceChange = async (type: "simulation" | "replay", fileName?: string) => {
    const fileToLoad = fileName || (type === "replay" ? selectedCsv : undefined);
    try {
      const res = await fetch(`${API_URL}/api/control/source`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_type: type, file_name: fileToLoad })
      });
      if (res.ok) {
        // Reset fault state client-side
        setActiveFaults([]);
        refreshHistory();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handlePwmChange = async (val: number) => {
    setSimPwm(val);
    try {
      await fetch(`${API_URL}/api/control/pwm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pwm: val })
      });
    } catch (e) {
      console.error(e);
    }
  };

  const handleInjectFault = async (faultType: string, value: any) => {
    try {
      const res = await fetch(`${API_URL}/api/control/fault`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fault_type: faultType, value: value })
      });
      if (res.ok) {
        if (value === false || value === 1.0) {
          setActiveFaults((prev) => prev.filter((f) => f !== faultType));
        } else {
          setActiveFaults((prev) => [...new Set([...prev, faultType])]);
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleClearFaults = async () => {
    try {
      const res = await fetch(`${API_URL}/api/control/fault`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fault_type: "clear", value: null })
      });
      if (res.ok) {
        setActiveFaults([]);
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleReplayAction = async (action: string, extra: any = {}) => {
    try {
      await fetch(`${API_URL}/api/control/replay`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...extra })
      });
    } catch (e) {
      console.error(e);
    }
  };

  // Status helper mapping
  const getStatusClass = (state: string) => {
    switch (state) {
      case "HEALTHY": return "status-healthy";
      case "MONITOR": return "status-monitor";
      case "WARNING": return "status-warning";
      case "CRITICAL": return "status-critical";
      default: return "status-neutral";
    }
  };

  return (
    <div className="dashboard-container">
      {/* Top Header Panel */}
      <header className="header-panel">
        <h1 className="header-title" style={{ margin: 0, fontSize: "16px" }}>Thrust-HM // Thruster Health Monitor</h1>
        <div className="header-status-group align-center">
          <div>
            System:{" "}
            <span className={`status-pill ${connected ? "status-healthy" : "status-critical"}`}>
              {connected ? "ONLINE" : "OFFLINE"}
            </span>
          </div>
          <div>
            Source:{" "}
            <span className="status-pill status-neutral" style={{ color: "#fff" }}>
              {sourceType.toUpperCase()}
            </span>
          </div>
          <div>
            Thruster ID: <span className="num-val">T200-001</span>
          </div>
        </div>
      </header>

      {/* Main Dashboard Layout */}
      <main className="dashboard-body">
        {/* Left Column: Health Profile & Lifetime */}
        <section className="panel" style={{ gridRow: "span 2" }}>
          <div className="panel-header">Health Status</div>
          {telemetry ? (
            <div className="flex-col gap-10">
              <div className="flex-row space-between align-center">
                <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>OVERALL INDEX</span>
                <span className={`status-pill ${getStatusClass(telemetry.health_state)}`}>
                  {telemetry.health_state}
                </span>
              </div>
              <div className="num-val" style={{ fontSize: "42px", fontWeight: "700", lineHeight: "1.0", margin: "10px 0" }}>
                {(telemetry.health_score ?? 0).toFixed(1)}<span style={{ fontSize: "16px", color: "var(--text-muted)" }}>/100</span>
              </div>
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", lineHeight: "1.4" }}>
                <strong>Confidence:</strong> {(telemetry.confidence_score ?? 0) > 0.8 ? "HIGH" : (telemetry.confidence_score ?? 0) > 0.5 ? "MEDIUM" : "LOW"} ({(telemetry.confidence_score ?? 0).toFixed(2)})
                <br />
                <strong>Region:</strong> {telemetry.operating_region || "UNKNOWN"}
              </div>
              
              <div style={{ borderTop: "1px solid var(--panel-border)", padding: "8px 0", marginTop: "5px" }}>
                <div style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase" }}>Interpretation</div>
                <div style={{ fontSize: "11px", color: "var(--text-primary)", marginTop: "4px", lineHeight: "1.3" }}>
                  {telemetry.health_state === "HEALTHY" && "Current behavior is consistent with the established healthy operating envelope."}
                  {telemetry.health_state === "MONITOR" && "Minor deviation detected. Monitor thruster signals and baseline logs closely."}
                  {telemetry.health_state === "WARNING" && "Significant deviation. Check for shaft binding, propeller fouling, or ESC deterioration."}
                  {telemetry.health_state === "CRITICAL" && "Severe fault condition detected. Shut down immediately to prevent hardware damage."}
                </div>
              </div>
              
              {/* Explainable Health details / Why Panel */}
              <div style={{ borderTop: "1px solid var(--panel-border)", padding: "8px 0", marginTop: "5px" }}>
                <div style={{ fontSize: "10px", color: "var(--text-muted)", textTransform: "uppercase", fontWeight: "bold" }}>Health Assessment Details</div>
                <div className="flex-col gap-5" style={{ fontSize: "11px", marginTop: "5px" }}>
                  <div>
                    <strong>Baseline State:</strong>{" "}
                    <span className="num-val" style={{ color: telemetry.baseline_state === "VALIDATED" ? "var(--color-healthy)" : "var(--color-warning)" }}>
                      {telemetry.baseline_state || "NOT ESTABLISHED"}
                    </span>
                  </div>
                  <div>
                    <strong>Model Coverage:</strong>{" "}
                    <span className="num-val" style={{ color: telemetry.coverage_status === "VALID" ? "var(--color-healthy)" : "var(--color-warning)" }}>
                      {telemetry.coverage_status || "VALID"}
                    </span>
                  </div>
                  {telemetry.contributors && telemetry.contributors.length > 0 && (
                    <div style={{ marginTop: "3px" }}>
                      <strong>Active Decays:</strong>
                      <ul style={{ margin: "2px 0 0 10px", padding: 0, listStyleType: "square", color: "var(--text-secondary)" }}>
                        {telemetry.contributors.map((contrib: string, idx: number) => (
                          <li key={idx}>{contrib}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div style={{ fontStyle: "italic", fontSize: "10px", color: "var(--text-muted)", marginTop: "8px", borderLeft: "2px solid #575765", paddingLeft: "5px" }}>
                    * No specific physical fault has been confirmed.
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>Waiting for telemetry...</div>
          )}

          {/* Health Components */}
          <div className="panel-header" style={{ marginTop: "20px" }}>Health Metrics</div>
          {telemetry ? (
            <div className="flex-col gap-10" style={{ fontSize: "12px" }}>
              <div>
                <div className="flex-row space-between" style={{ marginBottom: "2px" }}>
                  <span>Electrical Integrity</span>
                  <span className="num-val">{(telemetry.electrical_health ?? 0).toFixed(1)}%</span>
                </div>
                <div className="progress-bar-bg">
                  <div className="progress-bar-fill" style={{ width: `${telemetry.electrical_health ?? 0}%`, backgroundColor: (telemetry.electrical_health ?? 0) > 75 ? "var(--color-healthy)" : (telemetry.electrical_health ?? 0) > 50 ? "var(--color-warning)" : "var(--color-critical)" }} />
                </div>
              </div>
              <div>
                <div className="flex-row space-between" style={{ marginBottom: "2px" }}>
                  <span>Thermal Integrity</span>
                  <span className="num-val">{(telemetry.thermal_health ?? 0).toFixed(1)}%</span>
                </div>
                <div className="progress-bar-bg">
                  <div className="progress-bar-fill" style={{ width: `${telemetry.thermal_health ?? 0}%`, backgroundColor: (telemetry.thermal_health ?? 0) > 75 ? "var(--color-healthy)" : (telemetry.thermal_health ?? 0) > 50 ? "var(--color-warning)" : "var(--color-critical)" }} />
                </div>
              </div>
              <div>
                <div className="flex-row space-between" style={{ marginBottom: "2px" }}>
                  <span>Operational Stability</span>
                  <span className="num-val">
                    {getStabilityHealthText(telemetry.stability_health)}
                  </span>
                </div>
                <div className="progress-bar-bg">
                  <div className="progress-bar-fill" style={{ 
                    width: `${getStabilityHealthPercent(telemetry.stability_health)}%`, 
                    backgroundColor: telemetry.stability_health === "N/A" ? "#4a5568" : (getStabilityHealthPercent(telemetry.stability_health) > 75 ? "var(--color-healthy)" : (getStabilityHealthPercent(telemetry.stability_health) > 50 ? "var(--color-warning)" : "var(--color-critical)")) 
                  }} />
                </div>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>No metrics loaded</div>
          )}

          {/* Lifetime Profile */}
          <div className="panel-header" style={{ marginTop: "20px" }}>Lifetime / History</div>
          <div className="flex-col gap-10" style={{ fontSize: "11px" }}>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Calendar Age:</span>
              <span className="num-val">{lifetime.calendar_age}</span>
            </div>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Operating Time:</span>
              <span className="num-val">{(lifetime.operating_hours ?? 0).toFixed(4)} h</span>
            </div>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Operating Cycles:</span>
              <span className="num-val">{lifetime.operating_cycles ?? 0}</span>
            </div>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Total Energy:</span>
              <span className="num-val">{(lifetime.energy_consumed_kwh ?? 0).toFixed(4)} kWh</span>
            </div>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Max Current:</span>
              <span className="num-val" style={{ color: "var(--color-warning)" }}>{(lifetime.max_current_seen ?? 0).toFixed(2)} A</span>
            </div>
            <div className="flex-row space-between">
              <span style={{ color: "var(--text-secondary)" }}>Max ESC Temp:</span>
              <span className="num-val" style={{ color: "var(--color-critical)" }}>{(lifetime.max_temp_seen ?? 0).toFixed(1)} °C</span>
            </div>
          </div>

          {/* Data Quality Monitor Panel */}
          <div className="panel-header" style={{ marginTop: "20px" }}>Data Quality Monitor</div>
          {telemetry && telemetry.data_quality_metrics ? (
            <div className="flex-col gap-10" style={{ fontSize: "11px" }}>
              <div className="flex-row space-between">
                <span style={{ color: "var(--text-secondary)" }}>Sample Rate (Hz):</span>
                <span className="num-val" style={{ color: telemetry.data_quality_metrics.sample_rate_hz < 8.0 ? "var(--color-warning)" : "var(--color-healthy)" }}>
                  {telemetry.data_quality_metrics.sample_rate_hz} Hz
                </span>
              </div>
              <div className="flex-row space-between">
                <span style={{ color: "var(--text-secondary)" }}>Packet Loss Rate:</span>
                <span className="num-val" style={{ color: telemetry.data_quality_metrics.packet_loss_pct > 5.0 ? "var(--color-warning)" : "var(--color-healthy)" }}>
                  {telemetry.data_quality_metrics.packet_loss_pct} %
                </span>
              </div>
              <div className="flex-row space-between">
                <span style={{ color: "var(--text-secondary)" }}>Sensor Dropouts (NaNs):</span>
                <span className="num-val" style={{ color: telemetry.data_quality_metrics.sensor_dropouts > 0 ? "var(--color-critical)" : "inherit" }}>
                  {telemetry.data_quality_metrics.sensor_dropouts}
                </span>
              </div>
              <div className="flex-row space-between">
                <span style={{ color: "var(--text-secondary)" }}>Time Discontinuities:</span>
                <span className="num-val" style={{ color: telemetry.data_quality_metrics.timestamp_discontinuities > 0 ? "var(--color-warning)" : "inherit" }}>
                  {telemetry.data_quality_metrics.timestamp_discontinuities}
                </span>
              </div>
              <div className="flex-row space-between">
                <span style={{ color: "var(--text-secondary)" }}>Active Stuck Sensors:</span>
                <span className="num-val" style={{ color: telemetry.data_quality_metrics.stuck_sensor_count > 0 ? "var(--color-warning)" : "inherit" }}>
                  {telemetry.data_quality_metrics.stuck_sensor_count}
                </span>
              </div>
            </div>
          ) : (
            <div style={{ color: "var(--text-muted)", fontSize: "11px" }}>Data quality monitor offline</div>
          )}
        </section>

        {/* Center Top: Real-Time Telemetry & Residuals */}
        <section className="panel">
          <div className="panel-header">Live Telemetry & Performance Residuals</div>
          <div className="telemetry-grid">
            <div className="telemetry-card">
              <span className="telemetry-label">PWM Command</span>
              <div className="telemetry-value-row">
                <span className="telemetry-number num-val">{telemetry ? telemetry.pwm : "1500"}</span>
                <span className="telemetry-unit">µs</span>
              </div>
            </div>
            <div className="telemetry-card">
              <span className="telemetry-label">Supply Voltage</span>
              <div className="telemetry-value-row">
                <span className="telemetry-number num-val">{telemetry ? (telemetry.voltage ?? 0).toFixed(2) : "16.00"}</span>
                <span className="telemetry-unit">V</span>
              </div>
            </div>
            <div className="telemetry-card">
              <span className="telemetry-label">Current Draw</span>
              <div className="telemetry-value-row">
                <span className="telemetry-number num-val">{telemetry ? (telemetry.current_raw ?? 0).toFixed(2) : "0.00"}</span>
                <span className="telemetry-unit">A</span>
              </div>
              <span style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>
                Filt: {telemetry ? (telemetry.current_filtered ?? 0).toFixed(2) : "0.0"}A
              </span>
            </div>
            <div className="telemetry-card">
              <span className="telemetry-label">Electric Power</span>
              <div className="telemetry-value-row">
                <span className="telemetry-number num-val">
                  {telemetry ? ((telemetry.voltage ?? 0) * (telemetry.current_filtered ?? 0)).toFixed(1) : "0.0"}
                </span>
                <span className="telemetry-unit">W</span>
              </div>
            </div>
            <div className="telemetry-card">
              <span className="telemetry-label">ESC Temperature</span>
              <div className="telemetry-value-row">
                <span className="telemetry-number num-val">{telemetry ? (telemetry.esc_temperature_raw ?? 0).toFixed(1) : "20.0"}</span>
                <span className="telemetry-unit">°C</span>
              </div>
              <span style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "2px" }}>
                Filt: {telemetry ? (telemetry.esc_temperature_filtered ?? 0).toFixed(1) : "20.0"}°C
              </span>
            </div>
          </div>

          {/* Expected vs Measured Comparison table */}
          <div style={{ marginTop: "15px", borderTop: "1px solid var(--panel-border)", paddingTop: "10px" }}>
            <table className="tech-table">
              <thead>
                <tr>
                  <th>METRIC</th>
                  <th>MEASURED (FILT)</th>
                  <th>EXPECTED (REF)</th>
                  <th>DEVIATION (RESIDUAL)</th>
                  <th>PERCENT RESIDUAL</th>
                </tr>
              </thead>
              <tbody>
                {telemetry ? (
                  <>
                    <tr>
                      <td>Current Draw (A)</td>
                      <td className="num-val">{(telemetry.current_filtered ?? 0).toFixed(2)} A</td>
                      <td className="num-val">{(telemetry.expected_current ?? 0).toFixed(2)} A</td>
                      <td className="num-val" style={{ color: Math.abs(telemetry.current_residual ?? 0) > 1.5 ? "var(--color-warning)" : "inherit" }}>
                        {(telemetry.current_residual ?? 0) > 0 ? "+" : ""}{(telemetry.current_residual ?? 0).toFixed(3)} A
                      </td>
                      <td className="num-val" style={{ color: Math.abs(telemetry.current_residual_pct ?? 0) > 15 ? "var(--color-warning)" : "inherit" }}>
                        {(telemetry.current_residual_pct ?? 0) > 0 ? "+" : ""}{(telemetry.current_residual_pct ?? 0).toFixed(2)} %
                      </td>
                    </tr>
                    <tr>
                      <td>Electric Power (W)</td>
                      <td className="num-val">{((telemetry.voltage ?? 0) * (telemetry.current_filtered ?? 0)).toFixed(1)} W</td>
                      <td className="num-val">{(telemetry.expected_power ?? 0).toFixed(1)} W</td>
                      <td className="num-val" style={{ color: Math.abs(telemetry.power_residual ?? 0) > 10.0 ? "var(--color-warning)" : "inherit" }}>
                        {(telemetry.power_residual ?? 0) > 0 ? "+" : ""}{(telemetry.power_residual ?? 0).toFixed(1)} W
                      </td>
                      <td className="num-val" style={{ color: Math.abs(telemetry.power_residual_pct ?? 0) > 15 ? "var(--color-warning)" : "inherit" }}>
                        {(telemetry.power_residual_pct ?? 0) > 0 ? "+" : ""}{(telemetry.power_residual_pct ?? 0).toFixed(1)} %
                      </td>
                    </tr>
                  </>
                ) : (
                  <tr>
                    <td colSpan={5} style={{ textAlign: "center", color: "var(--text-muted)" }}>
                      Telemetry offline
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Right Column: Controller Interface & Fault Injector */}
        <section className="panel" style={{ gridRow: "span 2" }}>
          <div className="panel-header">Controller Panel</div>
          <div className="flex-col gap-10">
            {/* Mode selection buttons */}
            <div className="flex-row gap-10">
              <button
                className={`tech-btn w-full ${sourceType === "simulation" ? "active" : ""}`}
                onClick={() => handleSourceChange("simulation")}
              >
                SIMULATION
              </button>
              <button
                className={`tech-btn w-full ${sourceType === "replay" ? "active" : ""}`}
                onClick={() => handleSourceChange("replay")}
              >
                CSV REPLAY
              </button>
            </div>

            {/* Simulation controls */}
            {sourceType === "simulation" && (
              <div style={{ borderTop: "1px solid var(--panel-border)", marginTop: "10px", paddingTop: "10px" }}>
                <div style={{ fontSize: "11px", fontWeight: "600", marginBottom: "8px", textTransform: "uppercase", color: "var(--text-secondary)" }}>
                  Simulation Signal Generator
                </div>
                
                {/* PWM slider */}
                <div className="flex-col gap-10" style={{ marginBottom: "15px" }}>
                  <div className="flex-row space-between" style={{ fontSize: "11px" }}>
                    <span>PWM Command Input:</span>
                    <span className="num-val" style={{ color: "var(--color-info)" }}>{simPwm} µs</span>
                  </div>
                  <input
                    type="range"
                    min="1100"
                    max="1900"
                    step="10"
                    value={simPwm}
                    onChange={(e) => handlePwmChange(Number(e.target.value))}
                    style={{ width: "100%", accentColor: "var(--color-info)" }}
                  />
                  <div className="flex-row gap-10">
                    <button className="tech-btn" onClick={() => handlePwmChange(1100)}>Max Rev (1100)</button>
                    <button className="tech-btn" onClick={() => handlePwmChange(1500)}>Neutral (1500)</button>
                    <button className="tech-btn" onClick={() => handlePwmChange(1900)}>Max Fwd (1900)</button>
                  </div>
                </div>

                {/* Fault injections */}
                <div style={{ borderTop: "1px solid var(--panel-border)", paddingTop: "10px" }}>
                  <div style={{ fontSize: "11px", fontWeight: "600", marginBottom: "8px", textTransform: "uppercase", color: "var(--text-secondary)" }}>
                    Fault Injector (Passive Testing)
                  </div>
                  <div className="flex-col gap-10">
                    <button
                      className={`tech-btn ${activeFaults.includes("friction") ? "status-warning" : ""}`}
                      onClick={() => handleInjectFault("friction", activeFaults.includes("friction") ? 1.0 : 1.35)}
                      style={{ justifyContent: "left" }}
                    >
                      {activeFaults.includes("friction") ? "[ACTIVE]" : "[]"} Shaft Friction Anomaly (+35% Load)
                    </button>
                    <button
                      className={`tech-btn ${activeFaults.includes("thermal_runaway") ? "status-critical" : ""}`}
                      onClick={() => handleInjectFault("thermal_runaway", !activeFaults.includes("thermal_runaway"))}
                      style={{ justifyContent: "left" }}
                    >
                      {activeFaults.includes("thermal_runaway") ? "[ACTIVE]" : "[]"} ESC Thermal Runaway
                    </button>
                    <button
                      className={`tech-btn ${activeFaults.includes("dropout") ? "status-critical" : ""}`}
                      onClick={() => handleInjectFault("dropout", !activeFaults.includes("dropout"))}
                      style={{ justifyContent: "left" }}
                    >
                      {activeFaults.includes("dropout") ? "[ACTIVE]" : "[]"} Telemetry Sensor Dropout (NaNs)
                    </button>
                    <button
                      className={`tech-btn ${activeFaults.includes("voltage_sag") ? "status-warning" : ""}`}
                      onClick={() => handleInjectFault("voltage_sag", !activeFaults.includes("voltage_sag"))}
                      style={{ justifyContent: "left" }}
                    >
                      {activeFaults.includes("voltage_sag") ? "[ACTIVE]" : "[]"} Power Voltage Sag (&lt;9.0 V)
                    </button>
                    <button
                      className="tech-btn"
                      onClick={handleClearFaults}
                      style={{ marginTop: "5px", color: "var(--color-healthy)", borderColor: "var(--color-healthy)" }}
                    >
                      Clear All Active Faults
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Replay controls */}
            {sourceType === "replay" && replayInfo && (
              <div style={{ borderTop: "1px solid var(--panel-border)", marginTop: "10px", paddingTop: "10px" }}>
                <div style={{ fontSize: "11px", fontWeight: "600", marginBottom: "8px", textTransform: "uppercase", color: "var(--text-secondary)" }}>
                  CSV Replay Engine
                </div>
                
                {/* File selector dropdown */}
                <div className="flex-col gap-10" style={{ marginBottom: "12px", borderBottom: "1px solid var(--panel-border)", paddingBottom: "10px" }}>
                  <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>SELECT LOG FILE:</span>
                  <select
                    value={selectedCsv}
                    onChange={(e) => {
                      setSelectedCsv(e.target.value);
                      handleSourceChange("replay", e.target.value);
                    }}
                    style={{
                      backgroundColor: "#16161a",
                      border: "1px solid var(--panel-border)",
                      color: "var(--text-primary)",
                      padding: "6px",
                      fontSize: "11px",
                      fontFamily: "monospace",
                      borderRadius: "2px",
                      width: "100%",
                      outline: "none"
                    }}
                  >
                    <option value="sample_telemetry.csv">sample_telemetry.csv (T200 Simulated)</option>
                    <option value="chinese_thruster_test.csv">chinese_thruster_test.csv (User Experimental Data)</option>
                  </select>
                </div>

                <div className="flex-col gap-10">
                  <div className="flex-row gap-10">
                    <button
                      className="tech-btn w-full"
                      onClick={() => handleReplayAction(replayInfo.is_playing ? "pause" : "play")}
                    >
                      {replayInfo.is_playing ? "PAUSE" : "RESUME"}
                    </button>
                    <button
                      className="tech-btn w-full"
                      onClick={() => handleReplayAction("seek", { seek_percent: 0.0 })}
                    >
                      RESET
                    </button>
                  </div>
                  
                  {/* Speed factors */}
                  <div className="flex-row align-center gap-10" style={{ fontSize: "11px" }}>
                    <span>Playback Speed:</span>
                    <button className={`tech-btn ${replayInfo.playback_speed === 1.0 ? "active" : ""}`} onClick={() => handleReplayAction("speed", { speed: 1.0 })}>1x</button>
                    <button className={`tech-btn ${replayInfo.playback_speed === 2.0 ? "active" : ""}`} onClick={() => handleReplayAction("speed", { speed: 2.0 })}>2x</button>
                    <button className={`tech-btn ${replayInfo.playback_speed === 5.0 ? "active" : ""}`} onClick={() => handleReplayAction("speed", { speed: 5.0 })}>5x</button>
                  </div>

                  {/* Scrub seek bar */}
                  <div className="flex-col gap-10" style={{ marginTop: "10px" }}>
                    <div className="flex-row space-between" style={{ fontSize: "10px", color: "var(--text-secondary)" }}>
                      <span>Progress:</span>
                      <span className="num-val">{replayInfo.current_index} / {replayInfo.total_samples} samples</span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="100"
                      step="1"
                      value={replayInfo.progress_pct}
                      onChange={(e) => handleReplayAction("seek", { seek_percent: Number(e.target.value) })}
                      style={{ width: "100%", accentColor: "var(--color-info)" }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Anomaly / Event log list */}
          <div className="panel-header" style={{ marginTop: "20px" }}>Anomaly & Diagnostic Events</div>
          <div className="event-log-container">
            {events.length > 0 ? (
              events.map((ev, idx) => (
                <div key={idx} className="event-item">
                  <div className="event-meta">
                    <span style={{ color: ev.severity === "CRITICAL" ? "var(--color-critical)" : "var(--color-warning)", fontWeight: "bold" }}>
                      {ev.severity} // {ev.source}
                    </span>
                    <span className="num-val">{ev.timestamp.split("T")[1]?.substring(0, 8) || ev.timestamp}</span>
                  </div>
                  <div className="event-msg">{ev.message}</div>
                  {ev.measured_value !== undefined && ev.expected_value !== undefined && (
                    <div className="event-detail">
                      Measured: {ev.measured_value} | Expected: {ev.expected_value} (Code: {ev.reason_code})
                    </div>
                  )}
                </div>
              ))
            ) : (
              <div style={{ color: "var(--text-muted)", fontSize: "11px", padding: "10px", textAlign: "center" }}>
                No events recorded. System nominal.
              </div>
            )}
          </div>
        </section>

        {/* Center Bottom: Time-Series Plots or Reference curves visualizer (Section 29) */}
        <section className="panel" style={{ gridColumn: "2 / 3" }}>
          <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Telemetry Plots & Reference Models</span>
            <div className="flex-row gap-5">
              <button 
                className={`tech-btn ${activeTab === "charts" ? "active" : ""}`}
                onClick={() => setActiveTab("charts")}
                style={{ padding: "3px 6px", fontSize: "10px" }}
              >
                Time-Series Trends
              </button>
              <button 
                className={`tech-btn ${activeTab === "reference" ? "active" : ""}`}
                onClick={() => setActiveTab("reference")}
                style={{ padding: "3px 6px", fontSize: "10px" }}
              >
                T200 Reference Curves
              </button>
            </div>
          </div>

          {activeTab === "charts" ? (
            <div className="charts-grid">
              {/* Chart 1: Current Draw Expected vs Measured */}
              <RealTimeChart
                data={history}
                title="Supply Current Draw: Measured vs Reference (A)"
                dataKeys={["current_filtered", "expected_current"]}
                labels={["Measured (Filt)", "Expected (Ref)"]}
                colors={["#2980b9", "#27ae60"]}
                unit="A"
                domain={[0, "auto"]}
              />

              {/* Chart 2: Current Residual Percentage */}
              <RealTimeChart
                data={history}
                title="Normalized Current Residual Percentage (%)"
                dataKeys={["current_residual_pct"]}
                labels={["Residual %"]}
                colors={["#e67e22"]}
                unit="%"
              />

              {/* Chart 3: Temperature */}
              <RealTimeChart
                data={history}
                title="ESC Core Temperature (°C)"
                dataKeys={["esc_temperature_filtered"]}
                labels={["ESC Temp"]}
                colors={["#c0392b"]}
                unit="°C"
                domain={[10, 80]}
              />

              {/* Chart 4: Health Index Trend */}
              <RealTimeChart
                data={history}
                title="Thruster Health Index Trend (0-100)"
                dataKeys={["health_score"]}
                labels={["Health Index"]}
                colors={["#27ae60"]}
                unit=""
                domain={[0, 100]}
              />
            </div>
          ) : (
            <div className="chart-wrapper" style={{ height: "350px", padding: "10px" }}>
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginBottom: "10px" }}>
                Plotting official T200 manufacturer current draw limits vs PWM control command at discrete voltages. Live operating state is overlaid dynamically.
              </div>
              <div style={{ width: "100%", height: "290px", fontSize: "10px" }}>
                <Recharts.ResponsiveContainer width="100%" height="100%">
                  <Recharts.ComposedChart
                    margin={{ top: 10, right: 10, left: -20, bottom: 20 }}
                  >
                    <Recharts.CartesianGrid strokeDasharray="3 3" stroke="#232328" />
                    <Recharts.XAxis
                      type="number"
                      dataKey="pwm"
                      domain={[1100, 1900]}
                      ticks={[1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900]}
                      stroke="#575765"
                    />
                    <Recharts.YAxis
                      type="number"
                      domain={[0, 26]}
                      stroke="#575765"
                    />
                    <Recharts.Tooltip
                      contentStyle={{ backgroundColor: "#16161a", borderColor: "#2a2a30", fontSize: "11px" }}
                    />
                    <Recharts.Legend verticalAlign="top" height={36} wrapperStyle={{ fontSize: "10px" }} />
                    
                    <Recharts.Line
                      data={referenceCurvesData}
                      type="monotone"
                      dataKey="T200 Ref @ 12V (A)"
                      stroke="#2980b9"
                      dot={false}
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                    />
                    <Recharts.Line
                      data={referenceCurvesData}
                      type="monotone"
                      dataKey="T200 Ref @ 16V (A)"
                      stroke="#27ae60"
                      dot={false}
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                    />
                    <Recharts.Line
                      data={referenceCurvesData}
                      type="monotone"
                      dataKey="T200 Ref @ 20V (A)"
                      stroke="#8e44ad"
                      dot={false}
                      strokeWidth={1.5}
                      strokeDasharray="4 4"
                    />
                    
                    {liveOperatingPoint.length > 0 && (
                      <Recharts.Scatter
                        data={liveOperatingPoint}
                        name="Live Measured Current"
                        dataKey="Live Operating Point (Measured)"
                        fill="#e74c3c"
                        line={false}
                        shape="circle"
                      />
                    )}
                    {liveOperatingPoint.length > 0 && (
                      <Recharts.Scatter
                        data={liveOperatingPoint}
                        name="Live Expected Current"
                        dataKey="Live Operating Point (Expected)"
                        fill="#f1c40f"
                        line={false}
                        shape="triangle"
                      />
                    )}
                  </Recharts.ComposedChart>
                </Recharts.ResponsiveContainer>
              </div>
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default App;
