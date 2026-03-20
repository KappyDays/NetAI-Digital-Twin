/**
 * Heatmap Component
 *
 * Canvas-based space congestion heatmap visualization.
 * Renders each space as a colored cell with object count overlay.
 * Auto-updates when the DashboardStore's congestion data changes.
 *
 * Features:
 *   - Color gradient: green (empty) -> red (congested)
 *   - Object count labels per cell
 *   - Tooltip on hover
 *   - Responsive canvas sizing
 *   - Animated transitions between data updates
 *   - Click-to-select space interaction
 */

class HeatmapComponent {
  /**
   * @param {HTMLCanvasElement} canvas - Target canvas element
   * @param {DashboardStore} store - Dashboard data store
   * @param {object} options - Rendering options
   */
  constructor(canvas, store, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.store = store;

    this.options = {
      cellPadding: options.cellPadding || 4,
      cellRadius: options.cellRadius || 8,
      minCellWidth: options.minCellWidth || 100,
      maxColumns: options.maxColumns || 6,
      fontSize: options.fontSize || 13,
      fontFamily: options.fontFamily || "'Inter', 'Segoe UI', sans-serif",
      animationDuration: options.animationDuration || 300,
      showLabels: options.showLabels !== false,
      showCounts: options.showCounts !== false,
      ...options,
    };

    // Internal state
    this._cells = [];          // Current cell layout
    this._animating = false;
    this._prevLevels = {};     // Previous congestion levels for animation
    this._selectedSpace = null;
    this._hoveredCell = null;
    this._tooltipEl = null;
    this._unwatch = null;
    this._resizeObserver = null;
    this._timeSnapshot = null; // { timestamp, spaceValues: { spaceId: count } }
    this._timeLabel = null;    // Display label for selected time

    this._init();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Initialization
  // ═══════════════════════════════════════════════════════════════════

  _init() {
    // Set up canvas sizing
    this._setupResize();

    // Set up interactivity
    this._setupEvents();

    // Create tooltip element
    this._createTooltip();

    // Subscribe to store changes
    this._unwatch = this.store.watch("congestion", () => this._onDataUpdate());

    // Listen for time-selected events from ChartComponent
    this._onTimeSelectedBound = (e) => this._onTimeSelected(e);
    document.addEventListener("time-selected", this._onTimeSelectedBound);

    // Initial render
    this._onDataUpdate();
  }

  _setupResize() {
    const resize = () => {
      const rect = this.canvas.parentElement?.getBoundingClientRect();
      if (rect) {
        this.canvas.width = rect.width * (window.devicePixelRatio || 1);
        this.canvas.height = rect.height * (window.devicePixelRatio || 1);
        this.canvas.style.width = rect.width + "px";
        this.canvas.style.height = rect.height + "px";
        this.ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
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
    this._tooltipEl.className = "heatmap-tooltip";
    this._tooltipEl.style.cssText =
      "position:fixed;display:none;background:#1e293b;color:#f8fafc;" +
      "padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;" +
      "box-shadow:0 4px 12px rgba(0,0,0,0.3);z-index:9999;white-space:nowrap;";
    document.body.appendChild(this._tooltipEl);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Data Update & Layout
  // ═══════════════════════════════════════════════════════════════════

  _onTimeSelected(e) {
    const { timestamp, spaceValues, index } = e.detail;

    if (index < 0 || !timestamp) {
      // Deselect — return to live data
      this._timeSnapshot = null;
      this._timeLabel = null;
      this._onDataUpdate();
      return;
    }

    // Store snapshot data
    this._timeSnapshot = spaceValues;
    try {
      const d = new Date(timestamp);
      this._timeLabel = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch {
      this._timeLabel = String(timestamp).slice(11, 19);
    }

    // Rebuild heatmap with snapshot data
    this._onDataUpdate();
  }

  _onDataUpdate() {
    let heatmapData;
    let delta;

    if (this._timeSnapshot) {
      // Use time-snapshot values from chart selection
      heatmapData = this.store.getHeatmapDataAtSnapshot(this._timeSnapshot);
      delta = {};
    } else {
      // Live data
      heatmapData = this.store.getHeatmapData();
      delta = this.store.getCongestionDelta();
    }

    // Compute layout
    this._cells = this._computeLayout(heatmapData, delta);

    // Animate transition
    this._animateTransition();
  }

  _computeLayout(data, delta) {
    const w = parseFloat(this.canvas.style.width) || this.canvas.width;
    const h = parseFloat(this.canvas.style.height) || this.canvas.height;
    const pad = this.options.cellPadding;

    if (!data.length) return [];

    // Compute grid dimensions
    const cols = Math.min(data.length, this.options.maxColumns);
    const rows = Math.ceil(data.length / cols);
    const cellW = Math.max((w - pad * (cols + 1)) / cols, this.options.minCellWidth);
    const cellH = Math.max((h - pad * (rows + 1)) / rows, 40);

    return data.map((d, i) => {
      const col = i % cols;
      const row = Math.floor(i / cols);
      return {
        ...d,
        x: pad + col * (cellW + pad),
        y: pad + row * (cellH + pad),
        w: cellW,
        h: cellH,
        delta: delta[d.spaceId] || 0,
        targetLevel: d.level,
        currentLevel: this._prevLevels[d.spaceId] ?? d.level,
      };
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Animation
  // ═══════════════════════════════════════════════════════════════════

  _animateTransition() {
    if (this._animating) return;

    const duration = this.options.animationDuration;
    const startTime = performance.now();
    this._animating = true;

    const animate = (now) => {
      const elapsed = now - startTime;
      const t = Math.min(elapsed / duration, 1);
      const eased = t * (2 - t); // ease-out quad

      // Interpolate congestion levels
      for (const cell of this._cells) {
        cell.currentLevel =
          cell.currentLevel + (cell.targetLevel - cell.currentLevel) * eased;
      }

      this._render();

      if (t < 1) {
        requestAnimationFrame(animate);
      } else {
        this._animating = false;
        // Store final levels for next transition
        for (const cell of this._cells) {
          this._prevLevels[cell.spaceId] = cell.targetLevel;
        }
      }
    };

    requestAnimationFrame(animate);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Rendering
  // ═══════════════════════════════════════════════════════════════════

  _render() {
    const ctx = this.ctx;
    const w = parseFloat(this.canvas.style.width) || this.canvas.width;
    const h = parseFloat(this.canvas.style.height) || this.canvas.height;

    // Clear
    ctx.clearRect(0, 0, w, h);

    if (!this._cells.length) {
      this._renderEmptyState(ctx, w, h);
      return;
    }

    // Draw cells
    for (const cell of this._cells) {
      this._renderCell(ctx, cell);
    }

    // Draw time-snapshot overlay badge
    if (this._timeLabel) {
      this._renderTimeOverlay(ctx, w);
    }
  }

  _renderTimeOverlay(ctx, canvasW) {
    ctx.save();
    const label = `\u23F1 ${this._timeLabel}`;
    ctx.font = `600 12px ${this.options.fontFamily}`;
    const textW = ctx.measureText(label).width + 16;
    const x = canvasW - textW - 8;
    const y = 8;

    // Badge background
    ctx.fillStyle = "rgba(59, 130, 246, 0.9)";
    ctx.beginPath();
    ctx.roundRect(x, y, textW, 22, 6);
    ctx.fill();

    // Text
    ctx.fillStyle = "#ffffff";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, x + textW / 2, y + 11);

    ctx.restore();
  }

  _renderCell(ctx, cell) {
    const { x, y, w, h, spaceId, count, currentLevel, delta } = cell;
    const isHovered = this._hoveredCell?.spaceId === spaceId;
    const isSelected = this._selectedSpace === spaceId;
    const r = this.options.cellRadius;

    // Background with congestion color
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);

    const color = this._levelToColor(currentLevel);
    ctx.fillStyle = color;
    ctx.fill();

    // Hover/selection outline
    if (isSelected) {
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 3;
      ctx.stroke();
    } else if (isHovered) {
      ctx.strokeStyle = "#94a3b8";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    ctx.restore();

    // Labels
    if (this.options.showLabels) {
      ctx.save();
      ctx.font = `600 ${this.options.fontSize}px ${this.options.fontFamily}`;
      ctx.fillStyle = currentLevel > 0.5 ? "#ffffff" : "#1e293b";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      // Space name
      const nameY = h > 60 ? y + h * 0.35 : y + h * 0.5;
      ctx.fillText(this._truncateLabel(spaceId, w - 16), x + w / 2, nameY);

      // Object count
      if (this.options.showCounts && h > 50) {
        ctx.font = `700 ${this.options.fontSize + 4}px ${this.options.fontFamily}`;
        ctx.fillText(String(count), x + w / 2, y + h * 0.6);

        // Delta indicator
        if (delta !== 0) {
          ctx.font = `500 ${this.options.fontSize - 2}px ${this.options.fontFamily}`;
          ctx.fillStyle = delta > 0 ? "#fbbf24" : "#34d399";
          const deltaText = delta > 0 ? `+${delta}` : String(delta);
          ctx.fillText(deltaText, x + w / 2, y + h * 0.8);
        }
      }

      ctx.restore();
    }
  }

  _renderEmptyState(ctx, w, h) {
    ctx.save();
    ctx.fillStyle = "#64748b";
    ctx.font = `400 14px ${this.options.fontFamily}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("No congestion data available", w / 2, h / 2 - 10);
    ctx.font = `400 12px ${this.options.fontFamily}`;
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("Waiting for dynamic object data...", w / 2, h / 2 + 12);
    ctx.restore();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Color Mapping
  // ═══════════════════════════════════════════════════════════════════

  _levelToColor(level) {
    // Gradient: green -> yellow -> orange -> red
    const stops = [
      { pos: 0.0, r: 34, g: 197, b: 94 },   // #22c55e green
      { pos: 0.3, r: 250, g: 204, b: 21 },   // #facc15 yellow
      { pos: 0.6, r: 249, g: 115, b: 22 },   // #f97316 orange
      { pos: 1.0, r: 220, g: 38, b: 38 },    // #dc2626 red
    ];

    const clamped = Math.max(0, Math.min(1, level));

    // Find surrounding stops
    let lower = stops[0], upper = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) {
      if (clamped >= stops[i].pos && clamped <= stops[i + 1].pos) {
        lower = stops[i];
        upper = stops[i + 1];
        break;
      }
    }

    const range = upper.pos - lower.pos || 1;
    const t = (clamped - lower.pos) / range;
    const r = Math.round(lower.r + (upper.r - lower.r) * t);
    const g = Math.round(lower.g + (upper.g - lower.g) * t);
    const b = Math.round(lower.b + (upper.b - lower.b) * t);

    return `rgb(${r}, ${g}, ${b})`;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Interaction
  // ═══════════════════════════════════════════════════════════════════

  _getCellAtPoint(clientX, clientY) {
    const rect = this.canvas.getBoundingClientRect();
    const mx = clientX - rect.left;
    const my = clientY - rect.top;

    for (const cell of this._cells) {
      if (mx >= cell.x && mx <= cell.x + cell.w && my >= cell.y && my <= cell.y + cell.h) {
        return cell;
      }
    }
    return null;
  }

  _onMouseMove(e) {
    const cell = this._getCellAtPoint(e.clientX, e.clientY);
    this._hoveredCell = cell;
    this.canvas.style.cursor = cell ? "pointer" : "default";

    if (cell) {
      const deltaText =
        cell.delta > 0
          ? ` (+${cell.delta})`
          : cell.delta < 0
          ? ` (${cell.delta})`
          : "";
      this._tooltipEl.innerHTML =
        `<strong>${cell.spaceId}</strong><br>` +
        `Objects: <strong>${cell.count}</strong>${deltaText}<br>` +
        `Congestion: <strong>${(cell.targetLevel * 100).toFixed(1)}%</strong>`;
      this._tooltipEl.style.display = "block";
      this._tooltipEl.style.left = e.clientX + 12 + "px";
      this._tooltipEl.style.top = e.clientY - 10 + "px";
    } else {
      this._tooltipEl.style.display = "none";
    }

    this._render();
  }

  _onMouseLeave() {
    this._hoveredCell = null;
    this._tooltipEl.style.display = "none";
    this._render();
  }

  _onClick(e) {
    const cell = this._getCellAtPoint(e.clientX, e.clientY);
    if (cell) {
      this._selectedSpace = this._selectedSpace === cell.spaceId ? null : cell.spaceId;
      this._render();

      // Dispatch custom event for other components
      this.canvas.dispatchEvent(
        new CustomEvent("space-selected", {
          detail: { spaceId: this._selectedSpace },
          bubbles: true,
        })
      );
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Helpers
  // ═══════════════════════════════════════════════════════════════════

  _truncateLabel(text, maxWidth) {
    const ctx = this.ctx;
    if (ctx.measureText(text).width <= maxWidth) return text;
    while (text.length > 3 && ctx.measureText(text + "...").width > maxWidth) {
      text = text.slice(0, -1);
    }
    return text + "...";
  }

  /** Get currently selected space */
  getSelectedSpace() {
    return this._selectedSpace;
  }

  /** Programmatically select a space */
  selectSpace(spaceId) {
    this._selectedSpace = spaceId;
    this._render();
  }

  /** Programmatically set time snapshot (alternative to event-driven) */
  setTimeSnapshot(timestamp, spaceValues) {
    if (!timestamp) {
      this._timeSnapshot = null;
      this._timeLabel = null;
    } else {
      this._timeSnapshot = spaceValues;
      try {
        const d = new Date(timestamp);
        this._timeLabel = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      } catch {
        this._timeLabel = String(timestamp).slice(11, 19);
      }
    }
    this._onDataUpdate();
  }

  /** Clear time snapshot and return to live data */
  clearTimeSnapshot() {
    this._timeSnapshot = null;
    this._timeLabel = null;
    this._onDataUpdate();
  }

  /** Clean up resources */
  destroy() {
    if (this._unwatch) this._unwatch();
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (this._tooltipEl) this._tooltipEl.remove();
    if (this._onTimeSelectedBound) {
      document.removeEventListener("time-selected", this._onTimeSelectedBound);
    }
  }
}

// Export
if (typeof window !== "undefined") {
  window.HeatmapComponent = HeatmapComponent;
}
