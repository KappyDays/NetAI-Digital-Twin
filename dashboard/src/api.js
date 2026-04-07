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

// ── Entity Backup ────────────────────────────────────────────────

/** GET /api/v1/entities/backup-times */
export const getEntityBackupTimes = () => request("/entities/backup-times");

/** GET /api/v1/entities/list?backup_time=... */
export const getEntityList = (backupTime) =>
  request(`/entities/list?backup_time=${encodeURIComponent(backupTime)}`);

/** GET /api/v1/entities/diff?time_a=...&time_b=... */
export const getEntityDiff = (timeA, timeB) => {
  const qs = new URLSearchParams({ time_a: timeA, time_b: timeB });
  return request(`/entities/diff?${qs}`);
};

/** GET /api/v1/entities/{path}/prim-diff?time_a=...&time_b=... */
export const getPrimDiff = (entityPath, timeA, timeB) => {
  const safePath = entityPath.startsWith("/") ? entityPath.slice(1) : entityPath;
  const qs = new URLSearchParams({ time_a: timeA, time_b: timeB });
  return request(`/entities/${safePath}/prim-diff?${qs}`);
};

// ── Raw Backup ───────────────────────────────────────────────────

/** GET /api/v1/raw-backup/times */
export const getRawBackupTimes = () => request("/raw-backup/times");

/** GET /api/v1/raw-backup/list?backup_time=... */
export const getRawBackupList = (backupTime) =>
  request(`/raw-backup/list?backup_time=${encodeURIComponent(backupTime)}`);

/** GET /api/v1/raw-backup/diff?time_a=...&time_b=... */
export const getRawBackupDiff = (timeA, timeB) => {
  const qs = new URLSearchParams({ time_a: timeA, time_b: timeB });
  return request(`/raw-backup/diff?${qs}`);
};

