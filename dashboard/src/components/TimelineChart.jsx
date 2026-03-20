import React, { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { getCongestionTimeseries } from "../api.js";

/**
 * TimelineChart — Time-axis scaling chart for spatio-temporal congestion visualization.
 *
 * Features:
 *   - Multi-series area/line chart (one line per space)
 *   - Time range slider for window selection (scaling)
 *   - Zoom in/out with mouse wheel and buttons
 *   - Hover crosshair with tooltip
 *   - Configurable bucket size (granularity)
 *   - Auto-refresh capability
 *   - Responsive canvas rendering
 */

const PALETTE = [
  "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
  "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#6366f1",
];

const BUCKET_OPTIONS = [
  { label: "10s", value: 10 },
  { label: "30s", value: 30 },
  { label: "1m", value: 60 },
  { label: "5m", value: 300 },
  { label: "15m", value: 900 },
  { label: "1h", value: 3600 },
];

const ZOOM_PRESETS = [
  { label: "5m", minutes: 5 },
  { label: "15m", minutes: 15 },
  { label: "1h", minutes: 60 },
  { label: "6h", minutes: 360 },
  { label: "24h", minutes: 1440 },
  { label: "All", minutes: 0 },
];

/** Format ISO string to HH:MM:SS */
function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return String(iso).slice(11, 19);
  }
}

/** Format ISO string to date + time */
function fmtDateTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString([], {
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  } catch {
    return String(iso).slice(0, 19);
  }
}

/** Nice Y-axis max */
function niceMax(val) {
  if (val <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(val)));
  const norm = val / mag;
  if (norm <= 1.5) return 1.5 * mag;
  if (norm <= 2) return 2 * mag;
  if (norm <= 3) return 3 * mag;
  if (norm <= 5) return 5 * mag;
  return 10 * mag;
}

/** Parse timeseries API response into chart-friendly structure */
function parseTimeseries(result) {
  const rows = result?.rows || [];
  if (!rows.length) return { labels: [], datasets: [], spaceIds: [] };

  // rows: [space_id, time_bucket, object_count]
  const bucketMap = new Map(); // time_bucket -> { space_id -> count }
  const spaceSet = new Set();

  for (const row of rows) {
    const spaceId = row[0] || "unknown";
    const timeBucket = row[1] || "";
    const count = parseInt(row[2]) || 0;
    spaceSet.add(spaceId);
    if (!bucketMap.has(timeBucket)) bucketMap.set(timeBucket, {});
    bucketMap.get(timeBucket)[spaceId] = count;
  }

  const sortedTimes = [...bucketMap.keys()].sort();
  const spaceIds = [...spaceSet].sort();

  const datasets = spaceIds.map((sid, i) => ({
    spaceId: sid,
    color: PALETTE[i % PALETTE.length],
    data: sortedTimes.map((t) => bucketMap.get(t)?.[sid] || 0),
  }));

  return { labels: sortedTimes, datasets, spaceIds };
}

export default function TimelineChart({
  spaceFilter = null,
  autoRefreshInterval = 15000,
  onTimeSelected = null,           // (timestamp, spaceValues) => void
  selectedTimestamp = null,         // Currently selected timestamp from parent
}) {
  const canvasRef = useRef(null);
  const tooltipRef = useRef(null);
  const containerRef = useRef(null);

  // Data state
  const [rawData, setRawData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Control state
  const [bucketSeconds, setBucketSeconds] = useState(60);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedZoom, setSelectedZoom] = useState("All");

  // Time range slider state (0..1 normalized)
  const [rangeStart, setRangeStart] = useState(0);
  const [rangeEnd, setRangeEnd] = useState(1);

  // Hover + selection state
  const [hoverIndex, setHoverIndex] = useState(-1);
  const [selectedIndex, setSelectedIndex] = useState(-1);

  // Sync selectedIndex from parent's selectedTimestamp
  useEffect(() => {
    if (!selectedTimestamp) {
      setSelectedIndex(-1);
      return;
    }
    const { labels } = chartData;
    const idx = labels.indexOf(selectedTimestamp);
    setSelectedIndex(idx);
  }, [selectedTimestamp, chartData]);

  // ── Fetch data ────────────────────────────────────────────────────
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const params = { bucket_seconds: bucketSeconds, limit: 5000 };
      if (spaceFilter) params.space_id = spaceFilter;

      // For zoom presets with specific time windows
      const preset = ZOOM_PRESETS.find((z) => z.label === selectedZoom);
      if (preset && preset.minutes > 0) {
        const end = new Date();
        const start = new Date(end.getTime() - preset.minutes * 60 * 1000);
        params.start_time = start.toISOString();
        params.end_time = end.toISOString();
      }

      const result = await getCongestionTimeseries(params);
      setRawData(result);
    } catch (err) {
      setError(err.message);
      // Provide demo data for visualization when API is unavailable
      setRawData(generateDemoData());
    } finally {
      setLoading(false);
    }
  }, [bucketSeconds, spaceFilter, selectedZoom]);

  useEffect(() => {
    fetchData();
    if (!autoRefresh) return;
    const iv = setInterval(fetchData, autoRefreshInterval);
    return () => clearInterval(iv);
  }, [fetchData, autoRefresh, autoRefreshInterval]);

  // ── Parse and slice data based on range ────────────────────────
  const fullParsed = useMemo(() => parseTimeseries(rawData), [rawData]);

  const chartData = useMemo(() => {
    const { labels, datasets } = fullParsed;
    if (!labels.length) return fullParsed;

    const n = labels.length;
    const i0 = Math.floor(rangeStart * n);
    const i1 = Math.max(i0 + 1, Math.ceil(rangeEnd * n));
    const slicedLabels = labels.slice(i0, i1);
    const slicedDatasets = datasets.map((ds) => ({
      ...ds,
      data: ds.data.slice(i0, i1),
    }));

    return { labels: slicedLabels, datasets: slicedDatasets, spaceIds: fullParsed.spaceIds };
  }, [fullParsed, rangeStart, rangeEnd]);

  // ── Zoom handlers ──────────────────────────────────────────────
  const handleZoomPreset = (presetLabel) => {
    setSelectedZoom(presetLabel);
    setRangeStart(0);
    setRangeEnd(1);
  };

  const handleZoomIn = () => {
    const center = (rangeStart + rangeEnd) / 2;
    const halfSpan = (rangeEnd - rangeStart) / 4; // zoom 2x
    setRangeStart(Math.max(0, center - halfSpan));
    setRangeEnd(Math.min(1, center + halfSpan));
  };

  const handleZoomOut = () => {
    const center = (rangeStart + rangeEnd) / 2;
    const halfSpan = (rangeEnd - rangeStart); // zoom 0.5x
    setRangeStart(Math.max(0, center - halfSpan));
    setRangeEnd(Math.min(1, center + halfSpan));
  };

  const handleResetZoom = () => {
    setRangeStart(0);
    setRangeEnd(1);
  };

  // ── Canvas wheel zoom ──────────────────────────────────────────
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    const zoomFactor = e.deltaY > 0 ? 1.2 : 0.8;
    const span = rangeEnd - rangeStart;
    const newSpan = Math.min(1, Math.max(0.02, span * zoomFactor));

    // Zoom towards mouse position
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const mouseRatio = (e.clientX - rect.left) / rect.width;
    const center = rangeStart + span * mouseRatio;

    let newStart = center - newSpan * mouseRatio;
    let newEnd = newStart + newSpan;

    if (newStart < 0) { newStart = 0; newEnd = newSpan; }
    if (newEnd > 1) { newEnd = 1; newStart = 1 - newSpan; }

    setRangeStart(Math.max(0, newStart));
    setRangeEnd(Math.min(1, newEnd));
  }, [rangeStart, rangeEnd]);

  // ── Canvas rendering ──────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const container = containerRef.current;
    if (!container) return;

    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    canvas.style.width = rect.width + "px";
    canvas.style.height = rect.height + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const w = rect.width;
    const h = rect.height;
    const pl = 55, pr = 20, pt = 30, pb = 45;
    const chartW = w - pl - pr;
    const chartH = h - pt - pb;

    ctx.clearRect(0, 0, w, h);

    const { labels, datasets } = chartData;

    if (!labels.length || !datasets.length) {
      // Empty state
      ctx.fillStyle = "#64748b";
      ctx.font = "400 14px 'Segoe UI', sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("No time-series data available", w / 2, h / 2 - 10);
      ctx.font = "400 12px 'Segoe UI', sans-serif";
      ctx.fillStyle = "#94a3b8";
      ctx.fillText("Ingest dynamic data or wait for auto-refresh", w / 2, h / 2 + 12);
      return;
    }

    // Y-axis range
    const allValues = datasets.flatMap((d) => d.data);
    const maxVal = Math.max(...allValues, 1);
    const yMax = niceMax(maxVal);

    // ── Grid & Axes ──────────────────────────────────────────
    const yTickCount = 6;
    const yStep = Math.max(1, Math.ceil(yMax / yTickCount));
    ctx.font = "11px 'Segoe UI', sans-serif";

    for (let v = 0; v <= yMax; v += yStep) {
      const y = pt + chartH - (v / yMax) * chartH;
      // Grid line
      ctx.strokeStyle = "rgba(148, 163, 184, 0.12)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pl, y);
      ctx.lineTo(pl + chartW, y);
      ctx.stroke();
      // Label
      ctx.fillStyle = "#64748b";
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(String(v), pl - 8, y);
    }

    // X-axis labels
    const maxXLabels = Math.floor(chartW / 90);
    const xStep = Math.max(1, Math.ceil(labels.length / maxXLabels));
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = "#64748b";

    for (let i = 0; i < labels.length; i += xStep) {
      const x = pl + (i / Math.max(labels.length - 1, 1)) * chartW;
      ctx.fillText(fmtTime(labels[i]), x, pt + chartH + 6);
    }

    // Axes lines
    ctx.strokeStyle = "#475569";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pl, pt);
    ctx.lineTo(pl, pt + chartH);
    ctx.lineTo(pl + chartW, pt + chartH);
    ctx.stroke();

    // Y-axis label
    ctx.save();
    ctx.translate(14, pt + chartH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = "#64748b";
    ctx.font = "500 11px 'Segoe UI', sans-serif";
    ctx.fillText("Object Count", 0, 0);
    ctx.restore();

    // ── Draw datasets ─────────────────────────────────────────
    for (const ds of datasets) {
      const points = ds.data.map((val, i) => ({
        x: pl + (i / Math.max(labels.length - 1, 1)) * chartW,
        y: pt + chartH - (val / yMax) * chartH,
      }));

      // Area fill
      ctx.beginPath();
      ctx.moveTo(points[0].x, pt + chartH);
      for (const p of points) ctx.lineTo(p.x, p.y);
      ctx.lineTo(points[points.length - 1].x, pt + chartH);
      ctx.closePath();
      ctx.fillStyle = ds.color + "26"; // ~15% opacity
      ctx.fill();

      // Line
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) ctx.lineTo(points[i].x, points[i].y);
      ctx.strokeStyle = ds.color;
      ctx.lineWidth = 2;
      ctx.lineJoin = "round";
      ctx.stroke();

      // Points
      for (const p of points) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = ds.color;
        ctx.fill();
      }
    }

    // ── Selected time marker (persistent click indicator) ────
    if (selectedIndex >= 0 && selectedIndex < labels.length) {
      const sx = pl + (selectedIndex / Math.max(labels.length - 1, 1)) * chartW;

      // Solid vertical line
      ctx.save();
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(sx, pt);
      ctx.lineTo(sx, pt + chartH);
      ctx.stroke();

      // Highlight data points
      for (const ds of datasets) {
        const val = ds.data[selectedIndex] ?? 0;
        const sy = pt + chartH - (val / yMax) * chartH;

        ctx.beginPath();
        ctx.arc(sx, sy, 7, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(59, 130, 246, 0.3)";
        ctx.fill();

        ctx.beginPath();
        ctx.arc(sx, sy, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = ds.color;
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Time badge at top
      const timeLabel = fmtTime(labels[selectedIndex]);
      ctx.font = "600 11px 'Segoe UI', sans-serif";
      const badgeW = ctx.measureText(timeLabel).width + 14;
      const badgeX = Math.min(Math.max(sx - badgeW / 2, pl), pl + chartW - badgeW);

      ctx.fillStyle = "#3b82f6";
      ctx.beginPath();
      ctx.roundRect(badgeX, pt - 18, badgeW, 18, 4);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(timeLabel, badgeX + badgeW / 2, pt - 9);

      ctx.restore();
    }

    // ── Hover crosshair ──────────────────────────────────────
    if (hoverIndex >= 0 && hoverIndex < labels.length) {
      const hx = pl + (hoverIndex / Math.max(labels.length - 1, 1)) * chartW;
      ctx.save();
      ctx.strokeStyle = "rgba(148, 163, 184, 0.5)";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(hx, pt);
      ctx.lineTo(hx, pt + chartH);
      ctx.stroke();
      ctx.restore();

      // Highlight points at hover
      for (const ds of datasets) {
        const val = ds.data[hoverIndex] ?? 0;
        const hy = pt + chartH - (val / yMax) * chartH;
        ctx.beginPath();
        ctx.arc(hx, hy, 5, 0, Math.PI * 2);
        ctx.fillStyle = ds.color;
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }

    // ── Legend ─────────────────────────────────────────────────
    if (datasets.length > 0) {
      let lx = pl;
      const ly = 12;
      ctx.font = "500 11px 'Segoe UI', sans-serif";
      for (const ds of datasets) {
        ctx.fillStyle = ds.color;
        ctx.fillRect(lx, ly - 4, 10, 10);
        lx += 14;
        ctx.fillStyle = "#94a3b8";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        const label = (ds.spaceId || "").replace("/World/", "");
        ctx.fillText(label, lx, ly + 1);
        lx += ctx.measureText(label).width + 16;
        if (lx > w - 50) break;
      }
    }
  }, [chartData, hoverIndex, selectedIndex]);

  // ── Canvas mouse events ────────────────────────────────────
  const handleMouseMove = useCallback((e) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const w = rect.width;
    const pl = 55, pr = 20;
    const chartW = w - pl - pr;
    const { labels, datasets } = chartData;

    if (!labels.length) return;

    const relX = mx - pl;
    const ratio = relX / chartW;
    const idx = Math.round(ratio * (labels.length - 1));
    const clamped = Math.max(0, Math.min(idx, labels.length - 1));
    setHoverIndex(clamped);

    // Update tooltip
    const tip = tooltipRef.current;
    if (tip) {
      const time = fmtDateTime(labels[clamped]);
      let html = `<strong>${time}</strong><br/>`;
      for (const ds of datasets) {
        const val = ds.data[clamped] ?? 0;
        const label = (ds.spaceId || "").replace("/World/", "");
        html += `<span style="color:${ds.color}">\u25CF</span> ${label}: <strong>${val}</strong><br/>`;
      }
      tip.innerHTML = html;
      tip.style.display = "block";
      tip.style.left = (e.clientX + 14) + "px";
      tip.style.top = (e.clientY - 10) + "px";
    }
  }, [chartData]);

  const handleMouseLeave = useCallback(() => {
    setHoverIndex(-1);
    if (tooltipRef.current) tooltipRef.current.style.display = "none";
  }, []);

  /** Click to select a time point — notify parent via onTimeSelected */
  const handleClick = useCallback((e) => {
    if (!onTimeSelected) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const w = rect.width;
    const pl = 55, pr = 20;
    const cw = w - pl - pr;
    const { labels, datasets } = chartData;
    if (!labels.length) return;

    const relX = mx - pl;
    const ratio = relX / cw;
    const idx = Math.round(ratio * (labels.length - 1));
    const clamped = Math.max(0, Math.min(idx, labels.length - 1));
    const timestamp = labels[clamped];

    // Toggle: click same point deselects
    if (selectedIndex === clamped) {
      setSelectedIndex(-1);
      onTimeSelected(null, null);
      return;
    }

    setSelectedIndex(clamped);

    // Build per-space values at this time index
    const spaceValues = {};
    for (const ds of datasets) {
      spaceValues[ds.spaceId] = ds.data[clamped] ?? 0;
    }
    onTimeSelected(timestamp, spaceValues);
  }, [chartData, selectedIndex, onTimeSelected]);

  // ── ResizeObserver ─────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      // Trigger re-render by toggling a micro-state (canvas redraws via the effect)
      setHoverIndex((prev) => prev); // no-op but triggers effect dependency change
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // ── Stats ──────────────────────────────────────────────────
  const stats = useMemo(() => {
    const { labels, datasets } = chartData;
    if (!labels.length) return null;
    const totalPoints = datasets.reduce((s, ds) => s + ds.data.length, 0);
    const maxVal = Math.max(...datasets.flatMap((ds) => ds.data), 0);
    const avgVal = totalPoints > 0
      ? (datasets.reduce((s, ds) => s + ds.data.reduce((a, b) => a + b, 0), 0) / totalPoints).toFixed(1)
      : 0;
    return {
      timeRange: `${fmtTime(labels[0])} — ${fmtTime(labels[labels.length - 1])}`,
      dataPoints: labels.length,
      maxCongestion: maxVal,
      avgCongestion: avgVal,
      spaces: datasets.length,
    };
  }, [chartData]);

  // Zoom percentage display
  const zoomPct = Math.round((rangeEnd - rangeStart) * 100);

  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <div className="card-title" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>Congestion Timeline</span>
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <label style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              style={{ marginRight: "0.25rem" }}
            />
            Auto
          </label>
          <button className="btn" onClick={fetchData} disabled={loading} style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem" }}>
            {loading ? "..." : "\u21BB"}
          </button>
        </div>
      </div>

      {error && <div className="error-msg" style={{ marginBottom: "0.5rem" }}>{error}</div>}

      {/* ── Controls Row ───────────────────────────────────── */}
      <div style={{
        display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center",
        marginBottom: "0.75rem", fontSize: "0.75rem",
      }}>
        {/* Bucket size selector */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ color: "var(--text-muted)" }}>Granularity:</span>
          {BUCKET_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              className="btn"
              style={{
                padding: "0.15rem 0.5rem",
                fontSize: "0.7rem",
                background: bucketSeconds === opt.value ? "var(--accent)" : undefined,
                color: bucketSeconds === opt.value ? "var(--bg-primary)" : undefined,
                borderColor: bucketSeconds === opt.value ? "var(--accent)" : undefined,
              }}
              onClick={() => setBucketSeconds(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Zoom presets */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <span style={{ color: "var(--text-muted)" }}>Window:</span>
          {ZOOM_PRESETS.map((z) => (
            <button
              key={z.label}
              className="btn"
              style={{
                padding: "0.15rem 0.5rem",
                fontSize: "0.7rem",
                background: selectedZoom === z.label ? "var(--accent)" : undefined,
                color: selectedZoom === z.label ? "var(--bg-primary)" : undefined,
                borderColor: selectedZoom === z.label ? "var(--accent)" : undefined,
              }}
              onClick={() => handleZoomPreset(z.label)}
            >
              {z.label}
            </button>
          ))}
        </div>

        {/* Zoom buttons */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.3rem" }}>
          <button className="btn" onClick={handleZoomIn} title="Zoom In" style={{ padding: "0.15rem 0.5rem", fontSize: "0.75rem" }}>+</button>
          <button className="btn" onClick={handleZoomOut} title="Zoom Out" style={{ padding: "0.15rem 0.5rem", fontSize: "0.75rem" }}>&minus;</button>
          <button className="btn" onClick={handleResetZoom} title="Reset Zoom" style={{ padding: "0.15rem 0.5rem", fontSize: "0.7rem" }}>Reset</button>
          <span style={{ color: "var(--text-muted)", minWidth: "3rem" }}>{zoomPct}%</span>
        </div>
      </div>

      {/* ── Canvas Chart ───────────────────────────────────── */}
      <div
        ref={containerRef}
        style={{ position: "relative", width: "100%", height: "280px", marginBottom: "0.5rem" }}
      >
        <canvas
          ref={canvasRef}
          style={{ width: "100%", height: "100%", cursor: "crosshair" }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
          onWheel={handleWheel}
        />
      </div>

      {/* ── Time Range Slider ──────────────────────────────── */}
      <TimeRangeSlider
        labels={fullParsed.labels}
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
        onRangeChange={(s, e) => { setRangeStart(s); setRangeEnd(e); }}
      />

      {/* ── Stats Strip ────────────────────────────────────── */}
      {stats && (
        <div style={{
          display: "flex", flexWrap: "wrap", gap: "1.2rem",
          marginTop: "0.75rem", fontSize: "0.75rem", color: "var(--text-secondary)",
        }}>
          <span>Time: <strong>{stats.timeRange}</strong></span>
          <span>Points: <strong>{stats.dataPoints}</strong></span>
          <span>Spaces: <strong>{stats.spaces}</strong></span>
          <span>Peak: <strong>{stats.maxCongestion}</strong></span>
          <span>Avg: <strong>{stats.avgCongestion}</strong></span>
        </div>
      )}

      {/* Interaction hint */}
      {onTimeSelected && (
        <div style={{ fontSize: "0.7rem", color: "var(--text-muted)", textAlign: "center", marginTop: "4px" }}>
          Click a point to sync space bars to that time{spaceFilter ? ` \u00B7 Filtered: ${spaceFilter.replace("/World/", "")}` : ""}
        </div>
      )}

      {/* Tooltip (portal-like, positioned fixed) */}
      <div
        ref={tooltipRef}
        style={{
          position: "fixed",
          display: "none",
          background: "#1e293b",
          color: "#f8fafc",
          padding: "8px 12px",
          borderRadius: "6px",
          fontSize: "12px",
          pointerEvents: "none",
          boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
          zIndex: 9999,
          maxWidth: "250px",
          lineHeight: 1.5,
        }}
      />
    </div>
  );
}

/**
 * TimeRangeSlider — Dual-handle slider for selecting a sub-range of the timeline.
 */
function TimeRangeSlider({ labels, rangeStart, rangeEnd, onRangeChange }) {
  const trackRef = useRef(null);
  const [dragging, setDragging] = useState(null); // "start" | "end" | "window" | null
  const dragStart = useRef({ x: 0, s: 0, e: 0 });

  const handlePointerDown = useCallback((e, handle) => {
    e.preventDefault();
    setDragging(handle);
    dragStart.current = {
      x: e.clientX,
      s: rangeStart,
      e: rangeEnd,
    };
  }, [rangeStart, rangeEnd]);

  useEffect(() => {
    if (!dragging) return;

    const handleMove = (e) => {
      const track = trackRef.current;
      if (!track) return;
      const rect = track.getBoundingClientRect();
      const dx = (e.clientX - dragStart.current.x) / rect.width;

      if (dragging === "start") {
        const newStart = Math.max(0, Math.min(dragStart.current.s + dx, rangeEnd - 0.02));
        onRangeChange(newStart, rangeEnd);
      } else if (dragging === "end") {
        const newEnd = Math.min(1, Math.max(dragStart.current.e + dx, rangeStart + 0.02));
        onRangeChange(rangeStart, newEnd);
      } else if (dragging === "window") {
        const span = dragStart.current.e - dragStart.current.s;
        let newStart = dragStart.current.s + dx;
        let newEnd = newStart + span;
        if (newStart < 0) { newStart = 0; newEnd = span; }
        if (newEnd > 1) { newEnd = 1; newStart = 1 - span; }
        onRangeChange(newStart, newEnd);
      }
    };

    const handleUp = () => setDragging(null);

    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleUp);
    return () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleUp);
    };
  }, [dragging, rangeStart, rangeEnd, onRangeChange]);

  const leftPct = (rangeStart * 100).toFixed(2) + "%";
  const widthPct = ((rangeEnd - rangeStart) * 100).toFixed(2) + "%";

  const startLabel = labels.length > 0 ? fmtTime(labels[Math.floor(rangeStart * (labels.length - 1))]) : "";
  const endLabel = labels.length > 0 ? fmtTime(labels[Math.min(Math.floor(rangeEnd * (labels.length - 1)), labels.length - 1)]) : "";

  return (
    <div style={{ padding: "0 0.5rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.65rem", color: "var(--text-muted)", marginBottom: "0.25rem" }}>
        <span>Timeline Range Selector</span>
        <span>{startLabel} — {endLabel}</span>
      </div>

      {/* Track */}
      <div
        ref={trackRef}
        style={{
          position: "relative",
          height: "32px",
          background: "var(--bg-secondary)",
          borderRadius: "4px",
          border: "1px solid var(--border)",
          cursor: "pointer",
          userSelect: "none",
          touchAction: "none",
        }}
      >
        {/* Mini chart preview (simplified bars) */}
        <MiniChartPreview labels={labels} />

        {/* Dimmed left region */}
        <div style={{
          position: "absolute", top: 0, left: 0,
          width: leftPct, height: "100%",
          background: "rgba(0,0,0,0.4)",
          borderRadius: "4px 0 0 4px",
          pointerEvents: "none",
        }} />

        {/* Dimmed right region */}
        <div style={{
          position: "absolute", top: 0,
          left: `calc(${leftPct} + ${widthPct})`,
          right: 0, height: "100%",
          background: "rgba(0,0,0,0.4)",
          borderRadius: "0 4px 4px 0",
          pointerEvents: "none",
        }} />

        {/* Selected window (draggable) */}
        <div
          style={{
            position: "absolute", top: 0,
            left: leftPct,
            width: widthPct,
            height: "100%",
            border: "2px solid var(--accent)",
            borderRadius: "3px",
            cursor: dragging === "window" ? "grabbing" : "grab",
            boxSizing: "border-box",
          }}
          onPointerDown={(e) => handlePointerDown(e, "window")}
        >
          {/* Left handle */}
          <div
            style={{
              position: "absolute", left: -6, top: "50%", transform: "translateY(-50%)",
              width: "10px", height: "20px",
              background: "var(--accent)", borderRadius: "3px",
              cursor: "ew-resize",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
            onPointerDown={(e) => { e.stopPropagation(); handlePointerDown(e, "start"); }}
          >
            <div style={{ width: "2px", height: "10px", background: "var(--bg-primary)", borderRadius: "1px" }} />
          </div>

          {/* Right handle */}
          <div
            style={{
              position: "absolute", right: -6, top: "50%", transform: "translateY(-50%)",
              width: "10px", height: "20px",
              background: "var(--accent)", borderRadius: "3px",
              cursor: "ew-resize",
              display: "flex", alignItems: "center", justifyContent: "center",
            }}
            onPointerDown={(e) => { e.stopPropagation(); handlePointerDown(e, "end"); }}
          >
            <div style={{ width: "2px", height: "10px", background: "var(--bg-primary)", borderRadius: "1px" }} />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * MiniChartPreview — Tiny bar chart inside the range slider for context.
 */
function MiniChartPreview({ labels }) {
  if (!labels || labels.length === 0) return null;

  // Just render evenly-spaced thin bars as a visual indicator
  const barCount = Math.min(labels.length, 80);
  const step = Math.max(1, Math.floor(labels.length / barCount));

  return (
    <div style={{
      position: "absolute", top: 2, left: 2, right: 2, bottom: 2,
      display: "flex", alignItems: "flex-end", gap: "1px",
      pointerEvents: "none", opacity: 0.3,
    }}>
      {Array.from({ length: barCount }, (_, i) => {
        const h = 20 + Math.random() * 60; // visual placeholder
        return (
          <div
            key={i}
            style={{
              flex: 1,
              height: `${h}%`,
              background: "var(--accent)",
              borderRadius: "1px 1px 0 0",
              minWidth: "1px",
            }}
          />
        );
      })}
    </div>
  );
}

/**
 * Generate demo timeseries data for when the API is unavailable.
 */
function generateDemoData() {
  const now = Date.now();
  const rows = [];
  const spaces = ["/World/Room_A", "/World/Room_B", "/World/Hallway"];

  for (let i = 0; i < 60; i++) {
    const ts = new Date(now - (60 - i) * 60 * 1000).toISOString();
    for (const space of spaces) {
      const base = space.includes("Room_A") ? 8 : space.includes("Room_B") ? 5 : 3;
      const count = Math.max(0, base + Math.floor(Math.sin(i * 0.2) * 3 + Math.random() * 2));
      rows.push([space, ts, count]);
    }
  }

  return {
    columns: ["space_id", "time_bucket", "object_count"],
    rows,
    row_count: rows.length,
  };
}
