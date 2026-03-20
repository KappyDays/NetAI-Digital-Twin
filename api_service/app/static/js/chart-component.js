/**
 * Chart Component
 *
 * Canvas-based time-series chart for congestion visualization.
 * Renders line/area charts showing object count per space over time.
 * Auto-updates from DashboardStore's congestionTimeseries data.
 *
 * Features:
 *   - Multi-series line chart (one line per space)
 *   - Filled area under each line (with transparency)
 *   - Auto-scaling Y-axis
 *   - Time-based X-axis with smart label formatting
 *   - Hover crosshair with data tooltip
 *   - Responsive canvas
 *   - Space filter (highlight selected space)
 *   - Animated data transitions
 */

class ChartComponent {
  /**
   * @param {HTMLCanvasElement} canvas - Target canvas element
   * @param {DashboardStore} store - Dashboard data store
   * @param {object} options - Chart options
   */
  constructor(canvas, store, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.store = store;

    this.options = {
      // Layout
      paddingTop: options.paddingTop || 20,
      paddingRight: options.paddingRight || 20,
      paddingBottom: options.paddingBottom || 40,
      paddingLeft: options.paddingLeft || 50,
      // Style
      lineWidth: options.lineWidth || 2,
      pointRadius: options.pointRadius || 3,
      areaOpacity: options.areaOpacity || 0.15,
      gridColor: options.gridColor || "rgba(148, 163, 184, 0.15)",
      axisColor: options.axisColor || "#64748b",
      fontSize: options.fontSize || 11,
      fontFamily: options.fontFamily || "'Inter', 'Segoe UI', sans-serif",
      // Behavior
      maxYTicks: options.maxYTicks || 6,
      animationDuration: options.animationDuration || 400,
      ...options,
    };

    // Color palette for space lines
    this._palette = [
      "#3b82f6", // blue
      "#ef4444", // red
      "#22c55e", // green
      "#f59e0b", // amber
      "#8b5cf6", // purple
      "#06b6d4", // cyan
      "#ec4899", // pink
      "#14b8a6", // teal
      "#f97316", // orange
      "#6366f1", // indigo
    ];

    // State
    this._chartData = { labels: [], datasets: [] };
    this._filterSpaceId = null;
    this._selectedIndex = -1;   // Clicked time-point index
    this._hoverIndex = -1;
    this._tooltipEl = null;
    this._unwatch = null;
    this._resizeObserver = null;

    this._init();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Init
  // ═══════════════════════════════════════════════════════════════════

  _init() {
    this._setupResize();
    this._setupEvents();
    this._createTooltip();

    // Watch both timeseries and space-selection
    this._unwatch = this.store.watch("congestionTimeseries", () => this._onDataUpdate());

    // Listen for heatmap space selection
    document.addEventListener("space-selected", (e) => {
      this._filterSpaceId = e.detail.spaceId;
      this._onDataUpdate();
    });

    this._onDataUpdate();
  }

  _setupResize() {
    const resize = () => {
      const rect = this.canvas.parentElement?.getBoundingClientRect();
      if (rect) {
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.canvas.style.width = rect.width + "px";
        this.canvas.style.height = rect.height + "px";
        this.ctx.scale(dpr, dpr);
      }
      this._render();
    };

    if (typeof ResizeObserver !== "undefined") {
      this._resizeObserver = new ResizeObserver(resize);
      this._resizeObserver.observe(this.canvas.parentElement || this.canvas);
    }
    window.addEventListener("resize", resize);
    resize();
  }

  _setupEvents() {
    this.canvas.addEventListener("mousemove", (e) => this._onMouseMove(e));
    this.canvas.addEventListener("mouseleave", () => this._onMouseLeave());
    this.canvas.addEventListener("click", (e) => this._onClick(e));
  }

  _createTooltip() {
    this._tooltipEl = document.createElement("div");
    this._tooltipEl.className = "chart-tooltip";
    this._tooltipEl.style.cssText =
      "position:fixed;display:none;background:#1e293b;color:#f8fafc;" +
      "padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;" +
      "box-shadow:0 4px 12px rgba(0,0,0,0.3);z-index:9999;max-width:250px;";
    document.body.appendChild(this._tooltipEl);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Data
  // ═══════════════════════════════════════════════════════════════════

  _onDataUpdate() {
    this._chartData = this.store.getChartData(this._filterSpaceId);
    this._render();
  }

  /** External: set space filter */
  filterBySpace(spaceId) {
    this._filterSpaceId = spaceId;
    this._onDataUpdate();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Rendering
  // ═══════════════════════════════════════════════════════════════════

  _render() {
    const ctx = this.ctx;
    const w = parseFloat(this.canvas.style.width) || this.canvas.width;
    const h = parseFloat(this.canvas.style.height) || this.canvas.height;
    const { paddingTop: pt, paddingRight: pr, paddingBottom: pb, paddingLeft: pl } = this.options;

    ctx.clearRect(0, 0, w, h);

    const { labels, datasets } = this._chartData;

    if (!labels.length || !datasets.length) {
      this._renderEmptyState(ctx, w, h);
      return;
    }

    // Chart area
    const chartW = w - pl - pr;
    const chartH = h - pt - pb;

    // Y-axis range
    const allValues = datasets.flatMap((d) => d.data);
    const maxVal = Math.max(...allValues, 1);
    const yMax = this._niceMax(maxVal);

    // Draw grid and axes
    this._drawGrid(ctx, pl, pt, chartW, chartH, yMax, labels);

    // Draw each dataset
    datasets.forEach((ds, dsIdx) => {
      const color = this._palette[dsIdx % this._palette.length];
      this._drawSeries(ctx, ds, pl, pt, chartW, chartH, yMax, labels.length, color);
    });

    // Draw selected time-point marker (persistent)
    if (this._selectedIndex >= 0 && this._selectedIndex < labels.length) {
      this._drawSelectedMarker(ctx, pl, pt, chartW, chartH, labels.length, datasets);
    }

    // Draw hover crosshair
    if (this._hoverIndex >= 0 && this._hoverIndex < labels.length) {
      this._drawCrosshair(ctx, pl, pt, chartW, chartH, labels.length);
    }

    // Legend
    this._drawLegend(ctx, w, datasets);
  }

  _drawGrid(ctx, x0, y0, w, h, yMax, labels) {
    ctx.save();

    // Y-axis grid lines and labels
    const ticks = this._getYTicks(yMax);
    ctx.strokeStyle = this.options.gridColor;
    ctx.lineWidth = 1;
    ctx.font = `${this.options.fontSize}px ${this.options.fontFamily}`;
    ctx.fillStyle = this.options.axisColor;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";

    for (const tick of ticks) {
      const y = y0 + h - (tick / yMax) * h;
      // Grid line
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(x0 + w, y);
      ctx.stroke();
      // Label
      ctx.fillText(String(tick), x0 - 8, y);
    }

    // X-axis labels (smart sampling)
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const maxLabels = Math.floor(w / 80);
    const step = Math.max(1, Math.ceil(labels.length / maxLabels));

    for (let i = 0; i < labels.length; i += step) {
      const xPos = x0 + (i / Math.max(labels.length - 1, 1)) * w;
      const label = this._formatTimeLabel(labels[i]);
      ctx.fillText(label, xPos, y0 + h + 6);
    }

    // Axes
    ctx.strokeStyle = this.options.axisColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x0, y0);
    ctx.lineTo(x0, y0 + h);
    ctx.lineTo(x0 + w, y0 + h);
    ctx.stroke();

    // Y-axis label
    ctx.save();
    ctx.translate(12, y0 + h / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = this.options.axisColor;
    ctx.font = `500 ${this.options.fontSize}px ${this.options.fontFamily}`;
    ctx.fillText("Object Count", 0, 0);
    ctx.restore();

    ctx.restore();
  }

  _drawSeries(ctx, dataset, x0, y0, w, h, yMax, count, color) {
    if (count < 1) return;

    const data = dataset.data;
    ctx.save();

    // Compute points
    const points = data.map((val, i) => ({
      x: x0 + (i / Math.max(count - 1, 1)) * w,
      y: y0 + h - (val / yMax) * h,
    }));

    // Area fill
    ctx.beginPath();
    ctx.moveTo(points[0].x, y0 + h);
    for (const pt of points) {
      ctx.lineTo(pt.x, pt.y);
    }
    ctx.lineTo(points[points.length - 1].x, y0 + h);
    ctx.closePath();
    ctx.fillStyle = color + this._toAlphaHex(this.options.areaOpacity);
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = this.options.lineWidth;
    ctx.lineJoin = "round";
    ctx.stroke();

    // Data points
    for (const pt of points) {
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, this.options.pointRadius, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    }

    ctx.restore();
  }

  _drawCrosshair(ctx, x0, y0, w, h, count) {
    const xPos = x0 + (this._hoverIndex / Math.max(count - 1, 1)) * w;

    ctx.save();
    ctx.strokeStyle = "rgba(148, 163, 184, 0.5)";
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(xPos, y0);
    ctx.lineTo(xPos, y0 + h);
    ctx.stroke();
    ctx.restore();
  }

  _drawSelectedMarker(ctx, x0, y0, w, h, count, datasets) {
    const xPos = x0 + (this._selectedIndex / Math.max(count - 1, 1)) * w;

    // Vertical line — solid, brighter
    ctx.save();
    ctx.strokeStyle = "#3b82f6";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xPos, y0);
    ctx.lineTo(xPos, y0 + h);
    ctx.stroke();

    // Highlight circles at each series' value at this index
    const yMax = this._niceMax(Math.max(...datasets.flatMap(d => d.data), 1));
    datasets.forEach((ds, i) => {
      const val = ds.data[this._selectedIndex] ?? 0;
      const py = y0 + h - (val / yMax) * h;
      const color = this._palette[i % this._palette.length];

      // Outer ring
      ctx.beginPath();
      ctx.arc(xPos, py, 6, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(59, 130, 246, 0.3)";
      ctx.fill();

      // Inner dot
      ctx.beginPath();
      ctx.arc(xPos, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.stroke();
    });

    // Time label at top
    const label = this._formatTimeLabel(this._chartData.labels[this._selectedIndex]);
    ctx.font = `600 ${this.options.fontSize}px ${this.options.fontFamily}`;
    const labelW = ctx.measureText(label).width + 12;
    const labelX = Math.min(Math.max(xPos - labelW / 2, x0), x0 + w - labelW);
    const labelY = y0 - 2;

    ctx.fillStyle = "#3b82f6";
    ctx.beginPath();
    ctx.roundRect(labelX, labelY - 16, labelW, 18, 4);
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, labelX + labelW / 2, labelY - 7);

    ctx.restore();
  }

  _drawLegend(ctx, canvasW, datasets) {
    if (datasets.length <= 1) return;

    ctx.save();
    ctx.font = `500 ${this.options.fontSize}px ${this.options.fontFamily}`;

    const legendItems = datasets.map((ds, i) => ({
      label: ds.spaceId,
      color: this._palette[i % this._palette.length],
    }));

    let x = this.options.paddingLeft;
    const y = 10;

    for (const item of legendItems) {
      // Color box
      ctx.fillStyle = item.color;
      ctx.fillRect(x, y - 4, 10, 10);
      x += 14;
      // Label
      ctx.fillStyle = this.options.axisColor;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(item.label, x, y + 1);
      x += ctx.measureText(item.label).width + 16;

      if (x > canvasW - 50) break; // Overflow protection
    }

    ctx.restore();
  }

  _renderEmptyState(ctx, w, h) {
    ctx.save();
    ctx.fillStyle = "#64748b";
    ctx.font = `400 14px ${this.options.fontFamily}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("No time-series data available", w / 2, h / 2 - 10);
    ctx.font = `400 12px ${this.options.fontFamily}`;
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("Congestion timeseries will appear when dynamic data is ingested", w / 2, h / 2 + 12);
    ctx.restore();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Interaction
  // ═══════════════════════════════════════════════════════════════════

  _onMouseMove(e) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const w = parseFloat(this.canvas.style.width) || this.canvas.width;
    const pl = this.options.paddingLeft;
    const pr = this.options.paddingRight;
    const chartW = w - pl - pr;
    const { labels, datasets } = this._chartData;

    if (!labels.length) return;

    // Find nearest data index
    const relX = mx - pl;
    const ratio = relX / chartW;
    const idx = Math.round(ratio * (labels.length - 1));
    this._hoverIndex = Math.max(0, Math.min(idx, labels.length - 1));

    // Build tooltip
    const time = this._formatTimeLabel(labels[this._hoverIndex]);
    let html = `<strong>${time}</strong><br>`;
    datasets.forEach((ds, i) => {
      const color = this._palette[i % this._palette.length];
      const val = ds.data[this._hoverIndex] ?? 0;
      html += `<span style="color:${color}">\u25CF</span> ${ds.spaceId}: <strong>${val}</strong><br>`;
    });

    this._tooltipEl.innerHTML = html;
    this._tooltipEl.style.display = "block";
    this._tooltipEl.style.left = e.clientX + 12 + "px";
    this._tooltipEl.style.top = e.clientY - 10 + "px";

    this._render();
  }

  _onMouseLeave() {
    this._hoverIndex = -1;
    this._tooltipEl.style.display = "none";
    this._render();
  }

  _onClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const w = parseFloat(this.canvas.style.width) || this.canvas.width;
    const pl = this.options.paddingLeft;
    const pr = this.options.paddingRight;
    const chartW = w - pl - pr;
    const { labels } = this._chartData;

    if (!labels.length) return;

    const relX = mx - pl;
    const ratio = relX / chartW;
    const idx = Math.round(ratio * (labels.length - 1));
    const clampedIdx = Math.max(0, Math.min(idx, labels.length - 1));

    // Toggle selection: click same index deselects
    if (this._selectedIndex === clampedIdx) {
      this._selectedIndex = -1;
    } else {
      this._selectedIndex = clampedIdx;
    }

    this._render();

    // Gather per-space values at this time index
    const { datasets } = this._chartData;
    const spaceValues = {};
    if (this._selectedIndex >= 0) {
      for (const ds of datasets) {
        spaceValues[ds.spaceId] = ds.data[this._selectedIndex] ?? 0;
      }
    }

    // Dispatch custom event for heatmap synchronization
    this.canvas.dispatchEvent(
      new CustomEvent("time-selected", {
        detail: {
          index: this._selectedIndex,
          timestamp: this._selectedIndex >= 0 ? labels[this._selectedIndex] : null,
          spaceValues,
        },
        bubbles: true,
      })
    );
  }

  /** External: programmatically select a time index */
  selectTimeIndex(index) {
    const { labels } = this._chartData;
    if (index < 0 || index >= labels.length) {
      this._selectedIndex = -1;
    } else {
      this._selectedIndex = index;
    }
    this._render();
  }

  /** Get currently selected time index */
  getSelectedTimeIndex() {
    return this._selectedIndex;
  }

  /** Get the timestamp at the selected index */
  getSelectedTimestamp() {
    if (this._selectedIndex < 0) return null;
    return this._chartData.labels[this._selectedIndex] || null;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Helpers
  // ═══════════════════════════════════════════════════════════════════

  _getYTicks(yMax) {
    const step = Math.max(1, Math.ceil(yMax / this.options.maxYTicks));
    const ticks = [];
    for (let v = 0; v <= yMax; v += step) {
      ticks.push(v);
    }
    return ticks;
  }

  _niceMax(val) {
    if (val <= 5) return 5;
    const mag = Math.pow(10, Math.floor(Math.log10(val)));
    const norm = val / mag;
    if (norm <= 1.5) return 1.5 * mag;
    if (norm <= 2) return 2 * mag;
    if (norm <= 3) return 3 * mag;
    if (norm <= 5) return 5 * mag;
    return 10 * mag;
  }

  _formatTimeLabel(isoStr) {
    if (!isoStr) return "";
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return String(isoStr).slice(11, 16);
    }
  }

  _toAlphaHex(opacity) {
    const hex = Math.round(opacity * 255)
      .toString(16)
      .padStart(2, "0");
    return hex;
  }

  /** Clean up */
  destroy() {
    if (this._unwatch) this._unwatch();
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (this._tooltipEl) this._tooltipEl.remove();
  }
}

// Export
if (typeof window !== "undefined") {
  window.ChartComponent = ChartComponent;
}
