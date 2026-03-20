import React, { useState, useEffect, useCallback, useMemo } from "react";
import TopViewHeatmap from "../components/TopViewHeatmap.jsx";
import TimeSeriesChart from "../components/TimeSeriesChart.jsx";
import CongestionHeatmap from "../components/CongestionHeatmap.jsx";
import TimelineChart from "../components/TimelineChart.jsx";
import { getCongestion, getCongestionGrid, getCongestionTimeseries, executeQuery } from "../api.js";

/**
 * CongestionPage — Full-page spatio-temporal congestion visualization.
 *
 * Layout:
 *   +-------------------------------------------------+
 *   | Title + Controls                                 |
 *   +-------------------------------------------------+
 *   | Summary Statistics (KPI cards)                   |
 *   +------------------------+------------------------+
 *   | Top-View 2D Grid       | Grid Config + Space     |
 *   | Heatmap (Canvas)       | Congestion Bars          |
 *   +------------------------+------------------------+
 *   | Time-Series Chart (full-width)                   |
 *   +-------------------------------------------------+
 *
 * Data sources:
 *   - GET /api/v1/congestion/grid  (2D grid for heatmap)
 *   - GET /api/v1/congestion       (per-space bars)
 *   - GET /api/v1/congestion/timeseries (time-series)
 */

const CONGESTION_COLORS = [
  "#1a9850",
  "#91cf60",
  "#fee08b",
  "#fc8d59",
  "#d73027",
];

function getCongestionColor(value, max) {
  if (max === 0) return CONGESTION_COLORS[0];
  const ratio = Math.min(value / max, 1);
  const idx = Math.min(Math.floor(ratio * 5), 4);
  return CONGESTION_COLORS[idx];
}

function CongestionBar({ label, value, max, rank }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  const color = getCongestionColor(value, max);

  return (
    <div style={{ marginBottom: "0.6rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "0.78rem",
          marginBottom: "0.2rem",
        }}
      >
        <span>
          <span style={{ color: "var(--text-muted)", fontSize: "0.7rem", marginRight: "0.3rem" }}>
            #{rank}
          </span>
          {label.replace(/^\/World\//, "")}
        </span>
        <span style={{ color: "var(--text-muted)" }}>
          {value} obj ({pct}%)
        </span>
      </div>
      <div
        style={{
          height: "18px",
          background: "var(--bg-primary)",
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

function KPICard({ label, value, unit, icon, color }) {
  return (
    <div className="kpi-card">
      <div className="kpi-icon" style={{ color: color || "var(--accent)" }}>
        {icon}
      </div>
      <div className="kpi-body">
        <div className="kpi-value">
          {value}
          {unit && <span className="kpi-unit">{unit}</span>}
        </div>
        <div className="kpi-label">{label}</div>
      </div>
    </div>
  );
}

// ─── Demo Data Generator ───────────────────────────────────────────
function generateDemoGridData(rows = 20, cols = 20) {
  const xMin = -50, xMax = 50, yMin = -50, yMax = 50;
  const cellW = (xMax - xMin) / cols;
  const cellH = (yMax - yMin) / rows;
  const grid = Array.from({ length: rows }, () => Array(cols).fill(0));
  const cells = [];
  let maxVal = 0, totalObjects = 0;
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
    cells, grid, max_value: maxVal, total_objects: totalObjects, snapshot_time: new Date().toISOString(),
  };
}

const GRID_RESOLUTIONS = [10, 20, 30, 40, 50];
const COLOR_SCALE_OPTIONS = [
  { value: "thermal", label: "Thermal (Blue-Red)" },
  { value: "viridis", label: "Viridis (Purple-Yellow)" },
  { value: "plasma", label: "Plasma (Purple-Orange)" },
  { value: "grayscale", label: "Grayscale" },
];

export default function CongestionPage() {
  const [viewMode, setViewMode] = useState("overview"); // "overview" | "advanced"
  const [gridData, setGridData] = useState(null);
  const [data, setData] = useState(null);
  const [timeSeriesData, setTimeSeriesData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedSpace, setSelectedSpace] = useState(null);
  const [isDemo, setIsDemo] = useState(false);

  // Grid configuration
  const [gridRes, setGridRes] = useState(20);
  const [colorScale, setColorScale] = useState("thermal");
  const [bounds, setBounds] = useState({ x_min: -50, x_max: 50, y_min: -50, y_max: 50 });

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setIsDemo(false);

      // 1) Fetch 2D grid data for heatmap
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

      // 2) Fetch per-space congestion for bars
      let result;
      try {
        result = await getCongestion();
      } catch {
        try {
          const sqlResult = await executeQuery(
            "SELECT space_id, COUNT(*) as object_count FROM iceberg.static_db.static_prims GROUP BY space_id ORDER BY object_count DESC"
          );
          result = {
            spaces: (sqlResult.rows || sqlResult.data || []).map((r) => ({
              space_id: r[0] || r.space_id,
              object_count: parseInt(r[1] || r.object_count || 0),
              congestion_level: "computed",
            })),
          };
        } catch {
          result = { spaces: [] };
        }
      }
      setData(result);

      // 3) Fetch time-series data
      try {
        const tsResult = await getCongestionTimeseries({ limit: 100 });
        if (tsResult.data && tsResult.data.length > 0) {
          setTimeSeriesData(tsResult.data);
        } else if (tsResult.history && tsResult.history.length > 0) {
          setTimeSeriesData(tsResult.history);
        } else {
          generateSyntheticTimeSeries(result.spaces || []);
        }
      } catch {
        generateSyntheticTimeSeries(result?.spaces || []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [bounds, gridRes]);

  const loadDemo = useCallback(() => {
    setGridData(generateDemoGridData(gridRes, gridRes));
    setIsDemo(true);
    setError(null);
  }, [gridRes]);

  // Generate synthetic time points from current snapshot (for visualization layout demo)
  const generateSyntheticTimeSeries = (spaces) => {
    if (spaces.length === 0) {
      setTimeSeriesData([]);
      return;
    }
    const now = Date.now();
    const points = [];
    const numPoints = 12;
    for (let i = numPoints; i >= 0; i--) {
      const ts = new Date(now - i * 5 * 60 * 1000).toISOString();
      for (const space of spaces) {
        const base = space.object_count || 0;
        // Add slight random variation to simulate changes over time
        const variation = Math.round(base * (0.85 + Math.random() * 0.3));
        points.push({
          timestamp: ts,
          space_id: space.space_id,
          value: Math.max(0, variation),
        });
      }
    }
    setTimeSeriesData(points);
  };

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const iv = setInterval(fetchData, 15000);
    return () => clearInterval(iv);
  }, [fetchData, autoRefresh]);

  const spaces = useMemo(() => {
    const s = data?.spaces || [];
    // Sort by object_count descending
    return [...s].sort(
      (a, b) => (b.object_count || 0) - (a.object_count || 0)
    );
  }, [data]);

  const maxCount = Math.max(1, ...spaces.map((s) => s.object_count || 0));
  const totalObjects = spaces.reduce((s, x) => s + (x.object_count || 0), 0);
  const avgDensity =
    spaces.length > 0 ? Math.round(totalObjects / spaces.length) : 0;
  const highCongestionCount = spaces.filter(
    (s) => (s.object_count || 0) / maxCount > 0.6
  ).length;

  return (
    <div className="congestion-page">
      {/* Page header with controls */}
      <div className="page-header">
        <div>
          <h2 className="page-title">Spatio-temporal Congestion</h2>
          <p className="page-desc">
            Real-time congestion monitoring across all /World spaces
          </p>
        </div>
        <div className="page-controls">
          {/* View mode toggle */}
          <div className="view-toggle">
            <button
              className={`view-toggle-btn ${viewMode === "overview" ? "active" : ""}`}
              onClick={() => setViewMode("overview")}
            >
              Overview
            </button>
            <button
              className={`view-toggle-btn ${viewMode === "advanced" ? "active" : ""}`}
              onClick={() => setViewMode("advanced")}
            >
              Advanced
            </button>
          </div>
          <label className="auto-refresh-label">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            Auto (15s)
          </label>
          <button className="btn" onClick={fetchData} disabled={loading}>
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button className="btn" onClick={loadDemo}>Demo</button>
        </div>
      </div>

      {error && <div className="error-msg">{error}</div>}

      {/* KPI Summary Cards */}
      <div className="kpi-row">
        <KPICard
          label="Total Spaces"
          value={spaces.length}
          icon="&#9632;"
          color="var(--info)"
        />
        <KPICard
          label="Total Objects"
          value={totalObjects}
          icon="&#9679;"
          color="var(--accent)"
        />
        <KPICard
          label="Avg Density"
          value={avgDensity}
          unit="/space"
          icon="&#9776;"
          color="var(--warning)"
        />
        <KPICard
          label="High Congestion"
          value={highCongestionCount}
          unit=" spaces"
          icon="&#9888;"
          color={highCongestionCount > 0 ? "var(--danger)" : "var(--success)"}
        />
      </div>

      {/* ─── Overview Mode: SVG Heatmap + Bars + Simple Chart ─── */}
      {viewMode === "overview" && (
        <>
          <div className="viz-row">
            <div className="card viz-heatmap">
              <div className="card-title">Top-View Spatial Heatmap</div>
              <TopViewHeatmap
                spaces={spaces}
                maxCount={maxCount}
                onSpaceClick={(space) => setSelectedSpace(space.space_id)}
                width={600}
                height={380}
              />
            </div>

            <div className="card viz-bars">
              <div className="card-title">
                Space Congestion Ranking
                {selectedSpace && (
                  <span
                    style={{
                      fontWeight: 400,
                      fontSize: "0.8rem",
                      color: "var(--accent)",
                      marginLeft: "0.5rem",
                    }}
                  >
                    Selected: {selectedSpace.replace(/^\/World\//, "")}
                  </span>
                )}
              </div>
              <div className="congestion-bars-scroll">
                {spaces.length === 0 && !loading ? (
                  <div
                    style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}
                  >
                    No space data. Ingest prims via{" "}
                    <code>POST /api/v1/static/prims</code>
                  </div>
                ) : (
                  spaces.map((s, i) => (
                    <CongestionBar
                      key={s.space_id}
                      label={s.space_id}
                      value={s.object_count || 0}
                      max={maxCount}
                      rank={i + 1}
                    />
                  ))
                )}
              </div>
              <div className="congestion-legend">
                <span>Low</span>
                {CONGESTION_COLORS.map((c, i) => (
                  <div
                    key={i}
                    style={{
                      width: "24px",
                      height: "12px",
                      background: c,
                      borderRadius: "2px",
                    }}
                  />
                ))}
                <span>High</span>
              </div>
            </div>
          </div>

          <div className="card viz-timeseries">
            <div className="card-title">Congestion Trend Over Time</div>
            <TimeSeriesChart data={timeSeriesData} width={900} height={280} />
          </div>
        </>
      )}

      {/* ─── Advanced Mode: Canvas Grid Heatmap + Timeline Chart ─── */}
      {viewMode === "advanced" && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 320px",
              gap: "1rem",
            }}
          >
            {/* Canvas-based 2D Grid Heatmap */}
            <div className="card" style={{ minHeight: "520px" }}>
              <div className="card-title">
                Top-View 2D Grid Heatmap
                {isDemo && (
                  <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--warning)", marginLeft: "0.5rem" }}>
                    (Demo)
                  </span>
                )}
                <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--text-muted)", marginLeft: "0.5rem" }}>
                  Scroll zoom &middot; Drag pan
                </span>
              </div>
              {gridData ? (
                <CongestionHeatmap gridData={gridData} colorScale={colorScale} />
              ) : (
                <div className="loading">Loading heatmap data...</div>
              )}
            </div>

            {/* Grid Configuration + Stats */}
            <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
              <div className="card">
                <div className="card-title">Statistics</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                  <StatKPI label="Total Objects" value={gridData?.total_objects ?? "--"} />
                  <StatKPI label="Active Cells" value={gridData?.cells?.length ?? "--"} />
                  <StatKPI label="Max Density" value={gridData?.max_value != null ? Math.round(gridData.max_value) : "--"} />
                  <StatKPI label="Grid Size" value={gridData ? `${gridData.config.rows}x${gridData.config.cols}` : "--"} />
                </div>
              </div>

              <div className="card">
                <div className="card-title">Grid Configuration</div>
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "12px", color: "var(--text-muted)", fontWeight: 500 }}>Resolution</label>
                    <select value={gridRes} onChange={(e) => setGridRes(parseInt(e.target.value))} style={selectStyle}>
                      {GRID_RESOLUTIONS.map((r) => (<option key={r} value={r}>{r} x {r}</option>))}
                    </select>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                    <label style={{ fontSize: "12px", color: "var(--text-muted)", fontWeight: 500 }}>Color Scale</label>
                    <select value={colorScale} onChange={(e) => setColorScale(e.target.value)} style={selectStyle}>
                      {COLOR_SCALE_OPTIONS.map((cs) => (<option key={cs.value} value={cs.value}>{cs.label}</option>))}
                    </select>
                  </div>
                </div>
              </div>

              {/* Space Bars in compact form */}
              <div className="card" style={{ flex: 1, overflow: "auto" }}>
                <div className="card-title">Space Congestion</div>
                <div className="congestion-bars-scroll">
                  {spaces.length === 0 && !loading ? (
                    <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                      No space data. Load demo or ingest prims.
                    </div>
                  ) : (
                    spaces.map((s, i) => (
                      <CongestionBar key={s.space_id} label={s.space_id} value={s.object_count || 0} max={maxCount} rank={i + 1} />
                    ))
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Timeline Chart with interactive controls */}
          <TimelineChart spaceFilter={null} autoRefreshInterval={15000} />
        </>
      )}
    </div>
  );
}

// ─── Helper Components ──────────────────────────────────────────────

function StatKPI({ label, value }) {
  return (
    <div style={{ background: "var(--bg-secondary)", borderRadius: "6px", padding: "10px", textAlign: "center" }}>
      <div style={{ fontSize: "20px", fontWeight: 700, color: "var(--accent)" }}>{value}</div>
      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>{label}</div>
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
