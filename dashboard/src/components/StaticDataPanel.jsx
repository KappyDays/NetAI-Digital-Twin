import React, { useState, useEffect } from "react";
import { getSpaces, getStaticPrims, executeQuery } from "../api.js";

/**
 * StaticDataPanel — Browse static Prim data stored in Iceberg.
 */
export default function StaticDataPanel() {
  const [spaces, setSpaces] = useState([]);
  const [selectedSpace, setSelectedSpace] = useState(null);
  const [prims, setPrims] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Fetch spaces on mount
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await getSpaces();
        if (res.spaces && res.spaces.length > 0) {
          setSpaces(res.spaces);
        } else {
          // Fallback: query distinct space_ids from Trino
          try {
            const sql = await executeQuery(
              "SELECT DISTINCT space_id FROM iceberg.static_db.static_prims ORDER BY space_id"
            );
            const rows = sql.rows || sql.data || [];
            setSpaces(rows.map((r) => ({ space_id: r[0] || r.space_id })));
          } catch {
            setSpaces([]);
          }
        }
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Fetch prims when space selected
  useEffect(() => {
    if (!selectedSpace) return;
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getStaticPrims(selectedSpace);
        if (!cancelled) setPrims(res.prims || res.data || []);
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [selectedSpace]);

  return (
    <div>
      <h2 style={{ fontSize: "1.1rem", marginBottom: "1rem" }}>
        Static Object Browser
      </h2>

      <div className="grid-2">
        {/* Space list */}
        <div className="card">
          <div className="card-title">Spaces (/World children)</div>
          {loading && spaces.length === 0 && (
            <div className="loading">Loading spaces...</div>
          )}
          {!loading && spaces.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              No spaces found. Use <code>POST /api/v1/static/prims</code> to
              ingest static scene data.
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
            {spaces.map((s) => (
              <button
                key={s.space_id}
                className={`btn ${selectedSpace === s.space_id ? "btn-primary" : ""}`}
                onClick={() => setSelectedSpace(s.space_id)}
                style={{ textAlign: "left" }}
              >
                {s.space_id}
                {s.prim_count != null && (
                  <span style={{ float: "right", opacity: 0.6 }}>
                    {s.prim_count} prims
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Prim detail table */}
        <div className="card">
          <div className="card-title">
            Prims{selectedSpace ? ` — ${selectedSpace}` : ""}
          </div>
          {error && <div className="error-msg">{error}</div>}
          {!selectedSpace && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              Select a space to view its Prim hierarchy.
            </div>
          )}
          {selectedSpace && loading && (
            <div className="loading">Loading prims...</div>
          )}
          {selectedSpace && !loading && prims.length === 0 && (
            <div style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
              No prims found in this space.
            </div>
          )}
          {prims.length > 0 && (
            <div style={{ maxHeight: "500px", overflowY: "auto" }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Prim Path</th>
                    <th>Type</th>
                    <th>Properties</th>
                  </tr>
                </thead>
                <tbody>
                  {prims.map((p, i) => (
                    <tr key={i}>
                      <td style={{ fontFamily: "monospace", fontSize: "0.75rem" }}>
                        {p.prim_path || p.path || "—"}
                      </td>
                      <td>
                        <span className="badge badge-healthy">
                          {p.prim_type || p.type || "—"}
                        </span>
                      </td>
                      <td
                        style={{
                          maxWidth: "200px",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                          fontSize: "0.7rem",
                          color: "var(--text-muted)",
                        }}
                        title={
                          typeof p.properties === "object"
                            ? JSON.stringify(p.properties)
                            : p.properties || ""
                        }
                      >
                        {typeof p.properties === "object"
                          ? JSON.stringify(p.properties).slice(0, 80)
                          : p.properties || "—"}
                      </td>
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
