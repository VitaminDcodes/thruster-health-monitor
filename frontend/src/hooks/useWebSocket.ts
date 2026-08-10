import { useState, useEffect, useRef } from "react";

export interface TelemetryData {
  timestamp: string;
  thruster_id: string;
  pwm: number;
  voltage: number;
  current_raw: number;
  current_filtered: number;
  esc_temperature_raw: number;
  esc_temperature_filtered: number;
  expected_current: number;
  expected_power: number;
  current_residual: number;
  current_residual_pct: number;
  power_residual: number;
  power_residual_pct: number;
  ewma_value: number;
  cusum_pos: number;
  cusum_neg: number;
  health_score: number;
  health_state: "HEALTHY" | "MONITOR" | "WARNING" | "CRITICAL" | "UNKNOWN";
  confidence_score: number;
  operating_region: string;
  electrical_health: number;
  thermal_health: number;
  stability_health: number | string;
  anomaly_score: number;
  warnings: string;
  baseline_state?: string;
  coverage_status?: string;
  contributors?: string[];
  reason_codes?: string[];
  data_quality_metrics?: {
    sample_rate_hz: number;
    packet_loss_pct: number;
    sensor_dropouts: number;
    timestamp_discontinuities: number;
    stuck_sensor_count: number;
    total_received_samples: number;
  };
}

export interface HealthEvent {
  id?: number;
  timestamp: string;
  thruster_id: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  source: string;
  message: string;
  reason_code: string;
  associated_metric: string;
  measured_value: number;
  expected_value: number;
}

export interface ReplayInfo {
  current_index: number;
  total_samples: number;
  progress_pct: number;
  is_playing: boolean;
  playback_speed: number;
}

export const useWebSocket = (wsUrl: string, apiUrl: string, thrusterId: string = "T200-001") => {
  const [connected, setConnected] = useState(false);
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const [history, setHistory] = useState<TelemetryData[]>([]);
  const [events, setEvents] = useState<HealthEvent[]>([]);
  const [sourceType, setSourceType] = useState<string>("simulation");
  const [replayInfo, setReplayInfo] = useState<ReplayInfo | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);

  // Fetch initial history
  const fetchHistory = async () => {
    try {
      // 1. Fetch telemetry history
      const telRes = await fetch(`${apiUrl}/api/telemetry/history?thruster_id=${thrusterId}&limit=100`);
      if (telRes.ok) {
        const data = await telRes.json();
        setHistory(data);
        if (data.length > 0) {
          setTelemetry(data[data.length - 1]);
        }
      }
      
      // 2. Fetch logged events
      const evRes = await fetch(`${apiUrl}/api/events?thruster_id=${thrusterId}&limit=50`);
      if (evRes.ok) {
        const evData = await evRes.json();
        setEvents(evData);
      }
    } catch (e) {
      console.error("Error fetching telemetry history:", e);
    }
  };

  useEffect(() => {
    // Run initial fetch
    fetchHistory();

    const connectWS = () => {
      console.log(`Connecting to WebSocket at ${wsUrl}`);
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("WebSocket connection established");
        setConnected(true);
      };

      ws.onclose = () => {
        console.log("WebSocket connection closed. Reconnecting in 3s...");
        setConnected(false);
        setTimeout(connectWS, 3000);
      };

      ws.onerror = (error) => {
        console.error("WebSocket error:", error);
        ws.close();
      };

      ws.onmessage = (messageEvent) => {
        try {
          const payload = JSON.parse(messageEvent.data);
          
          if (payload.type === "telemetry") {
            const data: TelemetryData = payload.data;
            setTelemetry(data);
            setSourceType(payload.source_type);
            
            if (payload.replay_info) {
              setReplayInfo(payload.replay_info);
            } else {
              setReplayInfo(null);
            }
            
            // Append to history and shift if size > 100
            setHistory((prev) => {
              const updated = [...prev, data];
              if (updated.length > 100) {
                return updated.slice(updated.length - 100);
              }
              return updated;
            });
            
            // Append incoming events if present
            if (payload.events && payload.events.length > 0) {
              setEvents((prev) => {
                const updated = [...payload.events, ...prev]; // Show newest first in log
                if (updated.length > 100) {
                  return updated.slice(0, 100);
                }
                return updated;
              });
            }
          }
        } catch (e) {
          console.error("Error parsing WS message:", e);
        }
      };
    };

    connectWS();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [wsUrl, apiUrl, thrusterId]);

  return {
    connected,
    telemetry,
    history,
    events,
    sourceType,
    replayInfo,
    setEvents,
    refreshHistory: fetchHistory
  };
};
