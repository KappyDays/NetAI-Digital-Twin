import React, { useMemo, useState } from "react";

/**
 * TopViewHeatmap — SVG-based top-down (plan view) spatial heatmap.
 *
 * Renders each space as a rectangular cell in a grid layout, color-coded
 * by congestion level. Designed to represent a bird's-eye view of the
 * /World hierarchy from OpenUSD scenes.
 *
 * Props:
 *   spaces: Array<{ space_id: string, object_count: number, ... }>
 *   maxCount: number — maximum object count for normalization
 *   onSpaceClick?: (space) => void — callback when a space cell is clicked
 *   width?: number  — SVG viewport width (default 600)
 *   height?: number — SVG viewport height (default 400)
 */

const HEATMAP_PALETTE = [
  { threshold: 0.0, color: "#1a9850", label: "Very Low" },
  { threshold: 0.2, color: "#91cf60", label: "Low" },
  { threshold: 0.4, color: "#fee08b", label: "Moderate" },
  { threshold: 0.6, color: "#fc8d59", label: "High" },
  { threshold: 0.8, color: "#d73027", label: "Critical" },
];

function getHeatColor(value, max) {
  if (max === 0) return HEATMAP_PALETTE[0].color;
  const ratio = Math.min(value / max, 1);
  for (let i = HEATMAP_PALETTE.length - 1; i >= 0; i--) {
    if (ratio >= HEATMAP_PALETTE[i].threshold) return HEATMAP_PALETTE[i].color;
  }
  return HEATMAP_PALETTE[0].color;
}

function shortenSpaceId(spaceId) {
  return (spaceId || "").replace(/^\/World\//, "").replace(/^\//, "");
}

export default function TopViewHeatmap({
  spaces = [],
  maxCount = 1,
  onSpaceClick,
  width = 600,
  height = 400,
}) {
  const [hoveredIdx, setHoveredIdx] = useState(null);

  // Compute grid layout: try to fill a roughly square grid
  const layout = useMemo(() => {
    const n = spaces.length;
    if (n === 0) return { cols: 0, rows: 0, cells: [] };

    const cols = Math.ceil(Math.sqrt(n * (width / height)));
    const rows = Math.ceil(n / cols);
    const cellW = (width - 20) / cols; // 10px margin each side
    const cellH = (height - 60) / rows; // room for legend at bottom
    const gap = 4;

    const cells = spaces.map((space, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      return {
        ...space,
        x: 10 + col * cellW + gap / 2,
        y: 10 + row * cellH + gap / 2,
        w: cellW - gap,
        h: cellH - gap,
        color: getHeatColor(space.object_count || 0, maxCount),
        shortName: shortenSpaceId(space.space_id),
        index: i,
      };
    });

    return { cols, rows, cells };
  }, [spaces, maxCount, width, height]);

  if (spaces.length === 0) {
    return (
      <div className="heatmap-empty">
        <svg width={width} height={200} viewBox={`0 0 ${width} 200`}>
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
            y="90"
            textAnchor="middle"
            fill="#666"
            fontSize="14"
          >
            No spatial data available
          </text>
          <text
            x={width / 2}
            y="115"
            textAnchor="middle"
            fill="#555"
            fontSize="11"
          >
            Ingest static prims via POST /api/v1/static/prims
          </text>
        </svg>
      </div>
    );
  }

  return (
    <div className="topview-heatmap">
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

        {/* Grid title */}
        <text x={width / 2} y="8" textAnchor="middle" fill="#888" fontSize="0">
          {/* Title rendered in card-title instead */}
        </text>

        {/* Space cells */}
        {layout.cells.map((cell) => {
          const isHovered = hoveredIdx === cell.index;
          return (
            <g
              key={cell.space_id}
              onMouseEnter={() => setHoveredIdx(cell.index)}
              onMouseLeave={() => setHoveredIdx(null)}
              onClick={() => onSpaceClick?.(cell)}
              style={{ cursor: onSpaceClick ? "pointer" : "default" }}
            >
              {/* Cell background */}
              <rect
                x={cell.x}
                y={cell.y}
                width={cell.w}
                height={cell.h}
                fill={cell.color}
                rx="6"
                opacity={isHovered ? 1 : 0.85}
                stroke={isHovered ? "#fff" : "rgba(0,0,0,0.2)"}
                strokeWidth={isHovered ? 2 : 1}
                style={{ transition: "opacity 0.2s, stroke 0.2s" }}
              />
              {/* Space name */}
              <text
                x={cell.x + cell.w / 2}
                y={cell.y + cell.h / 2 - 8}
                textAnchor="middle"
                fill="#fff"
                fontSize={Math.min(cell.w / 8, 11)}
                fontWeight="600"
                style={{ textShadow: "0 1px 3px rgba(0,0,0,0.6)" }}
              >
                {cell.shortName.length > 12
                  ? cell.shortName.slice(0, 11) + "\u2026"
                  : cell.shortName}
              </text>
              {/* Object count */}
              <text
                x={cell.x + cell.w / 2}
                y={cell.y + cell.h / 2 + 10}
                textAnchor="middle"
                fill="#fff"
                fontSize={Math.min(cell.w / 5, 18)}
                fontWeight="700"
                style={{ textShadow: "0 1px 3px rgba(0,0,0,0.6)" }}
              >
                {cell.object_count || 0}
              </text>
              {/* Hover tooltip overlay */}
              {isHovered && (
                <text
                  x={cell.x + cell.w / 2}
                  y={cell.y + cell.h / 2 + 26}
                  textAnchor="middle"
                  fill="rgba(255,255,255,0.8)"
                  fontSize="9"
                >
                  objects
                </text>
              )}
            </g>
          );
        })}

        {/* Legend bar at bottom */}
        <g transform={`translate(${width / 2 - 120}, ${height - 30})`}>
          <text x="-25" y="12" fill="#888" fontSize="10">
            Low
          </text>
          {HEATMAP_PALETTE.map((p, i) => (
            <rect
              key={i}
              x={i * 48}
              y="4"
              width="44"
              height="14"
              fill={p.color}
              rx="3"
            />
          ))}
          <text x={5 * 48 + 5} y="12" fill="#888" fontSize="10">
            High
          </text>
        </g>
      </svg>

      {/* Tooltip for hovered space */}
      {hoveredIdx !== null && layout.cells[hoveredIdx] && (
        <div className="heatmap-tooltip">
          <strong>{layout.cells[hoveredIdx].space_id}</strong>
          <br />
          Objects: {layout.cells[hoveredIdx].object_count || 0}
          <br />
          Density:{" "}
          {maxCount > 0
            ? Math.round(
                ((layout.cells[hoveredIdx].object_count || 0) / maxCount) * 100
              )
            : 0}
          %
        </div>
      )}
    </div>
  );
}
