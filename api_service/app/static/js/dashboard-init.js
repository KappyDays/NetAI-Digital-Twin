/**
 * Dashboard Initialization Script
 *
 * Bootstraps the full dashboard stack:
 *   1. LakehouseAPIClient - HTTP client for FastAPI endpoints
 *   2. DataPollingService - Periodic data fetching with channels
 *   3. DashboardStore - Reactive data store with watchers
 *   4. HeatmapComponent - Canvas-based space congestion heatmap
 *   5. ChartComponent - Time-series congestion chart
 *   6. UI bindings - KPI cards, tables, status indicators
 */

(function () {
  "use strict";

  // ── Global references ──────────────────────────────────────────
  let apiClient, pollingService, store, heatmap, chart;

  // ── DOM Ready ──────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    initDashboard();
  });

  function initDashboard() {
    console.info("[Dashboard] Initializing...");

    // 1. API Client (same-origin)
    apiClient = new LakehouseAPIClient("", 15000);

    // 2. Polling Service with dashboard-standard channels
    pollingService = createDashboardPollingService(apiClient, {
      congestion: 5000,
      "congestion-ts": 15000,
      "dynamic-latest": 5000,
      "dynamic-objects": 30000,
      "static-spaces": 30000,
      "static-count": 30000,
      "static-types": 60000,
      health: 10000,
    });

    // 3. Dashboard Store
    store = new DashboardStore(pollingService);

    // 4. Initialize visualization components
    initHeatmap();
    initChart();

    // 5. Bind UI elements
    bindKPICards();
    bindDynamicObjectsTable();
    bindStatusIndicator();
    bindPollingControls();

    // 6. Start polling
    pollingService.startAll();

    // Make available for debugging
    window.__dashboard = { apiClient, pollingService, store, heatmap, chart };

    console.info("[Dashboard] Ready. Polling started.");
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Component Initialization
  // ═══════════════════════════════════════════════════════════════════

  function initHeatmap() {
    const canvas = document.getElementById("heatmap-canvas");
    if (!canvas) {
      console.warn("[Dashboard] Heatmap canvas not found");
      return;
    }
    heatmap = new HeatmapComponent(canvas, store, {
      cellPadding: 6,
      cellRadius: 8,
      maxColumns: 5,
      fontSize: 13,
      animationDuration: 300,
    });
  }

  function initChart() {
    const canvas = document.getElementById("chart-canvas");
    if (!canvas) {
      console.warn("[Dashboard] Chart canvas not found");
      return;
    }
    chart = new ChartComponent(canvas, store, {
      lineWidth: 2.5,
      pointRadius: 3,
      areaOpacity: 0.12,
      animationDuration: 400,
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  KPI Cards Binding
  // ═══════════════════════════════════════════════════════════════════

  function bindKPICards() {
    const elements = {
      totalDynamic: document.getElementById("kpi-total-dynamic"),
      totalStatic: document.getElementById("kpi-total-static"),
      totalSpaces: document.getElementById("kpi-total-spaces"),
      trackedObjects: document.getElementById("kpi-tracked-objects"),
      congestionSpaces: document.getElementById("kpi-congestion-spaces"),
      uptime: document.getElementById("kpi-uptime"),
    };

    // Watch relevant store keys and update KPI cards
    store.watch("dynamicObjects", (data) => {
      if (elements.totalDynamic) {
        elements.totalDynamic.textContent = data.total || 0;
      }
    });

    store.watch("staticCount", (data) => {
      if (elements.totalStatic) {
        elements.totalStatic.textContent = formatNumber(data.totalCount || 0);
      }
      if (elements.totalSpaces) {
        elements.totalSpaces.textContent = data.spaceCount || 0;
      }
    });

    store.watch("congestion", (data) => {
      if (elements.trackedObjects) {
        elements.trackedObjects.textContent = data.totalObjects || 0;
      }
      if (elements.congestionSpaces) {
        elements.congestionSpaces.textContent = data.spaces?.length || 0;
      }
    });

    store.watch("health", (data) => {
      if (elements.uptime) {
        elements.uptime.textContent = formatUptime(data.uptime || 0);
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Dynamic Objects Table
  // ═══════════════════════════════════════════════════════════════════

  function bindDynamicObjectsTable() {
    const tbody = document.getElementById("dynamic-objects-tbody");
    if (!tbody) return;

    store.watch("dynamicLatest", (data) => {
      const objects = data.byObject || {};
      const entries = Object.values(objects);

      if (!entries.length) {
        tbody.innerHTML =
          '<tr><td colspan="7" class="empty-state__text">No dynamic objects tracked yet</td></tr>';
        return;
      }

      tbody.innerHTML = entries
        .map(
          (obj) => `
        <tr>
          <td class="mono">${escapeHtml(obj.objectId)}</td>
          <td class="mono">${escapeHtml(obj.spaceId || "-")}</td>
          <td class="mono">${fmtCoord(obj.posX)}, ${fmtCoord(obj.posY)}, ${fmtCoord(obj.posZ)}</td>
          <td class="mono">${fmtCoord(obj.speed)}</td>
          <td>${formatTimestamp(obj.timestamp)}</td>
          <td>${getCongestionBadge(obj.spaceId)}</td>
        </tr>
      `
        )
        .join("");
    });
  }

  function getCongestionBadge(spaceId) {
    if (!spaceId) return '<span class="badge badge--low">N/A</span>';
    const space = store.state.congestion.spaces.find(
      (s) => s.space_id === spaceId
    );
    if (!space) return '<span class="badge badge--low">Low</span>';

    const level = space.congestion_level;
    if (level >= 0.6) return '<span class="badge badge--high">High</span>';
    if (level >= 0.3) return '<span class="badge badge--medium">Medium</span>';
    return '<span class="badge badge--low">Low</span>';
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Status Indicator
  // ═══════════════════════════════════════════════════════════════════

  function bindStatusIndicator() {
    const dot = document.getElementById("status-dot");
    const label = document.getElementById("status-label");
    const updateTime = document.getElementById("last-update-time");

    store.watch("health", (data) => {
      if (dot) {
        dot.className = "status-dot";
        if (data.status === "healthy") dot.className += "";
        else if (data.status === "degraded") dot.className += " status-dot--warning";
        else dot.className += " status-dot--error";
      }
      if (label) {
        label.textContent = data.status || "unknown";
      }
    });

    // Update timestamp on any data change
    store.watch("*", (state, key) => {
      if (updateTime && state.lastUpdate) {
        updateTime.textContent = new Date(state.lastUpdate).toLocaleTimeString();
      }
    });

    // Visual fetch indicator
    pollingService.on("data:updated", () => {
      const fetchDot = document.getElementById("fetch-dot");
      if (fetchDot) {
        fetchDot.classList.add("fetching");
        setTimeout(() => fetchDot.classList.remove("fetching"), 500);
      }
    });
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Polling Controls
  // ═══════════════════════════════════════════════════════════════════

  function bindPollingControls() {
    const pauseBtn = document.getElementById("btn-pause");
    const resumeBtn = document.getElementById("btn-resume");
    const refreshBtn = document.getElementById("btn-refresh");
    const intervalSelect = document.getElementById("polling-interval");

    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        pollingService.pause();
        pauseBtn.classList.add("btn--primary");
        if (resumeBtn) resumeBtn.classList.remove("btn--primary");
      });
    }

    if (resumeBtn) {
      resumeBtn.addEventListener("click", () => {
        pollingService.resume();
        if (pauseBtn) pauseBtn.classList.remove("btn--primary");
        resumeBtn.classList.add("btn--primary");
      });
    }

    if (refreshBtn) {
      refreshBtn.addEventListener("click", async () => {
        refreshBtn.disabled = true;
        refreshBtn.textContent = "Refreshing...";
        try {
          await Promise.allSettled([
            pollingService.fetchNow("congestion"),
            pollingService.fetchNow("congestion-ts"),
            pollingService.fetchNow("dynamic-latest"),
            pollingService.fetchNow("health"),
          ]);
        } catch (_) {}
        refreshBtn.disabled = false;
        refreshBtn.textContent = "Refresh Now";
      });
    }

    if (intervalSelect) {
      intervalSelect.addEventListener("change", (e) => {
        const ms = parseInt(e.target.value, 10);
        pollingService.setInterval("congestion", ms);
        pollingService.setInterval("dynamic-latest", ms);
        console.info(`[Dashboard] Polling interval set to ${ms}ms`);
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Utility Functions
  // ═══════════════════════════════════════════════════════════════════

  function formatNumber(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
    if (n >= 1000) return (n / 1000).toFixed(1) + "K";
    return String(n);
  }

  function formatUptime(seconds) {
    if (!seconds) return "0s";
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  }

  function formatTimestamp(ts) {
    if (!ts) return "-";
    try {
      return new Date(ts).toLocaleTimeString();
    } catch {
      return String(ts);
    }
  }

  function fmtCoord(val) {
    if (val == null) return "-";
    return Number(val).toFixed(2);
  }

  function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
})();
