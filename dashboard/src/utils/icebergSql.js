/**
 * Iceberg SQL template helpers.
 * All Iceberg operations are executed via Trino SQL through the existing /api/v1/query endpoint.
 */

// ── Input Validation ─────────────────────────────────────────────
function validateTableId(table) {
  if (!/^[a-zA-Z_][a-zA-Z0-9_."]*$/.test(table)) {
    throw new Error(`Invalid table identifier: ${table}`);
  }
  return table;
}

function validateTimestamp(ts) {
  if (!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}/.test(ts)) {
    throw new Error(`Invalid timestamp: ${ts}`);
  }
  return ts;
}

function validateIdentifier(name) {
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(name)) {
    throw new Error(`Invalid identifier: ${name}`);
  }
  return name;
}

function validateNumber(val) {
  if (!Number.isFinite(Number(val))) {
    throw new Error(`Invalid number: ${val}`);
  }
  return val;
}

// ── Catalog / Namespace Discovery ────────────────────────────────
export const listCatalogs = () => `SHOW CATALOGS`;
export const listSchemas = (catalog = "polaris") => `SHOW SCHEMAS FROM ${validateIdentifier(catalog)}`;
export const listTables = (schema, catalog = "polaris") => `SHOW TABLES FROM ${validateIdentifier(catalog)}.${validateIdentifier(schema)}`;
export const describeTable = (table) => `DESCRIBE ${validateTableId(table)}`;
export const showCreateTable = (table) => `SHOW CREATE TABLE ${validateTableId(table)}`;

// ── Time Travel ──────────────────────────────────────────────────
export const timeTravelQuery = (table, timestamp) =>
  `SELECT * FROM ${validateTableId(table)} FOR TIMESTAMP AS OF TIMESTAMP '${validateTimestamp(timestamp)}' LIMIT 100`;

export const snapshotTravelQuery = (table, snapshotId) =>
  `SELECT * FROM ${validateTableId(table)} FOR VERSION AS OF ${validateNumber(snapshotId)} LIMIT 100`;

// ── Metadata Tables ──────────────────────────────────────────────
// Trino requires: iceberg.schema."table$meta" (only table name + $suffix in quotes)
function metaTable(table, suffix) {
  validateTableId(table);
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
  `ALTER TABLE ${validateTableId(table)} EXECUTE optimize`;

export const compactWithSize = (table, sizeMB) =>
  `ALTER TABLE ${validateTableId(table)} EXECUTE optimize(file_size_threshold => '${validateNumber(sizeMB)}MB')`;

// ── Schema Evolution ─────────────────────────────────────────────
export const addColumn = (table, name, type) =>
  `ALTER TABLE ${validateTableId(table)} ADD COLUMN ${validateIdentifier(name)} ${validateIdentifier(type)}`;

export const dropColumn = (table, name) =>
  `ALTER TABLE ${validateTableId(table)} DROP COLUMN ${validateIdentifier(name)}`;

export const renameColumn = (table, oldName, newName) =>
  `ALTER TABLE ${validateTableId(table)} RENAME COLUMN ${validateIdentifier(oldName)} TO ${validateIdentifier(newName)}`;

// ── Snapshot Maintenance ─────────────────────────────────────────
export const expireSnapshots = (table, retention) =>
  `ALTER TABLE ${validateTableId(table)} EXECUTE expire_snapshots(retention_threshold => '${validateIdentifier(retention)}')`;

// ── COW / MOR ────────────────────────────────────────────────────
export const setWriteMode = (table, mode) =>
  `ALTER TABLE ${validateTableId(table)} SET PROPERTIES write_delete_mode = '${validateIdentifier(mode)}'`;

// ── Sorting ──────────────────────────────────────────────────────
export const setSortOrder = (table, columns) =>
  `ALTER TABLE ${validateTableId(table)} SET PROPERTIES sorted_by = ARRAY[${columns.map(c => `'${validateIdentifier(c)}'`).join(", ")}]`;

// ── Partition Evolution ──────────────────────────────────────────
export const setPartitioning = (table, specs) =>
  `ALTER TABLE ${validateTableId(table)} SET PROPERTIES partitioning = ARRAY[${specs.map(s => `'${validateIdentifier(s)}'`).join(", ")}]`;

// ── File size ────────────────────────────────────────────────────
export const setTargetFileSize = (table, bytes) =>
  `ALTER TABLE ${validateTableId(table)} SET PROPERTIES target_max_file_size = '${validateNumber(bytes)}'`;

// ── Helpers ──────────────────────────────────────────────────────
export const countRows = (table) => `SELECT COUNT(*) AS row_count FROM ${validateTableId(table)}`;

/** Format bytes to human-readable */
export function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}
