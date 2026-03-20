/**
 * API client — communicates with Lakehouse API via nginx reverse proxy.
 *
 * All requests go to the same origin (nginx), which proxies /api/* to lakehouse-api.
 */

const BASE = "/api/v1";

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error");
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

/** GET /api/v1/health */
export const getHealth = () => request("/health");

/** GET /health (deep health with dependencies) */
export const getDeepHealth = () =>
  fetch("/health").then((r) => r.json());

/** POST /api/v1/query — execute ad-hoc Trino SQL */
export const executeQuery = (sql) =>
  request("/query", {
    method: "POST",
    body: JSON.stringify({ sql }),
  });

/** GET /api/v1/congestion — space congestion data */
export const getCongestion = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/congestion${qs ? `?${qs}` : ""}`);
};

/** GET /api/v1/congestion/grid — 2D grid heatmap data */
export const getCongestionGrid = (params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(`/congestion/grid${qs ? `?${qs}` : ""}`);
};

/** GET /api/v1/spaces/congestion/summary — detailed congestion summary */
export const getCongestionSummary = () =>
  request("/spaces/congestion/summary").catch(() => ({ spaces: [], total_spaces: 0 }));

/** GET /api/v1/static/spaces — list spaces */
export const getSpaces = () => request("/static/spaces").catch(() => ({ spaces: [] }));

/** GET /api/v1/static/prims?space_id=... — get prims for a space */
export const getStaticPrims = (spaceId) =>
  request(`/static/prims?space_id=${encodeURIComponent(spaceId)}`).catch(() => ({
    prims: [],
  }));

/** GET /api/v1/dynamic-objects/tables — list dynamic object tables */
export const getDynamicTables = () =>
  request("/dynamic-objects/tables").catch(() => ({ tables: [] }));

/** GET /api/v1/dynamic-objects/{table}/latest — latest sensor data */
export const getDynamicLatest = (table) =>
  request(`/dynamic-objects/${encodeURIComponent(table)}/latest`).catch(() => ({
    data: [],
  }));

/** GET /api/v1/spaces/{spaceId}/objects — per-space static + dynamic objects */
export const getSpaceObjects = (spaceId, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return request(
    `/spaces/${encodeURIComponent(spaceId)}/objects${qs ? `?${qs}` : ""}`
  ).catch(() => ({
    space_id: spaceId,
    static_objects: [],
    dynamic_objects: [],
    static_count: 0,
    dynamic_count: 0,
    total_count: 0,
  }));
};

/** GET /api/v1/congestion/timeseries — congestion time-series data */
export const getCongestionTimeseries = (params = {}) => {
  const qs = new URLSearchParams();
  if (params.space_id) qs.set("space_id", params.space_id);
  if (params.start_time) qs.set("start_time", params.start_time);
  if (params.end_time) qs.set("end_time", params.end_time);
  if (params.bucket_seconds) qs.set("bucket_seconds", String(params.bucket_seconds));
  if (params.limit) qs.set("limit", String(params.limit));
  const q = qs.toString();
  return request(`/congestion/timeseries${q ? `?${q}` : ""}`);
};
