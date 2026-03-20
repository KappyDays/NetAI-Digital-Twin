import React, { useRef, useEffect, useState, useCallback } from "react";

/**
 * CongestionHeatmap — Canvas-based 2D Top-View congestion heatmap
 * with zoom, pan, colormap selection, legend, and tooltip.
 *
 * Props:
 *   gridData: { config, grid, cells, max_value, total_objects, snapshot_time }
 *   colorScale: "thermal" | "viridis" | "plasma" | "grayscale"
 *   onCellClick: (row, col, cellData) => void
 */

// ─── Color Scales ────────────────────────────────────────────────────
const COLOR_SCALES = {
  thermal: [
    [13, 27, 42],
    [27, 73, 101],
    [98, 182, 203],
    [244, 211, 94],
    [238, 108, 77],
    [214, 40, 40],
  ],
  viridis: [
    [68, 1, 84],
    [59, 82, 139],
    [33, 145, 140],
    [94, 201, 98],
    [253, 231, 37],
    [253, 231, 37],
  ],
  plasma: [
    [13, 8, 135],
    [126, 3, 168],
    [204, 71, 120],
    [248, 149, 64],
    [240, 249, 33],
    [240, 249, 33],
  ],
  grayscale: [
    [20, 20, 30],
    [60, 60, 70],
    [100, 100, 110],
    [150, 150, 160],
    [200, 200, 210],
    [240, 240, 245],
  ],
};

function interpolateColor(t, scaleName) {
  const scale = COLOR_SCALES[scaleName] || COLOR_SCALES.thermal;
  t = Math.max(0, Math.min(1, t));
  const idx = t * (scale.length - 1);
  const lo = Math.floor(idx);
  const hi = Math.min(lo + 1, scale.length - 1);
  const frac = idx - lo;
  return [
    Math.round(scale[lo][0] + (scale[hi][0] - scale[lo][0]) * frac),
    Math.round(scale[lo][1] + (scale[hi][1] - scale[lo][1]) * frac),
    Math.round(scale[lo][2] + (scale[hi][2] - scale[lo][2]) * frac),
  ];
}

function colorToCSS([r, g, b], alpha = 1) {
  return alpha < 1
    ? `rgba(${r},${g},${b},${alpha})`
    : `rgb(${r},${g},${b})`;
}

// ─── Main Component ──────────────────────────────────────────────────
export default function CongestionHeatmap({
  gridData,
  colorScale = "thermal",
  onCellClick,
}) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const tooltipRef = useRef(null);

  // Zoom & Pan state
  const [viewState, setViewState] = useState({
    offsetX: 0,
    offsetY: 0,
    zoom: 1.0,
  });
  const dragRef = useRef({ dragging: false, startX: 0, startY: 0, startOX: 0, startOY: 0 });

  // Tooltip state
  const [tooltip, setTooltip] = useState({ visible: false, x: 0, y: 0, content: null });

  // ─── Render heatmap on canvas ────────────────────────────────────
  const renderHeatmap = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || !gridData) return;

    const dpr = window.devicePixelRatio || 1;
    const w = container.clientWidth;
    const h = container.clientHeight;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";

    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const { config, grid, max_value } = gridData;
    const { rows, cols } = config;
    const { offsetX, offsetY, zoom } = viewState;

    const PADDING = 44;
    const gridW = (w - 2 * PADDING) * zoom;
    const gridH = (h - 2 * PADDING) * zoom;
    const cellW = gridW / cols;
    const cellH = gridH / rows;

    // Origin with pan offset
    const ox = PADDING + offsetX;
    const oy = PADDING + offsetY;

    // Background
    ctx.fillStyle = "#0a0e14";
    ctx.fillRect(0, 0, w, h);

    // Clip region for grid cells
    ctx.save();
    ctx.beginPath();
    ctx.rect(PADDING - 1, PADDING - 1, w - 2 * PADDING + 2, h - 2 * PADDING + 2);
    ctx.clip();

    // Draw grid cells
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const val = grid[r] ? grid[r][c] || 0 : 0;
        const norm = max_value > 0 ? val / max_value : 0;
        const [cr, cg, cb] = interpolateColor(norm, colorScale);
        const alpha = val > 0 ? Math.max(0.3, norm) : 0.06;

        ctx.fillStyle = colorToCSS([cr, cg, cb], alpha);
        const drawR = rows - 1 - r; // Flip Y
        const x = ox + c * cellW;
        const y = oy + drawR * cellH;

        ctx.fillRect(x, y, cellW - 0.5, cellH - 0.5);

        // Cell count label (only when zoomed enough)
        if (val > 0 && cellW > 22 && cellH > 22) {
          ctx.fillStyle = norm > 0.5 ? "#fff" : "rgba(255,255,255,0.7)";
          ctx.font = `${Math.min(12, cellW * 0.32)}px -apple-system, sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText(String(Math.round(val)), x + cellW / 2, y + cellH / 2);
        }
      }
    }
    ctx.restore();

    // Grid border
    ctx.strokeStyle = "#30363d";
    ctx.lineWidth = 1;
    ctx.strokeRect(PADDING, PADDING, w - 2 * PADDING, h - 2 * PADDING);

    // ─── Axis labels ─────────────────────────────────────────────
    ctx.fillStyle = "#8b949e";
    ctx.font = "11px -apple-system, sans-serif";

    // X-axis (bottom)
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const xStep = Math.max(1, Math.floor(cols / 8));
    for (let c = 0; c <= cols; c += xStep) {
      const xVal = config.x_min + c * config.cell_width;
      const screenX = ox + c * cellW;
      if (screenX >= PADDING - 10 && screenX <= w - PADDING + 10) {
        ctx.fillText(xVal.toFixed(0), screenX, h - PADDING + 6);
      }
    }

    // Y-axis (left)
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    const yStep = Math.max(1, Math.floor(rows / 8));
    for (let r = 0; r <= rows; r += yStep) {
      const yVal = config.y_min + r * config.cell_height;
      const drawR = rows - r;
      const screenY = oy + drawR * cellH;
      if (screenY >= PADDING - 10 && screenY <= h - PADDING + 10) {
        ctx.fillText(yVal.toFixed(0), PADDING - 6, screenY);
      }
    }

    // Axis titles
    ctx.fillStyle = "#00d4aa";
    ctx.font = "12px -apple-system, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillText("X (World Coords)", w / 2, h - 2);

    ctx.save();
    ctx.translate(12, h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText("Y (World Coords)", 0, 0);
    ctx.restore();

    // Zoom indicator
    if (zoom !== 1.0) {
      ctx.fillStyle = "rgba(0,212,170,0.7)";
      ctx.font = "10px -apple-system, sans-serif";
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText(`${(zoom * 100).toFixed(0)}%`, w - 8, 4);
    }

    // Store render metadata for mouse interactions
    canvas._meta = { PADDING, cellW, cellH, rows, cols, ox, oy, gridW, gridH, w, h };
  }, [gridData, viewState, colorScale]);

  // Re-render on data/state changes
  useEffect(() => {
    renderHeatmap();
  }, [renderHeatmap]);

  // Resize observer
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const obs = new ResizeObserver(() => renderHeatmap());
    obs.observe(container);
    return () => obs.disconnect();
  }, [renderHeatmap]);

  // ─── Zoom (mouse wheel) ──────────────────────────────────────────
  const handleWheel = useCallback(
    (e) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setViewState((prev) => {
        const newZoom = Math.max(0.5, Math.min(5.0, prev.zoom * delta));
        // Zoom toward mouse position
        const canvas = canvasRef.current;
        if (!canvas || !canvas._meta) return { ...prev, zoom: newZoom };
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const { PADDING } = canvas._meta;
        const factor = newZoom / prev.zoom;
        return {
          zoom: newZoom,
          offsetX: mx - PADDING - (mx - PADDING - prev.offsetX) * factor,
          offsetY: my - PADDING - (my - PADDING - prev.offsetY) * factor,
        };
      });
    },
    []
  );

  // ─── Pan (mouse drag) ────────────────────────────────────────────
  const handleMouseDown = useCallback(
    (e) => {
      if (e.button !== 0) return; // Left button only
      dragRef.current = {
        dragging: true,
        startX: e.clientX,
        startY: e.clientY,
        startOX: viewState.offsetX,
        startOY: viewState.offsetY,
      };
      e.currentTarget.style.cursor = "grabbing";
    },
    [viewState.offsetX, viewState.offsetY]
  );

  const handleMouseMove = useCallback(
    (e) => {
      const canvas = canvasRef.current;
      const d = dragRef.current;

      if (d.dragging) {
        const dx = e.clientX - d.startX;
        const dy = e.clientY - d.startY;
        setViewState((prev) => ({
          ...prev,
          offsetX: d.startOX + dx,
          offsetY: d.startOY + dy,
        }));
        return;
      }

      // ─── Tooltip on hover ──────────────────────────────────────
      if (!gridData || !canvas || !canvas._meta) return;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { PADDING, cellW, cellH, rows, cols, ox, oy } = canvas._meta;

      const gc = Math.floor((mx - ox) / cellW);
      const drawR = Math.floor((my - oy) / cellH);
      const gr = rows - 1 - drawR;

      if (gc < 0 || gc >= cols || gr < 0 || gr >= rows || mx < PADDING || my < PADDING) {
        setTooltip((t) => (t.visible ? { ...t, visible: false } : t));
        return;
      }

      const val = gridData.grid[gr] ? gridData.grid[gr][gc] || 0 : 0;
      const cfg = gridData.config;
      const xMin = (cfg.x_min + gc * cfg.cell_width).toFixed(1);
      const xMax = (cfg.x_min + (gc + 1) * cfg.cell_width).toFixed(1);
      const yMin = (cfg.y_min + gr * cfg.cell_height).toFixed(1);
      const yMax = (cfg.y_min + (gr + 1) * cfg.cell_height).toFixed(1);

      const cellInfo = gridData.cells?.find((c) => c.row === gr && c.col === gc);
      const objIds = cellInfo?.object_ids || [];

      setTooltip({
        visible: true,
        x: Math.min(mx + 14, rect.width - 200),
        y: Math.min(my + 14, rect.height - 120),
        content: { row: gr, col: gc, val, xMin, xMax, yMin, yMax, objIds },
      });
    },
    [gridData, viewState]
  );

  const handleMouseUp = useCallback((e) => {
    dragRef.current.dragging = false;
    e.currentTarget.style.cursor = "crosshair";
  }, []);

  const handleMouseLeave = useCallback(() => {
    dragRef.current.dragging = false;
    setTooltip((t) => (t.visible ? { ...t, visible: false } : t));
  }, []);

  // ─── Click handler ───────────────────────────────────────────────
  const handleClick = useCallback(
    (e) => {
      if (!onCellClick || !gridData || !canvasRef.current?._meta) return;
      const canvas = canvasRef.current;
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      const { cellW, cellH, rows, cols, ox, oy } = canvas._meta;
      const gc = Math.floor((mx - ox) / cellW);
      const drawR = Math.floor((my - oy) / cellH);
      const gr = rows - 1 - drawR;
      if (gc >= 0 && gc < cols && gr >= 0 && gr < rows) {
        const cellInfo = gridData.cells?.find((c) => c.row === gr && c.col === gc);
        onCellClick(gr, gc, cellInfo || null);
      }
    },
    [gridData, onCellClick]
  );

  // ─── Reset view ──────────────────────────────────────────────────
  const resetView = useCallback(() => {
    setViewState({ offsetX: 0, offsetY: 0, zoom: 1.0 });
  }, []);

  // ─── Legend gradient ─────────────────────────────────────────────
  const legendGradient = (() => {
    const scale = COLOR_SCALES[colorScale] || COLOR_SCALES.thermal;
    const stops = scale
      .map((c, i) => `rgb(${c.join(",")}) ${(i / (scale.length - 1)) * 100}%`)
      .join(", ");
    return `linear-gradient(to right, ${stops})`;
  })();

  return (
    <div style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* Canvas container */}
      <div
        ref={containerRef}
        style={{
          width: "100%",
          height: "100%",
          minHeight: "400px",
          background: "#0a0e14",
          borderRadius: "6px",
          overflow: "hidden",
          position: "relative",
        }}
      >
        <canvas
          ref={canvasRef}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseLeave}
          onClick={handleClick}
          style={{
            display: "block",
            width: "100%",
            height: "100%",
            cursor: "crosshair",
          }}
        />

        {/* Tooltip overlay */}
        {tooltip.visible && tooltip.content && (
          <div
            ref={tooltipRef}
            style={{
              position: "absolute",
              left: tooltip.x,
              top: tooltip.y,
              background: "rgba(22,33,62,0.95)",
              border: "1px solid #30363d",
              borderRadius: "6px",
              padding: "8px 12px",
              fontSize: "12px",
              pointerEvents: "none",
              zIndex: 100,
              whiteSpace: "nowrap",
              boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
            }}
          >
            <div>
              <span style={{ color: "#8b949e" }}>Cell: </span>
              <span style={{ fontWeight: 600 }}>
                [{tooltip.content.row}, {tooltip.content.col}]
              </span>
            </div>
            <div>
              <span style={{ color: "#8b949e" }}>Objects: </span>
              <span style={{ fontWeight: 600, color: "#00d4aa" }}>
                {tooltip.content.val}
              </span>
            </div>
            <div>
              <span style={{ color: "#8b949e" }}>X: </span>
              <span style={{ fontWeight: 600 }}>
                {tooltip.content.xMin} ~ {tooltip.content.xMax}
              </span>
            </div>
            <div>
              <span style={{ color: "#8b949e" }}>Y: </span>
              <span style={{ fontWeight: 600 }}>
                {tooltip.content.yMin} ~ {tooltip.content.yMax}
              </span>
            </div>
            {tooltip.content.objIds.length > 0 && (
              <div
                style={{
                  marginTop: 4,
                  paddingTop: 4,
                  borderTop: "1px solid #30363d",
                }}
              >
                <span style={{ color: "#8b949e" }}>IDs: </span>
                <span style={{ fontWeight: 600, fontSize: "11px" }}>
                  {tooltip.content.objIds.slice(0, 5).join(", ")}
                  {tooltip.content.objIds.length > 5 ? "..." : ""}
                </span>
              </div>
            )}
          </div>
        )}

        {/* Reset zoom button */}
        {viewState.zoom !== 1.0 && (
          <button
            onClick={resetView}
            title="Reset zoom & pan"
            style={{
              position: "absolute",
              top: 8,
              left: 8,
              padding: "4px 10px",
              fontSize: "11px",
              background: "rgba(0,212,170,0.2)",
              border: "1px solid rgba(0,212,170,0.4)",
              borderRadius: "4px",
              color: "#00d4aa",
              cursor: "pointer",
              zIndex: 50,
            }}
          >
            Reset View
          </button>
        )}
      </div>

      {/* Legend bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginTop: "8px",
        }}
      >
        <span style={{ fontSize: "11px", color: "#8b949e" }}>Low</span>
        <div
          style={{
            flex: 1,
            height: "12px",
            borderRadius: "4px",
            background: legendGradient,
          }}
        />
        <span style={{ fontSize: "11px", color: "#8b949e" }}>High</span>
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: "10px",
          color: "#666",
          marginTop: "2px",
          padding: "0 24px",
        }}
      >
        <span>0</span>
        <span>{gridData ? Math.round(gridData.max_value) : "--"}</span>
      </div>

      {/* Interaction hint */}
      <div
        style={{
          fontSize: "10px",
          color: "#555",
          textAlign: "center",
          marginTop: "4px",
        }}
      >
        Scroll to zoom | Drag to pan | Hover for details
      </div>
    </div>
  );
}
