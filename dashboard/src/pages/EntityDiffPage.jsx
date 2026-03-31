import React, { useState, useCallback } from "react";

/**
 * EntityDiffPage — 3-Level drill-down Entity comparison view.
 *
 * Level 1: Select two backup times → compare entity hashes
 * Level 2: Click a changed entity → compare sub-prim hashes
 * Level 3: Click a changed sub-prim → view before/after JSON properties
 */

const API_BASE = "";

const STATUS_COLORS = {
  added: "#4caf50",
  removed: "#f44336",
  changed: "#ff9800",
  unchanged: "#666",
};

const STATUS_ICONS = {
  added: "+",
  removed: "-",
  changed: "~",
  unchanged: "=",
};

// ─── API Helpers ──────────────────────────────────────────────────────

async function fetchBackupTimes() {
  const res = await fetch(`${API_BASE}/api/v1/entities/backup-times`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchEntityDiff(timeA, timeB) {
  const params = new URLSearchParams({ time_a: timeA, time_b: timeB });
  const res = await fetch(`${API_BASE}/api/v1/entities/diff?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchPrimDiff(entityPath, timeA, timeB) {
  const safePath = entityPath.startsWith("/") ? entityPath.slice(1) : entityPath;
  const params = new URLSearchParams({ time_a: timeA, time_b: timeB });
  const res = await fetch(`${API_BASE}/api/v1/entities/${safePath}/prim-diff?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ─── JSON Diff Highlighter ────────────────────────────────────────────

function JsonDiffView({ jsonA, jsonB }) {
  let objA = {},
    objB = {};
  try {
    objA = JSON.parse(jsonA || "{}");
  } catch {}
  try {
    objB = JSON.parse(jsonB || "{}");
  } catch {}

  const allKeys = [...new Set([...Object.keys(objA), ...Object.keys(objB)])].sort();

  return (
    <div className="json-diff-container">
      <div className="json-diff-side">
        <div className="json-diff-header">Before (Time A)</div>
        <pre className="json-diff-content">
          {allKeys.map((key) => {
            const valA = objA[key] !== undefined ? JSON.stringify(objA[key]) : undefined;
            const valB = objB[key] !== undefined ? JSON.stringify(objB[key]) : undefined;
            const color =
              valA === undefined
                ? STATUS_COLORS.removed
                : valA !== valB
                ? STATUS_COLORS.changed
                : "#ccc";
            return (
              <div key={key} style={{ color }}>
                {`  "${key}": ${valA !== undefined ? valA : "(missing)"}`}
              </div>
            );
          })}
        </pre>
      </div>
      <div className="json-diff-side">
        <div className="json-diff-header">After (Time B)</div>
        <pre className="json-diff-content">
          {allKeys.map((key) => {
            const valA = objA[key] !== undefined ? JSON.stringify(objA[key]) : undefined;
            const valB = objB[key] !== undefined ? JSON.stringify(objB[key]) : undefined;
            const color =
              valB === undefined
                ? STATUS_COLORS.removed
                : valA !== valB
                ? STATUS_COLORS.changed
                : "#ccc";
            return (
              <div key={key} style={{ color }}>
                {`  "${key}": ${valB !== undefined ? valB : "(missing)"}`}
              </div>
            );
          })}
        </pre>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────

export default function EntityDiffPage() {
  // State
  const [backupTimes, setBackupTimes] = useState([]);
  const [backupSources, setBackupSources] = useState([]);
  const [timeA, setTimeA] = useState("");
  const [timeB, setTimeB] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Level 1: Entity diff
  const [entityDiff, setEntityDiff] = useState(null);

  // Level 2: Prim diff
  const [selectedEntity, setSelectedEntity] = useState(null);
  const [primDiff, setPrimDiff] = useState(null);

  // Level 3: Property diff
  const [selectedPrim, setSelectedPrim] = useState(null);

  // Load backup times
  const loadTimes = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchBackupTimes();
      setBackupTimes(data.backup_times || []);
      setBackupSources(data.backup_sources || []);
      if (data.backup_times?.length >= 2) {
        setTimeA(data.backup_times[1]);
        setTimeB(data.backup_times[0]);
      } else if (data.backup_times?.length === 1) {
        setTimeA(data.backup_times[0]);
        setTimeB(data.backup_times[0]);
      }
    } catch (err) {
      setError(`Failed to load backup times: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  // Compare entities
  const onCompare = useCallback(async () => {
    if (!timeA || !timeB) return;
    try {
      setLoading(true);
      setError(null);
      setEntityDiff(null);
      setPrimDiff(null);
      setSelectedEntity(null);
      setSelectedPrim(null);
      const data = await fetchEntityDiff(timeA, timeB);
      setEntityDiff(data);
    } catch (err) {
      setError(`Diff failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [timeA, timeB]);

  // Drill into entity
  const onEntityClick = useCallback(
    async (entity) => {
      if (entity.status === "unchanged") return;
      try {
        setLoading(true);
        setSelectedEntity(entity);
        setSelectedPrim(null);
        setPrimDiff(null);
        const data = await fetchPrimDiff(entity.entity_path, timeA, timeB);
        setPrimDiff(data);
      } catch (err) {
        setError(`Prim diff failed: ${err.message}`);
      } finally {
        setLoading(false);
      }
    },
    [timeA, timeB]
  );

  // Drill into prim
  const onPrimClick = useCallback((prim) => {
    if (prim.status === "unchanged") return;
    setSelectedPrim(prim);
  }, []);

  // Navigate back
  const goBack = useCallback(() => {
    if (selectedPrim) {
      setSelectedPrim(null);
    } else if (selectedEntity) {
      setSelectedEntity(null);
      setPrimDiff(null);
    }
  }, [selectedPrim, selectedEntity]);

  return (
    <div className="entity-diff-page">
      <h2>Entity Diff Viewer</h2>
      <p className="page-desc">
        Compare Entity snapshots between two backup times. Drill down to see
        changed Sub-Prims and property-level diffs.
      </p>

      {/* ── Time Selection ─────────────────────────────────────── */}
      <div className="diff-controls">
        <button onClick={loadTimes} disabled={loading} className="btn btn-secondary">
          Load Backup Times
        </button>

        <div className="time-selectors">
          <label>
            Time A (before):
            <select value={timeA} onChange={(e) => setTimeA(e.target.value)}>
              <option value="">Select...</option>
              {backupTimes.map((t, i) => (
                <option key={t} value={t}>
                  {t} [{backupSources[i] || "?"}]
                </option>
              ))}
            </select>
          </label>
          <label>
            Time B (after):
            <select value={timeB} onChange={(e) => setTimeB(e.target.value)}>
              <option value="">Select...</option>
              {backupTimes.map((t, i) => (
                <option key={t} value={t}>
                  {t} [{backupSources[i] || "?"}]
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          onClick={onCompare}
          disabled={loading || !timeA || !timeB}
          className="btn btn-primary"
        >
          {loading ? "Comparing..." : "Compare"}
        </button>
      </div>

      {error && <div className="diff-error">{error}</div>}

      {/* Cross-source warning */}
      {timeA && timeB && (() => {
        const idxA = backupTimes.indexOf(timeA);
        const idxB = backupTimes.indexOf(timeB);
        const srcA = backupSources[idxA];
        const srcB = backupSources[idxB];
        if (srcA && srcB && srcA !== srcB) {
          return (
            <div className="diff-warning">
              Source mismatch: Time A [{srcA}] vs Time B [{srcB}].
              Extension과 Nucleus/Local 백업은 속성 추출 방식이 달라 비교 결과가 부정확할 수 있습니다.
            </div>
          );
        }
        return null;
      })()}

      {/* ── Breadcrumb ─────────────────────────────────────────── */}
      {(selectedEntity || selectedPrim) && (
        <div className="diff-breadcrumb">
          <button onClick={goBack} className="btn btn-back">
            Back
          </button>
          <span className="breadcrumb-path">
            Entities
            {selectedEntity && ` > ${selectedEntity.entity_path}`}
            {selectedPrim && ` > ${selectedPrim.relative_path}`}
          </span>
        </div>
      )}

      {/* ── Level 3: Property Diff ─────────────────────────────── */}
      {selectedPrim && (
        <div className="diff-section">
          <h3>
            Property Diff: {selectedPrim.relative_path}
            <span
              className="status-badge"
              style={{ backgroundColor: STATUS_COLORS[selectedPrim.status] }}
            >
              {selectedPrim.status}
            </span>
          </h3>
          <JsonDiffView jsonA={selectedPrim.properties_a} jsonB={selectedPrim.properties_b} />
        </div>
      )}

      {/* ── Level 2: Prim Diff ─────────────────────────────────── */}
      {primDiff && !selectedPrim && (
        <div className="diff-section">
          <h3>
            Sub-Prim Diff: {selectedEntity?.entity_path}
          </h3>
          <div className="diff-summary">
            <span className="stat added">+{primDiff.added} added</span>
            <span className="stat removed">-{primDiff.removed} removed</span>
            <span className="stat changed">~{primDiff.changed} changed</span>
            <span className="stat unchanged">={primDiff.unchanged} unchanged</span>
          </div>
          <div className="diff-table">
            <div className="diff-table-header">
              <span className="col-status">St</span>
              <span className="col-path">Relative Path</span>
              <span className="col-type">Type</span>
              <span className="col-hash">Hash A</span>
              <span className="col-hash">Hash B</span>
            </div>
            {primDiff.prims?.map((p) => (
              <div
                key={p.relative_path}
                className={`diff-table-row ${p.status !== "unchanged" ? "clickable" : ""}`}
                onClick={() => onPrimClick(p)}
                style={{ borderLeft: `3px solid ${STATUS_COLORS[p.status]}` }}
              >
                <span className="col-status" style={{ color: STATUS_COLORS[p.status] }}>
                  {STATUS_ICONS[p.status]}
                </span>
                <span className="col-path">{p.relative_path || "/"}</span>
                <span className="col-type">{p.prim_type}</span>
                <span className="col-hash">{p.hash_a?.slice(0, 8) || "-"}</span>
                <span className="col-hash">{p.hash_b?.slice(0, 8) || "-"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Level 1: Entity Diff ───────────────────────────────── */}
      {entityDiff && !selectedEntity && (
        <div className="diff-section">
          <h3>Entity Comparison</h3>
          <div className="diff-summary">
            <span className="stat">Time A: {entityDiff.total_a} entities</span>
            <span className="stat">Time B: {entityDiff.total_b} entities</span>
            <span className="stat added">+{entityDiff.added}</span>
            <span className="stat removed">-{entityDiff.removed}</span>
            <span className="stat changed">~{entityDiff.changed}</span>
            <span className="stat unchanged">={entityDiff.unchanged}</span>
          </div>
          <div className="diff-table">
            <div className="diff-table-header">
              <span className="col-status">St</span>
              <span className="col-path">Entity Path</span>
              <span className="col-type">Type</span>
              <span className="col-hash">Hash A</span>
              <span className="col-hash">Hash B</span>
            </div>
            {entityDiff.entities?.map((e) => (
              <div
                key={e.entity_path}
                className={`diff-table-row ${e.status !== "unchanged" ? "clickable" : ""}`}
                onClick={() => onEntityClick(e)}
                style={{ borderLeft: `3px solid ${STATUS_COLORS[e.status]}` }}
              >
                <span className="col-status" style={{ color: STATUS_COLORS[e.status] }}>
                  {STATUS_ICONS[e.status]}
                </span>
                <span className="col-path">{e.entity_path}</span>
                <span className="col-type">{e.entity_type || "-"}</span>
                <span className="col-hash">{e.hash_a?.slice(0, 8) || "-"}</span>
                <span className="col-hash">{e.hash_b?.slice(0, 8) || "-"}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`
        .entity-diff-page {
          padding: 0;
        }
        .entity-diff-page h2 {
          margin: 0 0 4px 0;
          color: #e0e0e0;
        }
        .page-desc {
          color: #888;
          font-size: 0.9em;
          margin-bottom: 16px;
        }
        .diff-controls {
          display: flex;
          align-items: flex-end;
          gap: 16px;
          margin-bottom: 16px;
          flex-wrap: wrap;
        }
        .time-selectors {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
        }
        .time-selectors label {
          display: flex;
          flex-direction: column;
          gap: 4px;
          color: #aaa;
          font-size: 0.85em;
        }
        .time-selectors select {
          background: #1a1a2e;
          color: #e0e0e0;
          border: 1px solid #444;
          border-radius: 4px;
          padding: 6px 8px;
          font-size: 0.9em;
          min-width: 220px;
        }
        .btn {
          padding: 8px 16px;
          border: none;
          border-radius: 4px;
          cursor: pointer;
          font-size: 0.9em;
          transition: background 0.2s;
        }
        .btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .btn-primary {
          background: #2979ff;
          color: white;
        }
        .btn-primary:hover:not(:disabled) {
          background: #448aff;
        }
        .btn-secondary {
          background: #333;
          color: #ccc;
        }
        .btn-secondary:hover:not(:disabled) {
          background: #444;
        }
        .btn-back {
          background: #555;
          color: #ddd;
          font-size: 0.85em;
          padding: 4px 12px;
        }
        .diff-error {
          background: #3a1a1a;
          color: #ff6b6b;
          padding: 10px 14px;
          border-radius: 4px;
          margin-bottom: 12px;
          border-left: 3px solid #f44336;
        }
        .diff-warning {
          background: #3a3a1a;
          color: #ffcc66;
          padding: 10px 14px;
          border-radius: 4px;
          margin-bottom: 12px;
          border-left: 3px solid #ff9800;
          font-size: 0.9em;
        }
        .diff-breadcrumb {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 12px;
          padding: 8px 12px;
          background: #1a1a2e;
          border-radius: 4px;
        }
        .breadcrumb-path {
          color: #66ccff;
          font-size: 0.9em;
        }
        .diff-section h3 {
          color: #e0e0e0;
          margin: 0 0 8px 0;
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .status-badge {
          font-size: 0.75em;
          padding: 2px 8px;
          border-radius: 10px;
          color: white;
          text-transform: uppercase;
        }
        .diff-summary {
          display: flex;
          gap: 16px;
          margin-bottom: 12px;
          flex-wrap: wrap;
        }
        .stat {
          color: #aaa;
          font-size: 0.9em;
          padding: 4px 10px;
          background: #1a1a2e;
          border-radius: 4px;
        }
        .stat.added { color: #4caf50; }
        .stat.removed { color: #f44336; }
        .stat.changed { color: #ff9800; }
        .stat.unchanged { color: #666; }
        .diff-table {
          border: 1px solid #333;
          border-radius: 6px;
          overflow: hidden;
        }
        .diff-table-header {
          display: flex;
          gap: 8px;
          padding: 8px 12px;
          background: #1a1a2e;
          color: #888;
          font-size: 0.8em;
          text-transform: uppercase;
          border-bottom: 1px solid #333;
        }
        .diff-table-row {
          display: flex;
          gap: 8px;
          padding: 8px 12px;
          border-bottom: 1px solid #222;
          transition: background 0.15s;
        }
        .diff-table-row:last-child {
          border-bottom: none;
        }
        .diff-table-row.clickable {
          cursor: pointer;
        }
        .diff-table-row.clickable:hover {
          background: #1a1a3e;
        }
        .col-status {
          width: 24px;
          text-align: center;
          font-weight: bold;
          font-size: 1.1em;
        }
        .col-path {
          flex: 3;
          color: #e0e0e0;
          font-family: monospace;
          font-size: 0.9em;
        }
        .col-type {
          flex: 1;
          color: #888;
          font-size: 0.85em;
        }
        .col-hash {
          flex: 1;
          color: #666;
          font-family: monospace;
          font-size: 0.85em;
        }
        .json-diff-container {
          display: flex;
          gap: 12px;
        }
        .json-diff-side {
          flex: 1;
          border: 1px solid #333;
          border-radius: 6px;
          overflow: hidden;
        }
        .json-diff-header {
          padding: 8px 12px;
          background: #1a1a2e;
          color: #888;
          font-size: 0.85em;
          border-bottom: 1px solid #333;
        }
        .json-diff-content {
          padding: 12px;
          margin: 0;
          font-family: monospace;
          font-size: 0.85em;
          line-height: 1.6;
          overflow-x: auto;
          max-height: 500px;
          overflow-y: auto;
        }
      `}</style>
    </div>
  );
}
