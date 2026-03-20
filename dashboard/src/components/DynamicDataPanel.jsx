import React, { useState, useEffect } from "react";
import { getDynamicTables, getDynamicLatest, executeQuery } from "../api.js";

/**
 * DynamicDataPanel — Browse dynamic object Iceberg tables and latest sensor data.
 */
export default function DynamicDataPanel() {
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState(null);
  const [latestData, setLatestData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Fetch dynamic tables
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await getDynamicTables();
        setTables(res.tables || []);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Fetch latest data for selected table
  useEffect(() => {
    if (!selectedTable) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getDynamicLatest(selectedTable);
        if (!cancelled) setLatestData(res.data || res.rows || []);
      } catch (err) {
        // Fallback: direct SQL
        try {
          const sql = await executeQuery(
            `SELECT * FROM iceberg.dynamic_db.${selectedTable} ORDER BY event_timestamp DESC LIMIT 20`
          );
          if (!cancelled) setLatestData(sql.rows || sql.data || []);
        } catch {
          if (!cancelled) setError(err.message);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [selectedTable]);

  return (
    <div>
      <h2 style={{ fontSize: "1.1rem", marginBottom: "1rem" }}>
        Dynamic Object Tables
      </h2>

      <div className="grid-2">
        {/* Table list */}
        <div className="card">
          <div className="card-title">Iceberg Tables (per object)</div>
          {loading && tables.length === 0 && (
            <div className="loading">Loading tables...</div>
          )}
          {!loading && tables.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              No dynamic tables found. Use{" "}
              <code>POST /api/v1/dynamic-objects/tables</code> to create one.
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
            {tables.map((t) => {
              const name = typeof t === "string" ? t : t.table_name || t.name;
              return (
                <button
                  key={name}
                  className={`btn ${selectedTable === name ? "btn-primary" : ""}`}
                  onClick={() => setSelectedTable(name)}
                  style={{ textAlign: "left", fontFamily: "monospace" }}
                >
                  {name}
                </button>
              );
            })}
          </div>
        </div>

        {/* Latest sensor data */}
        <div className="card">
          <div className="card-title">
            Latest Sensor Data
            {selectedTable && (
              <span style={{ fontWeight: 400, color: "var(--text-muted)" }}>
                {" "}
                — {selectedTable}
              </span>
            )}
          </div>
          {error && <div className="error-msg">{error}</div>}
          {!selectedTable && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              Select a table to view recent sensor readings.
            </div>
          )}
          {selectedTable && loading && (
            <div className="loading">Loading data...</div>
          )}
          {selectedTable && !loading && latestData.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              No data in this table yet.
            </div>
          )}
          {latestData.length > 0 && (
            <div style={{ maxHeight: "500px", overflowY: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    {Object.keys(
                      typeof latestData[0] === "object" && !Array.isArray(latestData[0])
                        ? latestData[0]
                        : {}
                    ).map((k) => (
                      <th key={k}>{k}</th>
                    ))}
                    {Array.isArray(latestData[0]) &&
                      latestData[0].map((_, i) => <th key={i}>Col {i}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {latestData.map((row, ri) => (
                    <tr key={ri}>
                      {typeof row === "object" && !Array.isArray(row)
                        ? Object.values(row).map((v, ci) => (
                            <td key={ci} style={{ fontSize: "0.75rem" }}>
                              {v == null ? "—" : String(v).slice(0, 60)}
                            </td>
                          ))
                        : Array.isArray(row)
                        ? row.map((v, ci) => (
                            <td key={ci} style={{ fontSize: "0.75rem" }}>
                              {v == null ? "—" : String(v).slice(0, 60)}
                            </td>
                          ))
                        : (
                            <td style={{ fontSize: "0.75rem" }}>{String(row)}</td>
                          )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
