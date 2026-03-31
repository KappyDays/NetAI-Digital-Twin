import React, { useState, useCallback } from "react";
import { executeQuery } from "../../api.js";
import { filesQuery, compactQuery, compactWithSize } from "../../utils/icebergSql.js";
import { formatBytes } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

export default function CompactionFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [filesBefore, setFilesBefore] = useState(null);
  const [filesAfter, setFilesAfter] = useState(null);
  const [sizeMB, setSizeMB] = useState("128");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const loadFiles = useCallback(async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(filesQuery(selectedTable));
      setFilesBefore(res);
      setFilesAfter(null);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [selectedTable]);

  const runCompact = async (withSize) => {
    setLoading(true); setError(""); setMsg("");
    try {
      const sql = withSize ? compactWithSize(selectedTable, sizeMB) : compactQuery(selectedTable);
      await executeQuery(sql);
      setMsg("Compaction complete!");
      const res = await executeQuery(filesQuery(selectedTable));
      setFilesAfter(res);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const summarize = (res) => {
    if (!res?.rows) return { count: 0, totalSize: 0 };
    const rows = res.rows;
    return {
      count: rows.length,
      totalSize: rows.reduce((s, r) => s + (r.file_size_in_bytes || 0), 0),
      totalRows: rows.reduce((s, r) => s + (r.record_count || 0), 0),
    };
  };

  const before = summarize(filesBefore);
  const after = summarize(filesAfter);

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Compaction이란?"
        description="IoT 센서 데이터는 소량씩 자주 삽입되어 작은 파일이 폭발적으로 늘어납니다. Compaction은 이 작은 파일들을 큰 파일로 병합하여 쿼리 성능을 크게 향상시킵니다. binpack(기본), sort, z-order 세 가지 전략이 있습니다."
        sqlExample={`ALTER TABLE t EXECUTE optimize;\nALTER TABLE t EXECUTE optimize(file_size_threshold => '128MB');`}
        bookRef="Ch.7 Compaction (p.103-110)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={loadFiles}>Analyze Files</button>

      {filesBefore && (
        <div className="iceberg-compare-grid">
          <div className="iceberg-stat-card">
            <h4>Before Compaction</h4>
            <div className="iceberg-stat-value">{before.count} files</div>
            <div className="iceberg-stat-label">{formatBytes(before.totalSize)} total</div>
            <div className="iceberg-stat-label">{before.totalRows?.toLocaleString()} rows</div>
          </div>
          {filesAfter && (
            <div className="iceberg-stat-card iceberg-stat-card-success">
              <h4>After Compaction</h4>
              <div className="iceberg-stat-value">{after.count} files</div>
              <div className="iceberg-stat-label">{formatBytes(after.totalSize)} total</div>
              <div className="iceberg-stat-label">{after.totalRows?.toLocaleString()} rows</div>
              <div className="iceberg-stat-diff">
                {before.count - after.count > 0 ? `−${before.count - after.count} files` : "No change"}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="iceberg-form-row">
        <label>File size target:</label>
        <input type="number" value={sizeMB} onChange={e => setSizeMB(e.target.value)} style={{ width: 80 }} />
        <span>MB</span>
        <button className="iceberg-btn" onClick={() => runCompact(true)} disabled={loading}>Optimize (custom)</button>
        <button className="iceberg-btn" onClick={() => runCompact(false)} disabled={loading}>Optimize (default)</button>
      </div>

      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
      {filesBefore && <SqlResultTable columns={filesBefore.columns} rows={filesBefore.rows || []} loading={loading} />}
    </div>
  );
}
