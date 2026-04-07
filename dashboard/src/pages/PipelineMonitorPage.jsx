import React, { useState, useCallback } from "react";
import { executeQuery } from "../api.js";

/**
 * PipelineMonitorPage — Quick view of all 6 Iceberg tables organized by Task.
 *
 * Task 1: raw_backup_files
 * Task 2: entities, prim_snapshots
 * Task 3: simulation_sessions, simulation_deltas, simulation_keyframes
 *
 * NOTE: Trino catalog name is "polaris" (trino/catalog/polaris.properties). SQL must use polaris.netai.*
 */

const TABLES = {
  task1: [
    {
      id: "raw_backup_files",
      label: "raw_backup_files",
      sql: "SELECT * FROM polaris.netai.raw_backup_files ORDER BY backup_time DESC LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.raw_backup_files",
      s3KeyCol: "s3_key",
    },
  ],
  task2: [
    {
      id: "entities",
      label: "entities",
      sql: "SELECT * FROM polaris.netai.entities ORDER BY backup_time DESC LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.entities",
    },
    {
      id: "prim_snapshots",
      label: "prim_snapshots",
      sql: "SELECT * FROM polaris.netai.prim_snapshots ORDER BY backup_time DESC LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.prim_snapshots",
    },
  ],
  task3: [
    {
      id: "simulation_sessions",
      label: "simulation_sessions",
      sql: "SELECT * FROM polaris.netai.simulation_sessions ORDER BY start_time DESC LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.simulation_sessions",
    },
    {
      id: "simulation_deltas",
      label: "simulation_deltas",
      sql: "SELECT * FROM polaris.netai.simulation_deltas LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.simulation_deltas",
    },
    {
      id: "simulation_keyframes",
      label: "simulation_keyframes",
      sql: "SELECT * FROM polaris.netai.simulation_keyframes ORDER BY keyframe_time DESC LIMIT 50",
      deleteSql: "DELETE FROM polaris.netai.simulation_keyframes",
    },
  ],
};

const TASK_META = [
  { key: "task1", title: "Task 1 — Raw Backup", color: "#7ecfff" },
  { key: "task2", title: "Task 2 — Entity Backup", color: "#b5ead7" },
  { key: "task3", title: "Task 3 — Simulation (M&S)", color: "#ffd6a5" },
];

/* ── TableSection ─────────────────────────────────────── */

function TableSection({ table }) {
  const [state, setState] = useState({
    rows: null,
    columns: null,
    loading: false,
    error: null,
  });
  // delete confirm state: "idle" | "confirm" | "deleting"
  const [deleteState, setDeleteState] = useState("idle");

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await executeQuery(table.sql);
      const rawRows = data.rows || data.data || [];
      const columns = data.columns || [];
      const rows = rawRows.map((row) =>
        Array.isArray(row)
          ? Object.fromEntries(columns.map((col, i) => [col, row[i]]))
          : row
      );
      setState({ rows, columns, loading: false, error: null });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e.message }));
    }
  }, [table.sql]);

  const handleDeleteClick = useCallback(() => {
    if (deleteState === "idle") {
      setDeleteState("confirm");
      // Auto-reset confirm after 3 s
      setTimeout(() => setDeleteState((s) => (s === "confirm" ? "idle" : s)), 3000);
    } else if (deleteState === "confirm") {
      runDelete();
    }
  }, [deleteState]);

  const runDelete = async () => {
    setDeleteState("deleting");
    setState((s) => ({ ...s, error: null }));
    try {
      await executeQuery(table.deleteSql);
      // Reload to reflect empty table
      setState((s) => ({ ...s, loading: true }));
      const data = await executeQuery(table.sql);
      const rawRows = data.rows || data.data || [];
      const columns = data.columns || [];
      const rows = rawRows.map((row) =>
        Array.isArray(row)
          ? Object.fromEntries(columns.map((col, i) => [col, row[i]]))
          : row
      );
      setState({ rows, columns, loading: false, error: null });
    } catch (e) {
      setState((s) => ({ ...s, loading: false, error: e.message }));
    } finally {
      setDeleteState("idle");
    }
  };

  const { rows, columns, loading, error } = state;

  const deleteLabel =
    deleteState === "confirm"
      ? "Confirm?"
      : deleteState === "deleting"
      ? "Deleting…"
      : "Delete";

  const deleteColor =
    deleteState === "confirm" ? "#c97f00" : "#7a1f1f";

  const deleteBg =
    deleteState === "confirm" ? "#3d2800" : "#2a1a1a";

  return (
    <div
      style={{
        marginBottom: "24px",
        background: "#1e1e2e",
        borderRadius: "8px",
        padding: "16px",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "8px",
          marginBottom: "12px",
          flexWrap: "wrap",
        }}
      >
        <span
          style={{
            color: "#e0e0e0",
            fontFamily: "monospace",
            fontSize: "14px",
            fontWeight: "bold",
            flex: 1,
            minWidth: 0,
          }}
        >
          polaris.netai.{table.label}
        </span>

        {/* Load / Reload */}
        <button
          onClick={load}
          disabled={loading || deleteState === "deleting"}
          style={{
            background: loading ? "#333" : "#4a6fa5",
            color: "#fff",
            border: "none",
            borderRadius: "4px",
            padding: "4px 14px",
            cursor: loading || deleteState === "deleting" ? "not-allowed" : "pointer",
            fontSize: "12px",
            opacity: loading || deleteState === "deleting" ? 0.6 : 1,
          }}
        >
          {loading ? "Loading…" : rows !== null ? "Reload" : "Load"}
        </button>

        {/* Delete */}
        <button
          onClick={handleDeleteClick}
          disabled={deleteState === "deleting" || loading}
          style={{
            background: deleteBg,
            color: deleteState === "confirm" ? "#ffc04d" : "#ff6b6b",
            border: `1px solid ${deleteColor}`,
            borderRadius: "4px",
            padding: "4px 14px",
            cursor: deleteState === "deleting" || loading ? "not-allowed" : "pointer",
            fontSize: "12px",
            fontWeight: deleteState === "confirm" ? "bold" : "normal",
            transition: "all 0.2s",
            opacity: loading ? 0.5 : 1,
          }}
          title={
            deleteState === "idle"
              ? "테이블의 모든 행을 삭제합니다"
              : deleteState === "confirm"
              ? "다시 클릭하면 삭제를 실행합니다 (3초 내)"
              : "삭제 중…"
          }
        >
          {deleteLabel}
        </button>

        {rows !== null && !loading && (
          <span style={{ color: "#888", fontSize: "12px" }}>
            {rows.length} rows
          </span>
        )}
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            color: "#ff6b6b",
            fontSize: "12px",
            padding: "8px",
            background: "#2a1a1a",
            borderRadius: "4px",
            marginBottom: "8px",
            wordBreak: "break-all",
          }}
        >
          {error}
        </div>
      )}

      {/* Data table */}
      {rows !== null && columns.length > 0 && (
        <div style={{ overflowX: "auto", maxHeight: "320px", overflowY: "auto" }}>
          <table
            style={{
              borderCollapse: "collapse",
              width: "100%",
              fontSize: "12px",
              fontFamily: "monospace",
            }}
          >
            <thead>
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    style={{
                      position: "sticky",
                      top: 0,
                      background: "#2a2a3e",
                      color: "#aaa",
                      padding: "6px 10px",
                      textAlign: "left",
                      whiteSpace: "nowrap",
                      borderBottom: "1px solid #444",
                      zIndex: 1,
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr
                  key={ri}
                  style={{ background: ri % 2 === 0 ? "transparent" : "#1a1a2a" }}
                >
                  {columns.map((col) => {
                    const val = row[col];
                    const isS3Key =
                      table.s3KeyCol && col === table.s3KeyCol && val;
                    return (
                      <td
                        key={col}
                        style={{
                          padding: "5px 10px",
                          color: "#ccc",
                          borderBottom: "1px solid #2a2a3a",
                          whiteSpace: "nowrap",
                          maxWidth: "300px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                        }}
                        title={val != null ? String(val) : ""}
                      >
                        {isS3Key ? (
                          <a
                            href={`http://localhost:9001/browser/warehouse2/${val}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ color: "#7ecfff", textDecoration: "none" }}
                          >
                            {val}
                          </a>
                        ) : val == null ? (
                          <span style={{ color: "#555" }}>null</span>
                        ) : (
                          String(val)
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rows !== null && rows.length === 0 && !loading && (
        <div style={{ color: "#666", fontSize: "13px", padding: "12px 0" }}>
          No rows returned.
        </div>
      )}
    </div>
  );
}

/* ── Main Page ────────────────────────────────────────── */

export default function PipelineMonitorPage() {
  return (
    <div style={{ padding: "20px" }}>
      <h2 style={{ color: "#e0e0e0", marginBottom: "4px" }}>Pipeline Monitor</h2>
      <p style={{ color: "#888", fontSize: "13px", marginBottom: "24px" }}>
        All 5 Iceberg tables — click <strong style={{ color: "#4a6fa5" }}>Load</strong> to
        query the latest rows,{" "}
        <strong style={{ color: "#ff6b6b" }}>Delete</strong> to truncate the table.
      </p>

      {TASK_META.map(({ key, title, color }) => (
        <div key={key} style={{ marginBottom: "32px" }}>
          <h3
            style={{
              color,
              fontSize: "15px",
              marginBottom: "12px",
              paddingBottom: "6px",
              borderBottom: `1px solid ${color}33`,
            }}
          >
            {title}
          </h3>
          {TABLES[key].map((table) => (
            <TableSection key={table.id} table={table} />
          ))}
        </div>
      ))}
    </div>
  );
}
