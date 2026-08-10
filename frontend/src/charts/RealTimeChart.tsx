import React from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

interface RealTimeChartProps {
  data: any[];
  title: string;
  dataKeys: string[];
  labels?: string[];
  colors?: string[];
  unit?: string;
  domain?: [number | string, number | string];
}

const getShortTime = (isoString: string) => {
  if (!isoString) return "";
  try {
    // If it is simple number (from generated CSV timestamps e.g. "12.3")
    if (!isNaN(Number(isoString))) {
      return `${Number(isoString).toFixed(1)}s`;
    }
    
    // ISO format: 2026-08-10T15:20:00.123Z
    const tParts = isoString.split("T");
    if (tParts.length > 1) {
      return tParts[1].substring(0, 8); // Extracts "15:20:00"
    }
    return isoString;
  } catch (e) {
    return isoString;
  }
};

export const RealTimeChart: React.FC<RealTimeChartProps> = ({
  data,
  title,
  dataKeys,
  labels,
  colors = ["#2980b9", "#27ae60", "#e74c3c"],
  unit = "",
  domain,
}) => {
  return (
    <div className="chart-wrapper">
      <div className="chart-title">{title}</div>
      <div style={{ width: "100%", height: "100%", fontSize: "10px" }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 5, right: 10, left: -25, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#232328" />
            <XAxis
              dataKey="timestamp"
              tickFormatter={getShortTime}
              stroke="#575765"
              minTickGap={30}
            />
            <YAxis
              stroke="#575765"
              domain={domain || ["auto", "auto"]}
              tickFormatter={(val) => {
                const num = Number(val);
                return `${isNaN(num) ? "0.0" : num.toFixed(1)}${unit}`;
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "#16161a",
                borderColor: "#2a2a30",
                fontSize: "11px",
              }}
              labelFormatter={(label) => `Time: ${label}`}
              formatter={(value: any, name: any) => {
                const keyIdx = dataKeys.indexOf(name);
                const displayName = labels && labels[keyIdx] ? labels[keyIdx] : name;
                const num = Number(value);
                const formattedVal = isNaN(num) ? "0.00" : num.toFixed(2);
                return [`${formattedVal} ${unit}`, displayName];
              }}
            />
            {dataKeys.map((key, idx) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={colors[idx % colors.length]}
                dot={false}
                strokeWidth={1.5}
                isAnimationActive={false} // Disable animations for performance during real-time 10Hz updates
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};
export default RealTimeChart;
