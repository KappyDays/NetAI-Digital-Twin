import React, { useMemo, useState } from "react";

/**
 * TimeSeriesChart — SVG-based time-axis chart for congestion trends.
 *
 * Renders a line/area chart showing congestion levels over time.
 * Supports multiple series (one per space) with interactive hover tooltips.
 *
 * Props:
 *   data: Array<{ timestamp: string|number, space_id: string, value: number }>
 *     OR: Array<{ timestamp: string|number, [space_id]: number }> (pivoted format)
 *   spaces?: string[] — list of space_ids for series (auto-detected if omitted)
 *   width?: number  — SVG viewport width (default 700)
 *   height?: number — SVG viewport height (default 280)
 *   title?: string
 */

const SERIES_COLORS = [
  "#00d4aa",
  "#4dabf7",
  "#fc8d59",
  "#d73027",
  "#91cf60",
  "#fee08b",
  "#9b59b6",
  "#e74c3c",
  "#3498db",
  "#2ecc71",
];

function formatTimestamp(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return String(ts).slice(0, 16);
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function formatDateShort(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function TimeSeriesChart({
  data = [],
  spaces: spacesProp,
  width = 700,
  height = 280,
  title,
}) {
  const [hoveredPoint, setHoveredPoint] = useState(null);

  // Chart margins
  const margin = { top: 20, right: 120, bottom: 40, left: 50 };
  const chartW = width - margin.left - margin.right;
  const chartH = height - margin.top - margin.bottom;

  // Process data into normalized series format
  const { series, timestamps, maxValue, spaceList } = useMemo(() => {
    if (data.length === 0)
      return { series: {}, timestamps: [], maxValue: 0, spaceList: [] };

    // Detect data format: array of {timestamp, space_id, value} vs pivoted
    const isPivoted =
      data[0] && !("space_id" in data[0]) && !("value" in data[0]);

    let normalizedData;
    let detectedSpaces;

    if (isPivoted) {
      // Pivoted format: { timestamp, space1: val, space2: val, ... }
      detectedSpaces =
        spacesProp ||
        Object.keys(data[0]).filter((k) => k !== "timestamp" && k !== "time");
      normalizedData = [];
      for (const row of data) {
        const ts = row.timestamp || row.time;
        for (const sp of detectedSpaces) {
          if (row[sp] != null) {
            normalizedData.push({
              timestamp: ts,
              space_id: sp,
              value: Number(row[sp]),
            });
          }
        }
      }
    } else {
      normalizedData = data;
      detectedSpaces =
        spacesProp || [...new Set(data.map((d) => d.space_id))];
    }

    // Group by space_id
    const grouped = {};
    for (const d of normalizedData) {
      if (!grouped[d.space_id]) grouped[d.space_id] = [];
      grouped[d.space_id].push({
        timestamp: new Date(d.timestamp).getTime() || 0,
        value: d.value,
        rawTs: d.timestamp,
      });
    }

    // Sort each series by timestamp
    for (const key of Object.keys(grouped)) {
      grouped[key].sort((a, b) => a.timestamp - b.timestamp);
    }

    // Collect all unique timestamps
    const allTs = [
      ...new Set(
        normalizedData.map(
          (d) => new Date(d.timestamp).getTime() || 0
        )
      ),
    ].sort((a, b) => a - b);

    const mv = Math.max(1, ...normalizedData.map((d) => d.value || 0));

    return {
      series: grouped,
      timestamps: allTs,
      maxValue: mv,
      spaceList: detectedSpaces,
    };
  }, [data, spacesProp]);

  // Scale functions
  const xScale = (ts) => {
    if (timestamps.length <= 1) return chartW / 2;
    const minTs = timestamps[0];
    const maxTs = timestamps[timestamps.length - 1];
    if (maxTs === minTs) return chartW / 2;
    return ((ts - minTs) / (maxTs - minTs)) * chartW;
  };

  const yScale = (val) => {
    return chartH - (val / maxValue) * chartH;
  };

  // Generate Y-axis tick values
  const yTicks = useMemo(() => {
    const tickCount = 5;
    const step = maxValue / tickCount;
    return Array.from({ length: tickCount + 1 }, (_, i) =>
      Math.round(i * step)
    );
  }, [maxValue]);

  // Generate X-axis tick labels (show ~6 labels)
  const xTicks = useMemo(() => {
    if (timestamps.length <= 1) return timestamps;
    const step = Math.max(1, Math.floor(timestamps.length / 6));
    return timestamps.filter((_, i) => i % step === 0);
  }, [timestamps]);

  // Build SVG path for each series
  const paths = useMemo(() => {
    const result = {};
    for (const [spaceId, points] of Object.entries(series)) {
      if (points.length === 0) continue;

      // Line path
      const linePoints = points.map(
        (p) => `${xScale(p.timestamp)},${yScale(p.value)}`
      );
      result[spaceId] = {
        line: `M ${linePoints.join(" L ")}`,
        // Area path (fill under curve)
        area: `M ${xScale(points[0].timestamp)},${chartH} L ${linePoints.join(
          " L "
        )} L ${xScale(points[points.length - 1].timestamp)},${chartH} Z`,
        points,
      };
    }
    return result;
  }, [series, chartW, chartH, maxValue, timestamps]);

  // Empty state
  if (data.length === 0) {
    return (
      <div className="timeseries-chart">
        <svg width="100%" height={200} viewBox={`0 0 ${width} 200`}>
          <rect
            x="0"
            y="0"
            width={width}
            height="200"
            fill="var(--bg-secondary)"
            rx="8"
          />
          <text
            x={width / 2}
            y="85"
            textAnchor="middle"
            fill="#666"
            fontSize="14"
          >
            No time-series data available
          </text>
          <text
            x={width / 2}
            y="110"
            textAnchor="middle"
            fill="#555"
            fontSize="11"
          >
            Congestion history will appear as data is ingested
          </text>
        </svg>
      </div>
    );
  }

  return (
    <div className="timeseries-chart" style={{ position: "relative" }}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        style={{ maxWidth: "100%" }}
      >
        {/* Background */}
        <rect
          x="0"
          y="0"
          width={width}
          height={height}
          fill="var(--bg-secondary)"
          rx="8"
        />

        {/* Chart area */}
        <g transform={`translate(${margin.left}, ${margin.top})`}>
          {/* Grid lines (horizontal) */}
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={0}
                y1={yScale(tick)}
                x2={chartW}
                y2={yScale(tick)}
                stroke="rgba(255,255,255,0.06)"
                strokeDasharray="4 4"
              />
              <text
                x={-8}
                y={yScale(tick) + 4}
                textAnchor="end"
                fill="#666"
                fontSize="10"
              >
                {tick}
              </text>
            </g>
          ))}

          {/* X-axis labels */}
          {xTicks.map((ts) => (
            <g key={ts}>
              <line
                x1={xScale(ts)}
                y1={chartH}
                x2={xScale(ts)}
                y2={chartH + 6}
                stroke="#555"
              />
              <text
                x={xScale(ts)}
                y={chartH + 18}
                textAnchor="middle"
                fill="#666"
                fontSize="9"
              >
                {formatTimestamp(ts)}
              </text>
              <text
                x={xScale(ts)}
                y={chartH + 30}
                textAnchor="middle"
                fill="#555"
                fontSize="8"
              >
                {formatDateShort(ts)}
              </text>
            </g>
          ))}

          {/* Axes */}
          <line
            x1={0}
            y1={0}
            x2={0}
            y2={chartH}
            stroke="#555"
            strokeWidth="1"
          />
          <line
            x1={0}
            y1={chartH}
            x2={chartW}
            y2={chartH}
            stroke="#555"
            strokeWidth="1"
          />

          {/* Y-axis label */}
          <text
            x={-35}
            y={chartH / 2}
            textAnchor="middle"
            fill="#888"
            fontSize="10"
            transform={`rotate(-90, -35, ${chartH / 2})`}
          >
            Object Count
          </text>

          {/* Series - area fills (semi-transparent) */}
          {spaceList.map((spaceId, idx) => {
            const p = paths[spaceId];
            if (!p) return null;
            return (
              <path
                key={`area-${spaceId}`}
                d={p.area}
                fill={SERIES_COLORS[idx % SERIES_COLORS.length]}
                opacity={0.08}
              />
            );
          })}

          {/* Series - line strokes */}
          {spaceList.map((spaceId, idx) => {
            const p = paths[spaceId];
            if (!p) return null;
            return (
              <path
                key={`line-${spaceId}`}
                d={p.line}
                fill="none"
                stroke={SERIES_COLORS[idx % SERIES_COLORS.length]}
                strokeWidth="2"
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            );
          })}

          {/* Data points */}
          {spaceList.map((spaceId, idx) => {
            const p = paths[spaceId];
            if (!p) return null;
            return p.points.map((pt, pi) => (
              <circle
                key={`dot-${spaceId}-${pi}`}
                cx={xScale(pt.timestamp)}
                cy={yScale(pt.value)}
                r={
                  hoveredPoint?.space === spaceId && hoveredPoint?.idx === pi
                    ? 5
                    : 3
                }
                fill={SERIES_COLORS[idx % SERIES_COLORS.length]}
                stroke="var(--bg-secondary)"
                strokeWidth="1.5"
                onMouseEnter={() =>
                  setHoveredPoint({ space: spaceId, idx: pi, pt })
                }
                onMouseLeave={() => setHoveredPoint(null)}
                style={{ cursor: "crosshair", transition: "r 0.15s" }}
              />
            ));
          })}
        </g>

        {/* Legend */}
        <g transform={`translate(${width - margin.right + 10}, ${margin.top})`}>
          <text x="0" y="0" fill="#888" fontSize="10" fontWeight="600">
            Spaces
          </text>
          {spaceList.map((spaceId, idx) => {
            const shortName =
              spaceId.replace(/^\/World\//, "").slice(0, 12) || spaceId;
            return (
              <g key={spaceId} transform={`translate(0, ${16 + idx * 18})`}>
                <rect
                  x="0"
                  y="-6"
                  width="10"
                  height="10"
                  rx="2"
                  fill={SERIES_COLORS[idx % SERIES_COLORS.length]}
                />
                <text x="14" y="3" fill="#aaa" fontSize="9">
                  {shortName}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {/* Hover tooltip */}
      {hoveredPoint && (
        <div className="chart-tooltip">
          <strong>{hoveredPoint.space.replace(/^\/World\//, "")}</strong>
          <br />
          Value: {hoveredPoint.pt.value}
          <br />
          Time: {formatTimestamp(hoveredPoint.pt.timestamp)}
        </div>
      )}
    </div>
  );
}
