import React, { useState } from "react";
import { executeQuery } from "../api.js";

/**
 * QueryPanel — Ad-hoc Trino SQL query interface.
 */

const PRESET_GROUPS = [
  {
    group: "Discovery",
    presets: [
      {
        label: "Show Catalogs",
        sql: "SHOW CATALOGS",
      },
      {
        label: "Show Namespaces",
        sql: "SHOW SCHEMAS FROM polaris",
      },
      {
        label: "Show Tables (netai)",
        sql: "SHOW TABLES FROM polaris.netai",
      },
      {
        label: "Describe entities",
        sql: "DESCRIBE polaris.netai.entities",
      },
      {
        label: "Describe prim_snapshots",
        sql: "DESCRIBE polaris.netai.prim_snapshots",
      },
      {
        label: "Describe raw_backup_files",
        sql: "DESCRIBE polaris.netai.raw_backup_files",
      },
      {
        label: "Describe simulation_sessions",
        sql: "DESCRIBE polaris.netai.simulation_sessions",
      },
      {
        label: "Describe simulation_deltas",
        sql: "DESCRIBE polaris.netai.simulation_deltas",
      },
      {
        label: "Describe simulation_keyframes",
        sql: "DESCRIBE polaris.netai.simulation_keyframes",
      },
    ],
  },
  {
    group: "Data Preview",
    presets: [
      {
        label: "Entities (latest 50)",
        sql: "SELECT entity_id, entity_path, entity_hash, backup_time\nFROM polaris.netai.entities\nORDER BY backup_time DESC\nLIMIT 50",
      },
      {
        label: "Prim Snapshots (latest 50)",
        sql: "SELECT entity_path, relative_path, prim_type, prim_hash, backup_time\nFROM polaris.netai.prim_snapshots\nORDER BY backup_time DESC\nLIMIT 50",
      },
      {
        label: "Raw Backup Files (latest 50)",
        sql: "SELECT file_path, file_name, file_size, status, backup_time\nFROM polaris.netai.raw_backup_files\nORDER BY backup_time DESC\nLIMIT 50",
      },
      {
        label: "Simulation Sessions",
        sql: "SELECT simulation_id, scene_path, start_time, end_time, total_deltas, entity_count, status\nFROM polaris.netai.simulation_sessions\nORDER BY start_time DESC\nLIMIT 50",
      },
      {
        label: "Simulation Deltas (latest 50)",
        sql: "SELECT capture_time, simulation_id, prim_path, property_name, delta_type, capture_source\nFROM polaris.netai.simulation_deltas\nORDER BY capture_time DESC\nLIMIT 50",
      },
      {
        label: "Simulation Keyframes (latest 50)",
        sql: "SELECT keyframe_id, simulation_id, sim_step, entity_id, keyframe_time\nFROM polaris.netai.simulation_keyframes\nORDER BY keyframe_time DESC\nLIMIT 50",
      },
    ],
  },
  {
    group: "Analytics",
    presets: [
      {
        label: "Backup Timeline",
        sql: "SELECT backup_time,\n       COUNT(DISTINCT entity_id) AS entity_count,\n       COUNT(*) AS total_records\nFROM polaris.netai.entities\nGROUP BY backup_time\nORDER BY backup_time DESC",
      },
      {
        label: "Entity Change Frequency",
        sql: "SELECT entity_path,\n       COUNT(DISTINCT entity_hash) AS unique_versions,\n       COUNT(*) AS backup_count,\n       MIN(backup_time) AS first_seen,\n       MAX(backup_time) AS last_seen\nFROM polaris.netai.entities\nGROUP BY entity_path\nORDER BY unique_versions DESC\nLIMIT 20",
      },
      {
        label: "Prim Type Distribution",
        sql: "SELECT prim_type,\n       COUNT(*) AS prim_count,\n       COUNT(DISTINCT entity_path) AS entity_count\nFROM polaris.netai.prim_snapshots\nGROUP BY prim_type\nORDER BY prim_count DESC",
      },
      {
        label: "Raw Backup Size by Time",
        sql: "SELECT backup_time,\n       COUNT(*) AS file_count,\n       SUM(file_size) AS total_bytes\nFROM polaris.netai.raw_backup_files\nGROUP BY backup_time\nORDER BY backup_time DESC",
      },
      {
        label: "File Extension Distribution",
        sql: "SELECT file_extension,\n       COUNT(*) AS file_count,\n       SUM(file_size) AS total_bytes\nFROM polaris.netai.raw_backup_files\nGROUP BY file_extension\nORDER BY total_bytes DESC",
      },
    ],
  },
  {
    group: "Iceberg Metadata",
    presets: [
      {
        label: "Snapshot History",
        sql: 'SELECT snapshot_id, parent_id, operation, committed_at, summary\nFROM polaris.netai."entities$snapshots"\nORDER BY committed_at DESC',
      },
      {
        label: "Data Files (Parquet)",
        sql: 'SELECT file_path, file_format, record_count, file_size_in_bytes\nFROM polaris.netai."entities$files"',
      },
      {
        label: "Active History",
        sql: 'SELECT * FROM polaris.netai."entities$history"',
      },
      {
        label: "Partitions",
        sql: 'SELECT * FROM polaris.netai."entities$partitions"',
      },
      {
        label: "Manifests",
        sql: 'SELECT path, length, added_data_files_count, added_rows_count\nFROM polaris.netai."entities$manifests"',
      },
    ],
  },
  {
    group: "Time Travel",
    presets: [
      {
        label: "By Timestamp",
        sql: "SELECT * FROM polaris.netai.entities\nFOR TIMESTAMP AS OF TIMESTAMP '2026-03-31 15:31:07'\nLIMIT 50",
      },
      {
        label: "By Snapshot ID",
        sql: "SELECT * FROM polaris.netai.entities\nFOR VERSION AS OF 7604719568992131136\nLIMIT 50",
      },
    ],
  },
  {
    group: "Maintenance",
    warn: true,
    presets: [
      {
        label: "Expire Snapshots (7d)",
        sql: "ALTER TABLE polaris.netai.entities\nEXECUTE expire_snapshots(retention_threshold => '7d')",
      },
      {
        label: "Optimize (Compaction)",
        sql: "ALTER TABLE polaris.netai.entities EXECUTE optimize",
      },
      {
        label: "Optimize (128MB)",
        sql: "ALTER TABLE polaris.netai.entities\nEXECUTE optimize(file_size_threshold => '128MB')",
      },
      {
        label: "Remove Orphan Files",
        sql: "ALTER TABLE polaris.netai.entities\nEXECUTE remove_orphan_files(retention_threshold => '7d')",
      },
    ],
  },
  {
    group: "Schema Evolution",
    warn: true,
    presets: [
      {
        label: "Add Column",
        sql: "ALTER TABLE polaris.netai.entities ADD COLUMN new_col varchar",
      },
      {
        label: "Drop Column",
        sql: "ALTER TABLE polaris.netai.entities DROP COLUMN new_col",
      },
      {
        label: "Rename Column",
        sql: "ALTER TABLE polaris.netai.entities RENAME COLUMN old_name TO new_name",
      },
    ],
  },
  {
    group: "Table Properties",
    warn: true,
    presets: [
      {
        label: "Partition Evolution",
        sql: "ALTER TABLE polaris.netai.entities\nSET PROPERTIES partitioning = ARRAY['day(backup_time)', 'bucket(entity_path, 8)']",
      },
      {
        label: "Write Mode (MoR)",
        sql: "ALTER TABLE polaris.netai.entities\nSET PROPERTIES write_delete_mode = 'merge-on-read'",
      },
      {
        label: "Sort Order",
        sql: "ALTER TABLE polaris.netai.entities\nSET PROPERTIES sorted_by = ARRAY['backup_time']",
      },
    ],
  },
  {
    group: "Clear Data",
    warn: true,
    presets: [
      {
        label: "Clear entities",
        sql: "DELETE FROM polaris.netai.entities",
      },
      {
        label: "Clear prim_snapshots",
        sql: "DELETE FROM polaris.netai.prim_snapshots",
      },
      {
        label: "Clear raw_backup_files",
        sql: "DELETE FROM polaris.netai.raw_backup_files",
      },
      {
        label: "Clear simulation_sessions",
        sql: "DELETE FROM polaris.netai.simulation_sessions",
      },
      {
        label: "Clear simulation_deltas",
        sql: "DELETE FROM polaris.netai.simulation_deltas",
      },
      {
        label: "Clear simulation_keyframes",
        sql: "DELETE FROM polaris.netai.simulation_keyframes",
      },
    ],
  },
  {
    group: "DDL",
    warn: true,
    presets: [
      {
        label: "Create Namespace",
        sql: "CREATE SCHEMA IF NOT EXISTS polaris.my_new_db",
      },
      {
        label: "Drop Table (legacy)",
        sql: "DROP TABLE IF EXISTS polaris.netai.static_prims",
      },
    ],
  },
];

export default function QueryPanel() {
  const [sql, setSql] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [elapsed, setElapsed] = useState(null);

  const runQuery = async () => {
    if (!sql.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    const t0 = performance.now();
    try {
      const res = await executeQuery(sql.trim());
      setElapsed(Math.round(performance.now() - t0));
      setResult(res);
    } catch (err) {
      setElapsed(Math.round(performance.now() - t0));
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  };

  const rows = result?.rows || result?.data || [];
  const columns = result?.columns || [];

  return (
    <div>
      <h2 style={{ fontSize: "1.1rem", marginBottom: "1rem" }}>
        Trino SQL Query
      </h2>

      <div className="card" style={{ marginBottom: "1rem" }}>
        {PRESET_GROUPS.map((g) => (
          <div key={g.group} style={{ marginBottom: "0.75rem" }}>
            <div
              style={{
                fontSize: "0.65rem",
                fontWeight: 600,
                color: g.warn ? "var(--warning, #e6a817)" : "var(--text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                marginBottom: "0.35rem",
              }}
            >
              {g.warn ? "\u26A0 " : ""}{g.group}
            </div>
            <div
              style={{
                display: "flex",
                gap: "0.4rem",
                flexWrap: "wrap",
              }}
            >
              {g.presets.map((q) => (
                <button
                  key={q.label}
                  className="btn"
                  style={{
                    fontSize: "0.7rem",
                    ...(g.warn && {
                      borderColor: "rgba(230, 168, 23, 0.3)",
                      color: "var(--warning, #e6a817)",
                    }),
                  }}
                  onClick={() => setSql(q.sql)}
                >
                  {q.label}
                </button>
              ))}
            </div>
          </div>
        ))}

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="SELECT * FROM polaris.netai.entities LIMIT 10"
          style={{
            width: "100%",
            minHeight: "100px",
            padding: "0.75rem",
            background: "var(--bg-primary)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            color: "var(--text-primary)",
            fontFamily: "'Cascadia Code', 'Fira Code', monospace",
            fontSize: "0.85rem",
            resize: "vertical",
          }}
        />

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1rem",
            marginTop: "0.75rem",
          }}
        >
          <button
            className="btn btn-primary"
            onClick={runQuery}
            disabled={loading || !sql.trim()}
          >
            {loading ? "Executing..." : "Run Query (Ctrl+Enter)"}
          </button>
          {elapsed != null && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              {elapsed}ms
              {rows.length > 0 && ` \u2022 ${rows.length} rows`}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="card" style={{ borderColor: "var(--danger)" }}>
          <div className="error-msg">{error}</div>
        </div>
      )}

      {rows.length > 0 && (
        <div className="card">
          <div className="card-title">
            Results ({rows.length} row{rows.length !== 1 ? "s" : ""})
          </div>
          <div style={{ overflowX: "auto", maxHeight: "500px", overflowY: "auto" }}>
            <table className="data-table">
              <thead>
                <tr>
                  {columns.length > 0
                    ? columns.map((c, i) => <th key={i}>{c}</th>)
                    : typeof rows[0] === "object" && !Array.isArray(rows[0])
                    ? Object.keys(rows[0]).map((k) => <th key={k}>{k}</th>)
                    : Array.isArray(rows[0])
                    ? rows[0].map((_, i) => <th key={i}>col_{i}</th>)
                    : null}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri}>
                    {typeof row === "object" && !Array.isArray(row)
                      ? Object.values(row).map((v, ci) => (
                          <td key={ci} style={{ fontSize: "0.75rem", fontFamily: "monospace" }}>
                            {v == null ? "NULL" : String(v)}
                          </td>
                        ))
                      : Array.isArray(row)
                      ? row.map((v, ci) => (
                          <td key={ci} style={{ fontSize: "0.75rem", fontFamily: "monospace" }}>
                            {v == null ? "NULL" : String(v)}
                          </td>
                        ))
                      : (
                          <td style={{ fontSize: "0.75rem", fontFamily: "monospace" }}>
                            {String(row)}
                          </td>
                        )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
