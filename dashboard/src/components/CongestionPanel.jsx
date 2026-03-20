import React, { useState, useEffect, useCallback, useMemo } from "react";
import { getCongestion, getCongestionGrid, executeQuery } from "../api.js";
import CongestionHeatmap from "./CongestionHeatmap.jsx";
import TimelineChart from "./TimelineChart.jsx";

/**
 * CongestionPanel — Spatio-temporal congestion visualization dashboard.
 *
 * Two-section layout:
 *   1. Top-View 2D heatmap (Canvas-based, zoom/pan, colormap, legend)
 *   2. Per-space congestion bar chart + summary statistics
 *   3. Timeline chart with bidirectional interaction:
 *      - Click heatmap space → filter timeline to that space
 *      - Click timeline point → update space bars to show that time's snapshot
 *      - SyncBanner shows active selection with clear button
 *
 * Data sources:
 *   - /api/v1/congestion/grid  (2D grid data for heatmap)
 *   - /api/v1/congestion       (per-space congestion bars)
 *   - Fallback: Trino SQL aggregation or demo data
 */

const CONGESTION_COLORS = [
  "#1a9850", // 0-20%  green
  "#91cf60", // 20-40% light green
  "#fee08b", // 40-60% yellow
  "#fc8d59", // 60-80% orange
  "#d73027", // 80-100% red
];

function getCongestionColor(value, max) {
  if (max === 0) return CONGESTION_COLORS[0];
  const ratio = Math.min(value / max, 1);
  const idx = Math.min(Math.floor(ratio * 5), 4);
  return CONGESTION_COLORS[idx];
}

function CongestionBar({ label, value, max, isSelected, onClick }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const color = getCongestionColor(value, max);

  return (
    <div
      style={{
        marginBottom: "0.75rem",
        cursor: onClick ? "pointer" : "default",
        borderLeft: isSelected ? "3px solid #3b82f6" : "3px solid transparent",
        paddingLeft: "8px",
        transition: "all 0.2s ease",
        opacity: isSelected === false ? 0.45 : 1,
      }}
      onClick={onClick}
      title={onClick ? `Click to ${isSelected ? "deselect" : "filter chart by"} ${label}` : undefined}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.8rem",
          marginBottom: "0.25rem",
        }}
      >
        <span style={{ fontWeight: isSelected ? 600 : 400 }}>{label}</span>
        <span style={{ color: "var(--text-muted)" }}>
          {value} objects ({pct}%)
        </span>
      </div>
      <div
        style={{
          height: "20px",
          background: "var(--bg-secondary)",
          borderRadius: "4px",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: color,
            borderRadius: "4px",
            transition: "width 0.5s ease",
            minWidth: value > 0 ? "4px" : "0",
          }}
        />
      </div>
    </div>
  );
}

/**
 * SyncBanner — Shows the current bidirectional selection state.
 */
function SyncBanner({ type, label, onClear }) {
  const icon = type === "space" ? "\uD83D\uDDFA\uFE0F" : "\u23F1\uFE0F";
  const desc =
    type === "space"
      ? "Chart filtered to space: "
      : "Bars showing snapshot at: ";

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "8px 16px",
        marginBottom: "12px",
        background: "rgba(59, 130, 246, 0.1)",
        border: "1px solid rgba(59, 130, 246, 0.3)",
        borderRadius: "6px",
        fontSize: "0.82rem",
        color: "#6ea8fe",
      }}
    >
      <span style={{ fontSize: "1.1rem" }}>{icon}</span>
      <span style={{ flex: 1 }}>
        {desc}<strong style={{ color: "#e8eaed" }}>{label}</strong>
      </span>
      <button
        onClick={onClear}
        style={{
          background: "transparent",
          border: "1px solid rgba(148, 163, 184, 0.3)",
          color: "#9aa0b2",
          borderRadius: "4px",
          padding: "2px 10px",
          fontSize: "0.75rem",
          cursor: "pointer",
        }}
      >
        \u2715 Clear
      </button>
    </div>
  );
}

function formatTimeShort(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return String(iso).slice(11, 16);
  }
}

// ─── Demo Data Generator ───────────────────────────────────────────
function generateDemoGridData(rows = 20, cols = 20) {
  const xMin = -50, xMax = 50, yMin = -50, yMax = 50;
  const cellW = (xMax - xMin) / cols;
  const cellH = (yMax - yMin) / rows;

  const grid = Array.from({ length: rows }, () => Array(cols).fill(0));
  const cells = [];
  let maxVal = 0;
  let totalObjects = 0;

  const hotspots = [
    { cr: rows * 0.3, cc: cols * 0.3, radius: 3, intensity: 8 },
    { cr: rows * 0.7, cc: cols * 0.6, radius: 4, intensity: 12 },
    { cr: rows * 0.5, cc: cols * 0.8, radius: 2, intensity: 6 },
    { cr: rows * 0.2, cc: cols * 0.7, radius: 3, intensity: 5 },
  ];

  for (const hs of hotspots) {
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const dist = Math.sqrt((r - hs.cr) ** 2 + (c - hs.cc) ** 2);
        if (dist < hs.radius * 1.5) {
          const falloff = Math.max(0, 1 - dist / (hs.radius * 1.5));
          grid[r][c] += Math.round(hs.intensity * falloff * (0.7 + Math.random() * 0.3));
        }
      }
    }
  }

  for (let i = 0; i < rows * cols * 0.05; i++) {
    const r = Math.floor(Math.random() * rows);
    const c = Math.floor(Math.random() * cols);
    grid[r][c] += Math.floor(Math.random() * 3);
  }

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (grid[r][c] > 0) {
        maxVal = Math.max(maxVal, grid[r][c]);
        totalObjects += grid[r][c];
        cells.push({
          row: r, col: c, value: grid[r][c],
          x_min: xMin + c * cellW, x_max: xMin + (c + 1) * cellW,
          y_min: yMin + r * cellH, y_max: yMin + (r + 1) * cellH,
          object_ids: Array.from({ length: grid[r][c] }, (_, i) => `demo_${r}_${c}_${i}`),
        });
      }
    }
  }

  return {
    config: { x_min: xMin, x_max: xMax, y_min: yMin, y_max: yMax, rows, cols, cell_width: cellW, cell_height: cellH },
    cells, grid,
    max_value: maxVal,
    total_objects: totalObjects,
    snapshot_time: new Date().toISOString(),
  };
}

// ─── Grid Configuration ────────────────────────────────────────────
const GRID_RESOLUTIONS = [10, 20, 30, 40, 50];
const COLOR_SCALE_OPTIONS = [
  { value: "thermal", label: "Thermal (Blue-Red)" },
  { value: "viridis", label: "Viridis (Purple-Green-Yellow)" },
  { value: "plasma", label: "Plasma (Purple-Orange-Yellow)" },
  { value: "grayscale", label: "Grayscale" },
];

export default function CongestionPanel() {
  const [gridData, setGridData] = useState(null);
  const [spaceData, setSpaceData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [isDemo, setIsDemo] = useState(false);

  // Grid configuration
  const [gridRes, setGridRes] = useState(20);
  const [colorScale, setColorScale] = useState("thermal");
  const [bounds, setBounds] = useState({ x_min: -50, x_max: 50, y_min: -50, y_max: 50 });

  // ── Bidirectional Interaction State ──────────────────────────────
  const [selectedSpace, setSelectedSpace] = useState(null);     // Heatmap/bar → chart filter
  const [selectedTimestamp, setSelectedTimestamp] = useState(null);  // Chart → bars snapshot
  const [timeSnapshotData, setTimeSnapshotData] = useState(null); // { spaceId → count }
  const [syncType, setSyncType] = useState(null); // "space" | "time" | null

  // ─── Fetch data from API ─────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setIsDemo(false);

      // Fetch 2D grid data for heatmap
      let gridResult;
      try {
        gridResult = await getCongestionGrid({
          x_min: bounds.x_min, x_max: bounds.x_max,
          y_min: bounds.y_min, y_max: bounds.y_max,
          rows: gridRes, cols: gridRes,
        });
      } catch {
        gridResult = generateDemoGridData(gridRes, gridRes);
        setIsDemo(true);
      }
      setGridData(gridResult);

      // Fetch per-space congestion for bars
      let spaceResult;
      try {
        spaceResult = await getCongestion();
      } catch {
        try {
          const sqlResult = await executeQuery(
            "SELECT space_id, COUNT(*) as object_count FROM iceberg.static_db.static_prims GROUP BY space_id ORDER BY object_count DESC"
          );
          spaceResult = {
            spaces: (sqlResult.rows || sqlResult.data || []).map((r) => ({
              space_id: r[0] || r.space_id,
              object_count: parseInt(r[1] || r.object_count || 0),
              congestion_level: "computed",
            })),
          };
        } catch {
          spaceResult = { spaces: [] };
        }
      }
      setSpaceData(spaceResult);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [bounds, gridRes]);

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const iv = setInterval(fetchData, 15000);
    return () => clearInterval(iv);
  }, [fetchData, autoRefresh]);

  const loadDemo = useCallback(() => {
    setGridData(generateDemoGridData(gridRes, gridRes));
    setIsDemo(true);
    setError(null);
  }, [gridRes]);

  // ── Interaction handlers ─────────────────────────────────────────

  /** Click a space bar/label → filter the timeline chart */
  const handleSpaceClick = useCallback((spaceId) => {
    if (selectedSpace === spaceId) {
      setSelectedSpace(null);
      setSyncType(null);
    } else {
      setSelectedSpace(spaceId);
      setSyncType("space");
      // Clear time snapshot when selecting a space
      setSelectedTimestamp(null);
      setTimeSnapshotData(null);
    }
  }, [selectedSpace]);

  /** Timeline chart reports a time-point click → update bars to snapshot */
  const handleTimeSelected = useCallback((timestamp, spaceValues) => {
    if (selectedTimestamp === timestamp) {
      // Deselect
      setSelectedTimestamp(null);
      setTimeSnapshotData(null);
      setSyncType(selectedSpace ? "space" : null);
    } else {
      setSelectedTimestamp(timestamp);
      setTimeSnapshotData(spaceValues);
      setSyncType("time");
    }
  }, [selectedTimestamp, selectedSpace]);

  /** Clear all interaction state */
  const clearSync = useCallback(() => {
    setSelectedSpace(null);
    setSelectedTimestamp(null);
    setTimeSnapshotData(null);
    setSyncType(null);
  }, []);

  // ── Compute displayed space data (live or time-snapshot) ───────
  const spaces = spaceData?.spaces || [];
  const maxCount = Math.max(1, ...spaces.map((s) => s.object_count || 0));

  const displaySpaces = useMemo(() => {
    if (!timeSnapshotData) return spaces;
    // Override object_count from the time snapshot
    return spaces.map((s) => ({
      ...s,
      object_count: timeSnapshotData[s.space_id] ?? 0,
    }));
  }, [spaces, timeSnapshotData]);

  const displayMaxCount = Math.max(1, ...displaySpaces.map((s) => s.object_count || 0));

  return (
    <div>
      {/* ─── Title Row ──────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "1rem",
        }}
      >
        <h2 style={{ fontSize: "1.1rem" }}>
          Spatio-temporal Congestion Overview
          {isDemo && (
            <span
              style={{
                fontSize: "0.7rem",
                color: "var(--warning)",
                marginLeft: "0.5rem",
                fontWeight: 400,
              }}
            >
              (Demo Mode)
            </span>
          )}
        </h2>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <label style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ marginRight: "0.3rem" }}
            />
            Auto-refresh (15s)
          </label>
          <button className="btn" onClick={fetchData} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button className="btn" onClick={loadDemo}>Demo</button>
        </div>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {/* ─── Sync Status Banner ──────────────────────────────── */}
      {syncType && (
        <SyncBanner
          type={syncType}
          label={syncType === "space" ? selectedSpace : formatTimeShort(selectedTimestamp)}
          onClear={clearSync}
        />
      )}

      {/* ─── Main Layout: Heatmap (left) + Controls/Bars (right) ─ */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          gap: "1rem",
        }}
      >
        {/* LEFT: Top-View Heatmap */}
        <div className="card" style={{ minHeight: "520px" }}>
          <div className="card-title">Top-View Spatial Congestion Heatmap</div>
          {gridData ? (
            <CongestionHeatmap
              gridData={gridData}
              colorScale={colorScale}
            />
          ) : (
            <div className="loading">Loading heatmap data...</div>
          )}
        </div>

        {/* RIGHT: Controls + Stats + Bars */}
        <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
          {/* Statistics KPIs */}
          <div className="card">
            <div className="card-title">Statistics</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
              <StatKPI label="Total Objects" value={gridData?.total_objects ?? "--"} />
              <StatKPI label="Active Cells" value={gridData?.cells?.length ?? "--"} />
              <StatKPI label="Max Density" value={gridData?.max_value != null ? Math.round(gridData.max_value) : "--"} />
              <StatKPI label="Grid Size" value={gridData ? `${gridData.config.rows}x${gridData.config.cols}` : "--"} />
            </div>
          </div>

          {/* Grid Configuration */}
          <div className="card">
            <div className="card-title">Grid Configuration</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <ControlRow label="Resolution">
                <select value={gridRes} onChange={(e) => setGridRes(parseInt(e.target.value))} style={selectStyle}>
                  {GRID_RESOLUTIONS.map((r) => (
                    <option key={r} value={r}>{r} x {r}</option>
                  ))}
                </select>
              </ControlRow>
              <ControlRow label="Color Scale">
                <select value={colorScale} onChange={(e) => setColorScale(e.target.value)} style={selectStyle}>
                  {COLOR_SCALE_OPTIONS.map((cs) => (
                    <option key={cs.value} value={cs.value}>{cs.label}</option>
                  ))}
                </select>
              </ControlRow>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
                <BoundsInput label="X Min" value={bounds.x_min} onChange={(v) => setBounds((b) => ({ ...b, x_min: v }))} />
                <BoundsInput label="X Max" value={bounds.x_max} onChange={(v) => setBounds((b) => ({ ...b, x_max: v }))} />
                <BoundsInput label="Y Min" value={bounds.y_min} onChange={(v) => setBounds((b) => ({ ...b, y_min: v }))} />
                <BoundsInput label="Y Max" value={bounds.y_max} onChange={(v) => setBounds((b) => ({ ...b, y_max: v }))} />
              </div>
            </div>
          </div>

          {/* Space Congestion Bars */}
          <div className="card" style={{ flex: 1, overflow: "auto" }}>
            <div className="card-title">
              Space Congestion Levels
              {selectedTimestamp && (
                <span style={{ fontSize: "0.7rem", color: "#6ea8fe", marginLeft: "8px",
                  background: "rgba(59, 130, 246, 0.15)", padding: "2px 8px", borderRadius: "4px" }}>
                  {"\u23F1"} {formatTimeShort(selectedTimestamp)}
                </span>
              )}
            </div>
            {displaySpaces.length === 0 && !loading ? (
              <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                No space data available. Ingest static prims via{" "}
                <code>POST /api/v1/static/prims</code> or load demo.
              </div>
            ) : (
              displaySpaces.map((s) => (
                <CongestionBar
                  key={s.space_id}
                  label={s.space_id}
                  value={s.object_count || 0}
                  max={displayMaxCount}
                  isSelected={selectedSpace === null ? undefined : selectedSpace === s.space_id}
                  onClick={() => handleSpaceClick(s.space_id)}
                />
              ))
            )}
            {displaySpaces.length > 0 && (
              <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", marginTop: "6px", textAlign: "center" }}>
                Click a space to filter the timeline chart
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ─── Summary Stats Footer ───────────────────────────────── */}
      <div
        style={{
          display: "flex",
          gap: "1.5rem",
          marginTop: "1rem",
          fontSize: "0.8rem",
          color: "var(--text-secondary)",
        }}
      >
        <span>Grid: <strong>{gridData ? `${gridData.config.rows}x${gridData.config.cols}` : "--"}</strong></span>
        <span>Total objects: <strong>{gridData?.total_objects ?? "--"}</strong></span>
        <span>Active cells: <strong>{gridData?.cells?.length ?? "--"}</strong></span>
        {spaces.length > 0 && <span>Spaces: <strong>{spaces.length}</strong></span>}
        {gridData?.snapshot_time && (
          <span>Snapshot: <strong>{new Date(gridData.snapshot_time).toLocaleTimeString()}</strong></span>
        )}
      </div>

      {/* ─── Timeline Chart with bidirectional interaction ──────── */}
      <TimelineChart
        spaceFilter={selectedSpace}
        autoRefreshInterval={15000}
        onTimeSelected={handleTimeSelected}
        selectedTimestamp={selectedTimestamp}
      />
    </div>
  );
}

// ─── Helper Sub-Components ─────────────────────────────────────────

function StatKPI({ label, value }) {
  return (
    <div
      style={{
        background: "var(--bg-secondary)",
        borderRadius: "6px",
        padding: "10px",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: "20px", fontWeight: 700, color: "var(--accent)" }}>{value}</div>
      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>{label}</div>
    </div>
  );
}

function ControlRow({ label, children }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
      <label style={{ fontSize: "12px", color: "var(--text-muted)", fontWeight: 500 }}>{label}</label>
      {children}
    </div>
  );
}

function BoundsInput({ label, value, onChange }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
      <label style={{ fontSize: "11px", color: "var(--text-muted)" }}>{label}</label>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
        step="10"
        style={inputStyle}
      />
    </div>
  );
}

const selectStyle = {
  background: "var(--bg-secondary)",
  border: "1px solid var(--border)",
  color: "var(--text-primary)",
  borderRadius: "4px",
  padding: "6px 8px",
  fontSize: "13px",
  outline: "none",
  width: "100%",
};

const inputStyle = {
  background: "var(--bg-secondary)",
  border: "1px solid var(--border)",
  color: "var(--text-primary)",
  borderRadius: "4px",
  padding: "6px 8px",
  fontSize: "13px",
  outline: "none",
  width: "100%",
};
