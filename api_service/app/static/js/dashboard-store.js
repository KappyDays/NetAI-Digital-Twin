/**
 * Dashboard Store
 *
 * Reactive data store that aggregates polled data from the DataPollingService
 * and distributes it to visualization components (heatmap, charts, panels).
 *
 * Responsibilities:
 *   - Subscribes to all polling channels
 *   - Maintains latest state snapshots
 *   - Computes derived metrics (congestion deltas, trend data)
 *   - Provides a simple reactive binding for UI components
 *
 * Pattern: Observer + Computed Properties (lightweight Vuex-like store)
 */

class DashboardStore {
  /**
   * @param {DataPollingService} pollingService
   */
  constructor(pollingService) {
    this.polling = pollingService;

    // ── State ──────────────────────────────────────────────────────
    this.state = {
      // System
      health: { status: "unknown", dependencies: {}, uptime: 0, version: "" },
      connected: false,
      lastUpdate: null,

      // Congestion (heatmap)
      congestion: {
        spaces: [],          // Array<{ space_id, object_count, congestion_level, timestamp }>
        totalObjects: 0,
        snapshotTime: null,
        history: [],         // Rolling window of last N snapshots for delta calculation
      },

      // Congestion time-series (chart)
      congestionTimeseries: {
        columns: [],
        rows: [],
        rowCount: 0,
        // Transformed: { spaceId -> [{ timeBucket, objectCount }] }
        bySpace: {},
      },

      // Dynamic objects
      dynamicLatest: {
        columns: [],
        rows: [],
        rowCount: 0,
        // Transformed: { objectId -> { pos_x, pos_y, pos_z, speed, space_id, timestamp } }
        byObject: {},
      },
      dynamicObjects: {
        objects: [],
        total: 0,
      },

      // Static objects
      staticSpaces: { spaces: [], totalSpaces: 0 },
      staticCount: { totalCount: 0, spaceCounts: {}, spaceCount: 0 },
      staticTypes: { types: [], totalTypes: 0 },
    };

    // ── History Config ─────────────────────────────────────────────
    this._congestionHistoryMax = 60; // Keep last 60 congestion snapshots

    // ── Watchers ──────────────────────────────────────────────────
    /** @type {Map<string, Set<Function>>} */
    this._watchers = new Map();

    // ── Wire up polling events ────────────────────────────────────
    this._subscriptions = [];
    this._bindPollingEvents();
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Reactive Watchers
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Watch a state key for changes.
   * @param {string} key - State key (e.g., "congestion", "health", "dynamicLatest")
   * @param {Function} callback - Called with (newValue, key) on change
   * @returns {Function} Unwatch function
   */
  watch(key, callback) {
    if (!this._watchers.has(key)) {
      this._watchers.set(key, new Set());
    }
    this._watchers.get(key).add(callback);
    return () => this._watchers.get(key)?.delete(callback);
  }

  /** Notify watchers of a state change */
  _notify(key) {
    const watchers = this._watchers.get(key);
    if (watchers) {
      const value = this.state[key];
      watchers.forEach((cb) => {
        try {
          cb(value, key);
        } catch (err) {
          console.error(`[DashboardStore] Watcher error for '${key}':`, err);
        }
      });
    }
    // Also notify '*' global watchers
    const globalWatchers = this._watchers.get("*");
    if (globalWatchers) {
      globalWatchers.forEach((cb) => {
        try {
          cb(this.state, key);
        } catch (err) {
          console.error(`[DashboardStore] Global watcher error:`, err);
        }
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Polling Event Bindings
  // ═══════════════════════════════════════════════════════════════════

  _bindPollingEvents() {
    const p = this.polling;

    // Congestion (heatmap data)
    this._subscriptions.push(
      p.on("congestion", ({ data, timestamp }) => {
        // Push to history
        this.state.congestion.history.push({
          spaces: data.spaces,
          totalObjects: data.totalObjects,
          time: timestamp,
        });
        if (this.state.congestion.history.length > this._congestionHistoryMax) {
          this.state.congestion.history.shift();
        }

        // Update current
        this.state.congestion.spaces = data.spaces;
        this.state.congestion.totalObjects = data.totalObjects;
        this.state.congestion.snapshotTime = data.snapshotTime;
        this.state.lastUpdate = timestamp;
        this.state.connected = true;
        this._notify("congestion");
      })
    );

    // Congestion time-series (chart data)
    this._subscriptions.push(
      p.on("congestion-ts", ({ data }) => {
        this.state.congestionTimeseries.columns = data.columns;
        this.state.congestionTimeseries.rows = data.rows;
        this.state.congestionTimeseries.rowCount = data.rowCount;

        // Transform rows into per-space time-series
        this.state.congestionTimeseries.bySpace = this._transformTimeseriesRows(
          data.columns,
          data.rows
        );
        this._notify("congestionTimeseries");
      })
    );

    // Dynamic latest
    this._subscriptions.push(
      p.on("dynamic-latest", ({ data }) => {
        this.state.dynamicLatest.columns = data.columns;
        this.state.dynamicLatest.rows = data.rows;
        this.state.dynamicLatest.rowCount = data.rowCount;

        // Transform to per-object map
        this.state.dynamicLatest.byObject = this._transformDynamicRows(
          data.columns,
          data.rows
        );
        this._notify("dynamicLatest");
      })
    );

    // Dynamic objects registry
    this._subscriptions.push(
      p.on("dynamic-objects", ({ data }) => {
        this.state.dynamicObjects = data;
        this._notify("dynamicObjects");
      })
    );

    // Static spaces
    this._subscriptions.push(
      p.on("static-spaces", ({ data }) => {
        this.state.staticSpaces = data;
        this._notify("staticSpaces");
      })
    );

    // Static count
    this._subscriptions.push(
      p.on("static-count", ({ data }) => {
        this.state.staticCount = data;
        this._notify("staticCount");
      })
    );

    // Static types
    this._subscriptions.push(
      p.on("static-types", ({ data }) => {
        this.state.staticTypes = data;
        this._notify("staticTypes");
      })
    );

    // Health
    this._subscriptions.push(
      p.on("health", ({ data }) => {
        this.state.health = data;
        this.state.connected = data.status === "healthy" || data.status === "degraded";
        this._notify("health");
      })
    );

    // Error handling
    this._subscriptions.push(
      p.on("error", ({ channelId, error, consecutiveErrors }) => {
        if (consecutiveErrors >= 3) {
          this.state.connected = false;
          this._notify("health");
        }
        console.warn(
          `[DashboardStore] Polling error on '${channelId}':`,
          error.message || error
        );
      })
    );
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Data Transformers
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Transform congestion timeseries rows into per-space arrays.
   * Expected columns: [space_id, time_bucket, object_count]
   * Output: { spaceId: [{ timeBucket, objectCount }] }
   */
  _transformTimeseriesRows(columns, rows) {
    const spaceIdx = columns.indexOf("space_id");
    const timeIdx = columns.indexOf("time_bucket");
    const countIdx = columns.indexOf("object_count");

    if (spaceIdx < 0 || timeIdx < 0 || countIdx < 0) return {};

    const bySpace = {};
    for (const row of rows) {
      const spaceId = row[spaceIdx];
      const timeBucket = row[timeIdx];
      const objectCount = row[countIdx];

      if (!bySpace[spaceId]) bySpace[spaceId] = [];
      bySpace[spaceId].push({ timeBucket, objectCount });
    }
    return bySpace;
  }

  /**
   * Transform dynamic latest rows into per-object map.
   * Expected columns: [object_id, timestamp, pos_x, pos_y, pos_z, rot_x, rot_y, rot_z, speed, space_id, properties]
   */
  _transformDynamicRows(columns, rows) {
    if (!columns.length || !rows.length) return {};

    const colMap = {};
    columns.forEach((c, i) => (colMap[c] = i));

    const byObject = {};
    for (const row of rows) {
      const objectId = row[colMap.object_id ?? 0];
      byObject[objectId] = {
        objectId,
        timestamp: row[colMap.timestamp ?? 1],
        posX: row[colMap.pos_x ?? 2],
        posY: row[colMap.pos_y ?? 3],
        posZ: row[colMap.pos_z ?? 4],
        rotX: row[colMap.rot_x ?? 5],
        rotY: row[colMap.rot_y ?? 6],
        rotZ: row[colMap.rot_z ?? 7],
        speed: row[colMap.speed ?? 8],
        spaceId: row[colMap.space_id ?? 9],
        properties: row[colMap.properties ?? 10],
      };
    }
    return byObject;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Computed / Derived Getters
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Get congestion data formatted for heatmap rendering.
   * Returns: Array<{ spaceId, level, count, label, color }>
   */
  getHeatmapData() {
    return this.state.congestion.spaces.map((s) => ({
      spaceId: s.space_id,
      level: s.congestion_level,
      count: s.object_count,
      label: `${s.space_id}: ${s.object_count} objects`,
      color: this._congestionColor(s.congestion_level),
    }));
  }

  /**
   * Get heatmap data using a snapshot of per-space values from a specific time.
   * Used when the user clicks a time point on the chart.
   * @param {Object} spaceValues - Map of spaceId -> objectCount at the selected time
   * Returns: Array<{ spaceId, level, count, label, color }>
   */
  getHeatmapDataAtSnapshot(spaceValues) {
    // Use the current spaces list as the base (for space IDs), but override counts
    const currentSpaces = this.state.congestion.spaces;

    // Find max count across the snapshot for normalization
    const allCounts = Object.values(spaceValues);
    const maxCount = Math.max(...allCounts, 1);

    // If we have current spaces, use them; otherwise build from spaceValues keys
    const spaceIds = currentSpaces.length > 0
      ? currentSpaces.map(s => s.space_id)
      : Object.keys(spaceValues);

    return spaceIds.map((spaceId) => {
      const count = spaceValues[spaceId] ?? 0;
      const level = Math.min(count / maxCount, 1);
      return {
        spaceId,
        level,
        count,
        label: `${spaceId}: ${count} objects`,
        color: this._congestionColor(level),
      };
    });
  }

  /**
   * Get time-series data for a specific space at all time points.
   * Used when the user clicks a heatmap space.
   * @param {string} spaceId - The space ID to get history for
   * Returns: Array<{ timeBucket, objectCount }>
   */
  getSpaceTimeseries(spaceId) {
    const bySpace = this.state.congestionTimeseries.bySpace;
    return bySpace[spaceId] || [];
  }

  /**
   * Get congestion delta (change since previous snapshot).
   * Returns: Map<spaceId, delta>
   */
  getCongestionDelta() {
    const history = this.state.congestion.history;
    if (history.length < 2) return {};

    const current = history[history.length - 1];
    const previous = history[history.length - 2];

    const prevMap = {};
    for (const s of previous.spaces) {
      prevMap[s.space_id] = s.object_count;
    }

    const delta = {};
    for (const s of current.spaces) {
      delta[s.space_id] = s.object_count - (prevMap[s.space_id] || 0);
    }
    return delta;
  }

  /**
   * Get time-series chart data for a specific space (or all spaces).
   * Returns: { labels: string[], datasets: [{ spaceId, data: number[] }] }
   */
  getChartData(spaceId = null) {
    const bySpace = this.state.congestionTimeseries.bySpace;
    const spaces = spaceId ? { [spaceId]: bySpace[spaceId] || [] } : bySpace;

    // Collect all unique time buckets
    const allTimes = new Set();
    for (const series of Object.values(spaces)) {
      for (const pt of series) {
        allTimes.add(pt.timeBucket);
      }
    }
    const sortedTimes = [...allTimes].sort();

    const datasets = [];
    for (const [sid, series] of Object.entries(spaces)) {
      const timeMap = {};
      for (const pt of series) {
        timeMap[pt.timeBucket] = pt.objectCount;
      }
      datasets.push({
        spaceId: sid,
        data: sortedTimes.map((t) => timeMap[t] || 0),
      });
    }

    return {
      labels: sortedTimes,
      datasets,
    };
  }

  /**
   * Get summary statistics for the dashboard overview cards.
   */
  getSummaryStats() {
    return {
      totalDynamicObjects: this.state.dynamicObjects.total,
      activeDynamicObjects: this.state.dynamicLatest.rowCount,
      totalStaticPrims: this.state.staticCount.totalCount,
      totalSpaces: this.state.staticCount.spaceCount,
      congestionSpaces: this.state.congestion.spaces.length,
      totalTrackedObjects: this.state.congestion.totalObjects,
      systemHealth: this.state.health.status,
      uptime: this.state.health.uptime,
      lastUpdate: this.state.lastUpdate,
    };
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Helpers
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Map congestion level (0..1) to a color string (green -> yellow -> red).
   */
  _congestionColor(level) {
    if (level <= 0.0) return "#22c55e"; // green
    if (level <= 0.2) return "#4ade80";
    if (level <= 0.4) return "#facc15"; // yellow
    if (level <= 0.6) return "#f97316"; // orange
    if (level <= 0.8) return "#ef4444"; // red
    return "#dc2626"; // deep red
  }

  /** Clean up all subscriptions */
  destroy() {
    this._subscriptions.forEach((unsub) => unsub());
    this._subscriptions = [];
    this._watchers.clear();
  }
}

// Export
if (typeof window !== "undefined") {
  window.DashboardStore = DashboardStore;
}
