import React, { useState } from "react";
import { executeQuery } from "../api.js";

/**
 * QueryPanel — Ad-hoc Trino SQL query interface.
 */

const EXAMPLE_QUERIES = [
  {
    label: "List static spaces",
    sql: "SELECT DISTINCT space_id, COUNT(*) as prim_count FROM iceberg.static_db.static_prims GROUP BY space_id",
  },
  {
    label: "Show all schemas",
    sql: "SHOW SCHEMAS FROM iceberg",
  },
  {
    label: "Show tables in static_db",
    sql: "SHOW TABLES FROM iceberg.static_db",
  },
  {
    label: "Recent dynamic data (sample)",
    sql: "SHOW SCHEMAS FROM iceberg",
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
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            marginBottom: "0.75rem",
            flexWrap: "wrap",
          }}
        >
          {EXAMPLE_QUERIES.map((q) => (
            <button
              key={q.label}
              className="btn"
              style={{ fontSize: "0.7rem" }}
              onClick={() => setSql(q.sql)}
            >
              {q.label}
            </button>
          ))}
        </div>

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="SELECT * FROM iceberg.static_db.static_prims LIMIT 10"
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
