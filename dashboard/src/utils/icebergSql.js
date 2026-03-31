/**
 * Iceberg SQL template helpers.
 * All Iceberg operations are executed via Trino SQL through the existing /api/v1/query endpoint.
 */

// ── Table Discovery ──────────────────────────────────────────────
export const listSchemas = () => `SHOW SCHEMAS FROM iceberg`;
export const listTables = (schema) => `SHOW TABLES FROM iceberg.${schema}`;
export const describeTable = (table) => `DESCRIBE ${table}`;
export const showCreateTable = (table) => `SHOW CREATE TABLE ${table}`;

// ── Time Travel ──────────────────────────────────────────────────
export const timeTravelQuery = (table, timestamp) =>
  `SELECT * FROM ${table} FOR TIMESTAMP AS OF TIMESTAMP '${timestamp}' LIMIT 100`;

export const snapshotTravelQuery = (table, snapshotId) =>
  `SELECT * FROM ${table} FOR VERSION AS OF ${snapshotId} LIMIT 100`;

// ── Metadata Tables ──────────────────────────────────────────────
// Trino requires: iceberg.schema."table$meta" (only table name + $suffix in quotes)
function metaTable(table, suffix) {
  const parts = table.split(".");
  const tbl = parts.pop();
  return parts.join(".") + `.\"${tbl}$${suffix}\"`;
}

export const snapshotsQuery = (table) =>
  `SELECT snapshot_id, parent_id, operation, committed_at, summary FROM ${metaTable(table, "snapshots")} ORDER BY committed_at DESC`;

export const historyQuery = (table) =>
  `SELECT * FROM ${metaTable(table, "history")}`;

export const filesQuery = (table) =>
  `SELECT file_path, file_format, record_count, file_size_in_bytes FROM ${metaTable(table, "files")}`;

export const partitionsQuery = (table) =>
  `SELECT * FROM ${metaTable(table, "partitions")}`;

export const manifestsQuery = (table) =>
  `SELECT path, length, added_snapshot_id, added_data_files_count, added_rows_count FROM ${metaTable(table, "manifests")}`;

// ── Compaction ───────────────────────────────────────────────────
export const compactQuery = (table) =>
  `ALTER TABLE ${table} EXECUTE optimize`;

export const compactWithSize = (table, sizeMB) =>
  `ALTER TABLE ${table} EXECUTE optimize(file_size_threshold => '${sizeMB}MB')`;

// ── Schema Evolution ─────────────────────────────────────────────
export const addColumn = (table, name, type) =>
  `ALTER TABLE ${table} ADD COLUMN ${name} ${type}`;

export const dropColumn = (table, name) =>
  `ALTER TABLE ${table} DROP COLUMN ${name}`;

export const renameColumn = (table, oldName, newName) =>
  `ALTER TABLE ${table} RENAME COLUMN ${oldName} TO ${newName}`;

// ── Snapshot Maintenance ─────────────────────────────────────────
export const expireSnapshots = (table, retention) =>
  `ALTER TABLE ${table} EXECUTE expire_snapshots(retention_threshold => '${retention}')`;

// ── COW / MOR ────────────────────────────────────────────────────
export const setWriteMode = (table, mode) =>
  `ALTER TABLE ${table} SET PROPERTIES write_delete_mode = '${mode}'`;

// ── Sorting ──────────────────────────────────────────────────────
export const setSortOrder = (table, columns) =>
  `ALTER TABLE ${table} SET PROPERTIES sorted_by = ARRAY[${columns.map(c => `'${c}'`).join(", ")}]`;

// ── Partition Evolution ──────────────────────────────────────────
export const setPartitioning = (table, specs) =>
  `ALTER TABLE ${table} SET PROPERTIES partitioning = ARRAY[${specs.map(s => `'${s}'`).join(", ")}]`;

// ── File size ────────────────────────────────────────────────────
export const setTargetFileSize = (table, bytes) =>
  `ALTER TABLE ${table} SET PROPERTIES target_max_file_size = '${bytes}'`;

// ── Helpers ──────────────────────────────────────────────────────
export const countRows = (table) => `SELECT COUNT(*) AS row_count FROM ${table}`;

/** Format bytes to human-readable */
export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}
