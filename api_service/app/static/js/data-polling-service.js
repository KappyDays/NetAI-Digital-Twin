/**
 * Data Polling Service
 *
 * Manages periodic data fetching from the Lakehouse API.
 * Supports multiple independent polling channels with configurable intervals,
 * error retry with exponential backoff, and event-based data distribution.
 *
 * Architecture:
 *   PollingService -> LakehouseAPIClient -> FastAPI /api/v1/*
 *                  -> EventEmitter -> DashboardStore / Components
 *
 * Each channel polls a specific API endpoint at a set interval.
 * On new data, it emits a typed event that the DashboardStore subscribes to.
 */

class DataPollingService {
  /**
   * @param {LakehouseAPIClient} apiClient - API client instance
   * @param {object} options - Global polling options
   */
  constructor(apiClient, options = {}) {
    this.api = apiClient;
    this.options = {
      defaultIntervalMs: options.defaultIntervalMs || 5000,
      maxRetries: options.maxRetries || 3,
      retryBackoffMs: options.retryBackoffMs || 2000,
      maxBackoffMs: options.maxBackoffMs || 30000,
      ...options,
    };

    /** @type {Map<string, PollingChannel>} Active polling channels */
    this._channels = new Map();

    /** @type {Map<string, Set<Function>>} Event listeners by event type */
    this._listeners = new Map();

    /** @type {boolean} Service-wide pause flag */
    this._paused = false;

    /** @type {object} Aggregate polling statistics */
    this.stats = {
      totalRequests: 0,
      totalErrors: 0,
      totalSuccesses: 0,
      lastError: null,
      startedAt: null,
    };
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Event Emitter
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Subscribe to a polling event.
   * @param {string} event - Event name (e.g., "congestion", "dynamic-latest", "error")
   * @param {Function} callback - Handler function(data)
   * @returns {Function} Unsubscribe function
   */
  on(event, callback) {
    if (!this._listeners.has(event)) {
      this._listeners.set(event, new Set());
    }
    this._listeners.get(event).add(callback);
    return () => this._listeners.get(event)?.delete(callback);
  }

  /** Emit an event to all subscribers */
  _emit(event, data) {
    const listeners = this._listeners.get(event);
    if (listeners) {
      listeners.forEach((cb) => {
        try {
          cb(data);
        } catch (err) {
          console.error(`[PollingService] Listener error on '${event}':`, err);
        }
      });
    }
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Channel Management
  // ═══════════════════════════════════════════════════════════════════

  /**
   * Register and start a polling channel.
   *
   * @param {string} channelId - Unique channel identifier (used as event name)
   * @param {Function} fetchFn - Async function that returns data (called with apiClient)
   * @param {object} channelOpts - Channel-specific options
   * @param {number} channelOpts.intervalMs - Polling interval in ms
   * @param {Function} channelOpts.transform - Optional transform(rawData) before emit
   * @param {boolean} channelOpts.immediate - Fetch immediately on start (default: true)
   * @returns {DataPollingService} this (for chaining)
   */
  register(channelId, fetchFn, channelOpts = {}) {
    if (this._channels.has(channelId)) {
      console.warn(`[PollingService] Channel '${channelId}' already registered, replacing.`);
      this.unregister(channelId);
    }

    const channel = new PollingChannel(channelId, fetchFn, {
      intervalMs: channelOpts.intervalMs || this.options.defaultIntervalMs,
      transform: channelOpts.transform || null,
      immediate: channelOpts.immediate !== false,
      maxRetries: this.options.maxRetries,
      retryBackoffMs: this.options.retryBackoffMs,
      maxBackoffMs: this.options.maxBackoffMs,
    });

    this._channels.set(channelId, channel);
    return this;
  }

  /** Unregister and stop a channel */
  unregister(channelId) {
    const channel = this._channels.get(channelId);
    if (channel) {
      channel.stop();
      this._channels.delete(channelId);
    }
  }

  /** Get channel info/status */
  getChannelStatus(channelId) {
    const ch = this._channels.get(channelId);
    if (!ch) return null;
    return {
      id: ch.id,
      running: ch.running,
      intervalMs: ch.intervalMs,
      fetchCount: ch.fetchCount,
      errorCount: ch.errorCount,
      lastFetchAt: ch.lastFetchAt,
      lastError: ch.lastError,
      consecutiveErrors: ch.consecutiveErrors,
    };
  }

  /** Get status of all channels */
  getAllChannelStatus() {
    const result = {};
    for (const [id] of this._channels) {
      result[id] = this.getChannelStatus(id);
    }
    return result;
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Lifecycle
  // ═══════════════════════════════════════════════════════════════════

  /** Start all registered channels */
  startAll() {
    this._paused = false;
    this.stats.startedAt = new Date();
    for (const [id, channel] of this._channels) {
      this._startChannel(channel);
    }
    console.info(
      `[PollingService] Started ${this._channels.size} channels`
    );
    return this;
  }

  /** Stop all channels */
  stopAll() {
    for (const [_, channel] of this._channels) {
      channel.stop();
    }
    console.info("[PollingService] All channels stopped");
    return this;
  }

  /** Pause all polling (keeps channels registered) */
  pause() {
    this._paused = true;
    for (const [_, channel] of this._channels) {
      channel.stop();
    }
    this._emit("service:paused", { timestamp: new Date() });
    return this;
  }

  /** Resume all polling */
  resume() {
    this._paused = false;
    for (const [_, channel] of this._channels) {
      this._startChannel(channel);
    }
    this._emit("service:resumed", { timestamp: new Date() });
    return this;
  }

  /** Update polling interval for a channel */
  setInterval(channelId, intervalMs) {
    const channel = this._channels.get(channelId);
    if (channel) {
      const wasRunning = channel.running;
      channel.stop();
      channel.intervalMs = intervalMs;
      if (wasRunning && !this._paused) {
        this._startChannel(channel);
      }
    }
  }

  /** Force an immediate fetch for a specific channel */
  async fetchNow(channelId) {
    const channel = this._channels.get(channelId);
    if (!channel) throw new Error(`Channel '${channelId}' not found`);
    return this._executeFetch(channel);
  }

  // ═══════════════════════════════════════════════════════════════════
  //  Internal: Channel execution
  // ═══════════════════════════════════════════════════════════════════

  _startChannel(channel) {
    if (channel.running) return;
    channel.running = true;
    channel.consecutiveErrors = 0;

    // Immediate first fetch
    if (channel.immediate) {
      this._executeFetch(channel);
    }

    // Set up interval
    channel._timerId = setInterval(() => {
      if (!this._paused) {
        this._executeFetch(channel);
      }
    }, channel.intervalMs);
  }

  async _executeFetch(channel) {
    this.stats.totalRequests++;
    channel.fetchCount++;

    try {
      const rawData = await channel.fetchFn(this.api);
      const data = channel.transform ? channel.transform(rawData) : rawData;

      channel.lastFetchAt = new Date();
      channel.lastData = data;
      channel.lastError = null;
      channel.consecutiveErrors = 0;
      this.stats.totalSuccesses++;

      // Emit data event
      this._emit(channel.id, {
        data,
        timestamp: channel.lastFetchAt,
        channelId: channel.id,
      });

      // Emit generic data-updated event
      this._emit("data:updated", {
        channelId: channel.id,
        timestamp: channel.lastFetchAt,
      });

      return data;
    } catch (err) {
      channel.errorCount++;
      channel.consecutiveErrors++;
      channel.lastError = err;
      this.stats.totalErrors++;
      this.stats.lastError = { channelId: channel.id, error: err, at: new Date() };

      // Emit error event
      this._emit("error", {
        channelId: channel.id,
        error: err,
        consecutiveErrors: channel.consecutiveErrors,
        timestamp: new Date(),
      });

      // Exponential backoff on consecutive errors
      if (channel.consecutiveErrors >= channel.maxRetries && channel.running) {
        const backoff = Math.min(
          channel.retryBackoffMs * Math.pow(2, channel.consecutiveErrors - channel.maxRetries),
          channel.maxBackoffMs
        );
        console.warn(
          `[PollingService] Channel '${channel.id}' backing off for ${backoff}ms ` +
            `(${channel.consecutiveErrors} consecutive errors)`
        );
        channel.stop();
        channel._backoffTimer = setTimeout(() => {
          if (!this._paused) {
            this._startChannel(channel);
          }
        }, backoff);
      }

      throw err;
    }
  }

  /** Destroy the service and clean up all resources */
  destroy() {
    this.stopAll();
    this._channels.clear();
    this._listeners.clear();
  }
}

/**
 * Internal: Represents a single polling channel.
 */
class PollingChannel {
  constructor(id, fetchFn, options) {
    this.id = id;
    this.fetchFn = fetchFn;
    this.intervalMs = options.intervalMs;
    this.transform = options.transform;
    this.immediate = options.immediate;
    this.maxRetries = options.maxRetries;
    this.retryBackoffMs = options.retryBackoffMs;
    this.maxBackoffMs = options.maxBackoffMs;

    // State
    this.running = false;
    this.fetchCount = 0;
    this.errorCount = 0;
    this.consecutiveErrors = 0;
    this.lastFetchAt = null;
    this.lastData = null;
    this.lastError = null;
    this._timerId = null;
    this._backoffTimer = null;
  }

  stop() {
    this.running = false;
    if (this._timerId) {
      clearInterval(this._timerId);
      this._timerId = null;
    }
    if (this._backoffTimer) {
      clearTimeout(this._backoffTimer);
      this._backoffTimer = null;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════
//  Pre-configured Polling Service Factory
// ═══════════════════════════════════════════════════════════════════════

/**
 * Create a pre-configured DataPollingService with standard dashboard channels.
 *
 * Channels:
 *   - "congestion"       : GET /api/v1/congestion (5s)
 *   - "congestion-ts"    : POST /api/v1/dynamic/query/congestion-timeseries (15s)
 *   - "dynamic-latest"   : GET /api/v1/dynamic/query/latest (5s)
 *   - "dynamic-objects"  : GET /api/v1/dynamic/objects (30s)
 *   - "static-spaces"    : GET /api/v1/static/spaces (30s)
 *   - "static-count"     : GET /api/v1/static/count (30s)
 *   - "static-types"     : GET /api/v1/static/types (60s)
 *   - "health"           : GET /health (10s)
 *
 * @param {LakehouseAPIClient} apiClient
 * @param {object} overrides - Per-channel interval overrides { channelId: intervalMs }
 * @returns {DataPollingService}
 */
function createDashboardPollingService(apiClient, overrides = {}) {
  const svc = new DataPollingService(apiClient, {
    defaultIntervalMs: 5000,
    maxRetries: 3,
    retryBackoffMs: 2000,
    maxBackoffMs: 30000,
  });

  // ── Congestion (heatmap) ──
  svc.register(
    "congestion",
    (api) => api.getCongestion(),
    {
      intervalMs: overrides.congestion || 5000,
      transform: (raw) => ({
        spaces: raw.spaces || [],
        totalObjects: raw.total_objects || 0,
        snapshotTime: raw.snapshot_time,
      }),
    }
  );

  // ── Congestion Time-Series (chart) ──
  svc.register(
    "congestion-ts",
    (api) =>
      api.getCongestionTimeseries({
        bucket_seconds: overrides.bucketSeconds || 60,
        limit: 500,
      }),
    {
      intervalMs: overrides["congestion-ts"] || 15000,
      transform: (raw) => ({
        columns: raw.columns || [],
        rows: raw.rows || [],
        rowCount: raw.row_count || 0,
      }),
    }
  );

  // ── Dynamic Objects Latest State ──
  svc.register(
    "dynamic-latest",
    (api) => api.getDynamicLatest(),
    {
      intervalMs: overrides["dynamic-latest"] || 5000,
      transform: (raw) => ({
        columns: raw.columns || [],
        rows: raw.rows || [],
        rowCount: raw.row_count || 0,
      }),
    }
  );

  // ── Dynamic Object Registry ──
  svc.register(
    "dynamic-objects",
    (api) => api.getDynamicObjects(),
    {
      intervalMs: overrides["dynamic-objects"] || 30000,
      transform: (raw) => ({
        objects: raw.objects || [],
        total: raw.total || 0,
      }),
    }
  );

  // ── Static Spaces ──
  svc.register(
    "static-spaces",
    (api) => api.getStaticSpaces(),
    {
      intervalMs: overrides["static-spaces"] || 30000,
      transform: (raw) => ({
        spaces: raw.spaces || [],
        totalSpaces: raw.total_spaces || 0,
      }),
    }
  );

  // ── Static Prim Count ──
  svc.register(
    "static-count",
    (api) => api.getStaticCount(),
    {
      intervalMs: overrides["static-count"] || 30000,
      transform: (raw) => ({
        totalCount: raw.total_count || 0,
        spaceCounts: raw.space_counts || {},
        spaceCount: raw.space_count || 0,
      }),
    }
  );

  // ── Static Type Distribution ──
  svc.register(
    "static-types",
    (api) => api.getStaticTypes(),
    {
      intervalMs: overrides["static-types"] || 60000,
      transform: (raw) => ({
        types: raw.types || [],
        totalTypes: raw.total_types || 0,
      }),
    }
  );

  // ── System Health ──
  svc.register(
    "health",
    (api) => api.getDeepHealth(),
    {
      intervalMs: overrides.health || 10000,
      transform: (raw) => ({
        status: raw.status,
        version: raw.version,
        uptime: raw.uptime_seconds,
        dependencies: raw.dependencies || {},
        timestamp: raw.timestamp,
      }),
    }
  );

  return svc;
}

// Export
if (typeof window !== "undefined") {
  window.DataPollingService = DataPollingService;
  window.createDashboardPollingService = createDashboardPollingService;
}
