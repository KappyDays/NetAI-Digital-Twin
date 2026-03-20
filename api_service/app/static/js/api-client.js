/**
 * Lakehouse API Client
 *
 * Central HTTP client for all FastAPI endpoints.
 * Handles fetch requests, error handling, and response normalization.
 * Used by the DataPollingService and dashboard components.
 *
 * Design: Pure ES module, no external dependencies (browser-native fetch).
 */

class LakehouseAPIClient {
  /**
   * @param {string} baseUrl - API base URL (e.g., "" for same-origin, "http://localhost:8000")
   * @param {number} timeoutMs - Default request timeout in milliseconds
   */
  constructor(baseUrl = "", timeoutMs = 15000) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.timeoutMs = timeoutMs;
    this._requestId = 0;
  }

  // ─────────────────────────────────────────────────────────────────
  //  Low-level fetch wrapper
  // ─────────────────────────────────────────────────────────────────

  /**
   * Execute an HTTP request with timeout and error normalization.
   * @param {string} path - API path (e.g., "/api/v1/congestion")
   * @param {object} options - fetch options override
   * @returns {Promise<object>} Parsed JSON response
   */
  async request(path, options = {}) {
    const url = `${this.baseUrl}${path}`;
    const reqId = ++this._requestId;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || this.timeoutMs);

    const fetchOptions = {
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      signal: controller.signal,
      ...options,
    };

    try {
      const response = await fetch(url, fetchOptions);
      clearTimeout(timeout);

      if (!response.ok) {
        const errorBody = await response.text().catch(() => "");
        let detail = errorBody;
        try {
          const parsed = JSON.parse(errorBody);
          detail = parsed.detail || errorBody;
        } catch (_) {}
        throw new APIError(response.status, detail, url);
      }

      return await response.json();
    } catch (err) {
      clearTimeout(timeout);
      if (err instanceof APIError) throw err;
      if (err.name === "AbortError") {
        throw new APIError(408, `Request timeout after ${this.timeoutMs}ms`, url);
      }
      throw new APIError(0, err.message || "Network error", url);
    }
  }

  /** GET request helper */
  async get(path, params = {}) {
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(params).filter(([_, v]) => v != null))
    ).toString();
    const fullPath = qs ? `${path}?${qs}` : path;
    return this.request(fullPath, { method: "GET" });
  }

  /** POST request helper */
  async post(path, body = {}) {
    return this.request(path, { method: "POST", body: JSON.stringify(body) });
  }

  // ─────────────────────────────────────────────────────────────────
  //  Health & System
  // ─────────────────────────────────────────────────────────────────

  /** GET /api/v1/health - lightweight health check */
  async getHealth() {
    return this.get("/api/v1/health");
  }

  /** GET /health - deep health check with dependency status */
  async getDeepHealth() {
    return this.get("/health");
  }

  // ─────────────────────────────────────────────────────────────────
  //  Congestion (Heatmap / Overview)
  // ─────────────────────────────────────────────────────────────────

  /** GET /api/v1/congestion - current space congestion snapshot */
  async getCongestion() {
    return this.get("/api/v1/congestion");
  }

  /**
   * POST /api/v1/dynamic/query/congestion-timeseries
   * @param {object} params - { space_id?, start_time?, end_time?, bucket_seconds?, limit? }
   */
  async getCongestionTimeseries(params = {}) {
    return this.post("/api/v1/dynamic/query/congestion-timeseries", params);
  }

  // ─────────────────────────────────────────────────────────────────
  //  Static Objects
  // ─────────────────────────────────────────────────────────────────

  /** GET /api/v1/static/spaces - list all spaces with metadata */
  async getStaticSpaces() {
    return this.get("/api/v1/static/spaces");
  }

  /** GET /api/v1/static/count - total and per-space prim counts */
  async getStaticCount() {
    return this.get("/api/v1/static/count");
  }

  /** GET /api/v1/static/types - prim type distribution */
  async getStaticTypes(spaceId = null) {
    return this.get("/api/v1/static/types", { space_id: spaceId });
  }

  /** GET /api/v1/static/prims - query static prims */
  async getStaticPrims(params = {}) {
    return this.get("/api/v1/static/prims", params);
  }

  // ─────────────────────────────────────────────────────────────────
  //  Dynamic Objects
  // ─────────────────────────────────────────────────────────────────

  /** GET /api/v1/dynamic/objects - list all dynamic objects */
  async getDynamicObjects() {
    return this.get("/api/v1/dynamic/objects");
  }

  /** GET /api/v1/dynamic/query/latest - latest state of all/specific objects */
  async getDynamicLatest(objectId = null) {
    return this.get("/api/v1/dynamic/query/latest", { object_id: objectId });
  }

  /**
   * POST /api/v1/dynamic/query/time-range
   * @param {object} params - { object_id, start_time, end_time, limit?, order? }
   */
  async getDynamicTimeRange(params) {
    return this.post("/api/v1/dynamic/query/time-range", params);
  }

  /**
   * POST /api/v1/dynamic/query/trajectory
   * @param {object} params - { object_id, start_time, end_time, sample_interval_seconds?, limit? }
   */
  async getDynamicTrajectory(params) {
    return this.post("/api/v1/dynamic/query/trajectory", params);
  }

  /**
   * POST /api/v1/dynamic/query/by-space
   * @param {object} params - { space_id, start_time?, end_time?, limit? }
   */
  async getDynamicBySpace(params) {
    return this.post("/api/v1/dynamic/query/by-space", params);
  }

  /**
   * POST /api/v1/dynamic/query/spatial-range
   * @param {object} params - { x_min, x_max, y_min, y_max, z_min?, z_max?, ... }
   */
  async getDynamicSpatialRange(params) {
    return this.post("/api/v1/dynamic/query/spatial-range", params);
  }

  // ─────────────────────────────────────────────────────────────────
  //  Ad-hoc Query
  // ─────────────────────────────────────────────────────────────────

  /** POST /api/v1/query - execute arbitrary Trino SQL */
  async executeQuery(sql) {
    return this.post("/api/v1/query", { sql });
  }
}

/**
 * Custom API error with HTTP status code and request URL.
 */
class APIError extends Error {
  constructor(status, detail, url) {
    super(`API Error ${status}: ${detail}`);
    this.name = "APIError";
    this.status = status;
    this.detail = detail;
    this.url = url;
  }
}

// Export for module usage and global access
if (typeof window !== "undefined") {
  window.LakehouseAPIClient = LakehouseAPIClient;
  window.APIError = APIError;
}
