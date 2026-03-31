import React, { useState, useCallback } from "react";
import { executeQuery } from "../../api.js";
import { snapshotsQuery, timeTravelQuery, snapshotTravelQuery } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

export default function TimeTravelFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [snapshots, setSnapshots] = useState([]);
  const [result, setResult] = useState(null);
  const [compareA, setCompareA] = useState(null);
  const [compareB, setCompareB] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [timestamp, setTimestamp] = useState(() => {
    const d = new Date(); d.setMinutes(d.getMinutes() - 5);
    return d.toISOString().slice(0, 19); // default: 5 min ago
  });
  const [mode, setMode] = useState("timeline"); // timeline | query | compare

  const loadSnapshots = useCallback(async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(snapshotsQuery(selectedTable));
      setSnapshots(res.rows || []);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [selectedTable]);

  const queryTimestamp = async () => {
    if (!timestamp) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(timeTravelQuery(selectedTable, timestamp));
      setResult(res);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const querySnapshot = async (sid) => {
    setLoading(true); setError("");
    try {
      const res = await executeQuery(snapshotTravelQuery(selectedTable, sid));
      setResult(res);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const loadCompare = async (sid, slot) => {
    try {
      const res = await executeQuery(snapshotTravelQuery(selectedTable, sid));
      if (slot === "A") setCompareA(res);
      else setCompareB(res);
    } catch (e) { setError(e.message); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Time Travel이란?"
        description="Iceberg는 모든 변경을 스냅샷으로 보존합니다. 과거 시점의 데이터를 조회하거나, 잘못된 변경을 롤백할 수 있습니다. SELECT ... FOR TIMESTAMP AS OF 또는 FOR VERSION AS OF 구문을 사용합니다."
        sqlExample={`SELECT * FROM table\n  FOR TIMESTAMP AS OF TIMESTAMP '2026-03-24 10:00:00';\n\nSELECT * FROM table\n  FOR VERSION AS OF 8619686881304977663;`}
        bookRef="Ch.5 Snapshots & Time Travel (p.89-95)"
      />

      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />

      <div className="iceberg-tabs">
        <button className={mode === "timeline" ? "active" : ""} onClick={() => { setMode("timeline"); loadSnapshots(); }}>Snapshot Timeline</button>
        <button className={mode === "query" ? "active" : ""} onClick={() => setMode("query")}>Time Travel Query</button>
        <button className={mode === "compare" ? "active" : ""} onClick={() => { setMode("compare"); loadSnapshots(); }}>Compare Snapshots</button>
      </div>

      {mode === "timeline" && (
        <div>
          <button className="iceberg-btn" onClick={loadSnapshots}>Load Snapshots</button>
          {snapshots.length > 0 && (
            <div className="iceberg-timeline">
              {snapshots.map((s, i) => (
                <div key={i} className="iceberg-timeline-item" onClick={() => querySnapshot(s.snapshot_id)}>
                  <div className="iceberg-timeline-dot" />
                  <div className="iceberg-timeline-content">
                    <strong>Snapshot {s.snapshot_id}</strong>
                    <span className="iceberg-timeline-date">{s.committed_at}</span>
                    <span className="iceberg-timeline-op">{s.operation}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {mode === "query" && (
        <div className="iceberg-form-row">
          <input type="datetime-local" value={timestamp} onChange={e => setTimestamp(e.target.value)} step="1" />
          <button className="iceberg-btn" onClick={queryTimestamp}>Query at Timestamp</button>
        </div>
      )}

      {mode === "compare" && (
        <div>
          <p className="iceberg-hint">Click two snapshots to compare:</p>
          <div className="iceberg-compare-selectors">
            {snapshots.slice(0, 10).map((s, i) => (
              <button key={i} className="iceberg-btn-sm" onClick={() => loadCompare(s.snapshot_id, compareA ? "B" : "A")}>
                {s.snapshot_id} ({s.operation})
              </button>
            ))}
          </div>
          {compareA && compareB && (
            <div className="iceberg-compare-grid">
              <div><h4>Snapshot A</h4><SqlResultTable columns={compareA.columns} rows={compareA.rows || []} /></div>
              <div><h4>Snapshot B</h4><SqlResultTable columns={compareB.columns} rows={compareB.rows || []} /></div>
            </div>
          )}
        </div>
      )}

      {error && <div className="iceberg-error">{error}</div>}
      {result && <SqlResultTable columns={result.columns} rows={result.rows || []} loading={loading} />}
    </div>
  );
}
