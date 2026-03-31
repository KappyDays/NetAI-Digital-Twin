import React, { useState } from "react";
import { executeQuery } from "../../api.js";
import { expireSnapshots, snapshotsQuery } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

export default function MaintenanceFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [snapResult, setSnapResult] = useState(null);
  const [retention, setRetention] = useState("7d");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const loadSnapshots = async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(snapshotsQuery(selectedTable));
      setSnapResult(res);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const runExpire = async () => {
    setLoading(true); setError(""); setMsg("");
    try {
      await executeQuery(expireSnapshots(selectedTable, retention));
      setMsg(`Snapshots older than ${retention} expired!`);
      loadSnapshots();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="테이블 유지보수란?"
        description="Iceberg 테이블은 시간이 지나면 오래된 스냅샷, 고아 파일, 불필요한 메타데이터가 쌓입니다. 주기적인 유지보수로 스토리지 비용을 절감하고 쿼리 성능을 유지합니다."
        sqlExample={`ALTER TABLE t EXECUTE expire_snapshots(\n  retention_threshold => '7d'\n);`}
        bookRef="Ch.10 Table Maintenance (p.135-142)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={loadSnapshots}>Load Snapshots</button>

      {snapResult && (
        <div className="iceberg-stat-card">
          <div className="iceberg-stat-value">{snapResult.rows?.length || 0} snapshots</div>
          <div className="iceberg-stat-label">in this table</div>
        </div>
      )}

      <div className="iceberg-form-row">
        <label>Retention:</label>
        <select value={retention} onChange={e => setRetention(e.target.value)}>
          <option value="1d">1 day</option>
          <option value="3d">3 days</option>
          <option value="7d">7 days</option>
          <option value="14d">14 days</option>
          <option value="30d">30 days</option>
        </select>
        <button className="iceberg-btn iceberg-btn-danger" onClick={runExpire} disabled={loading}>Expire Snapshots</button>
      </div>

      <div className="iceberg-section">
        <h4>권장 유지보수 스케줄</h4>
        <table className="iceberg-table">
          <thead><tr><th className="iceberg-th">주기</th><th className="iceberg-th">작업</th><th className="iceberg-th">대상</th></tr></thead>
          <tbody>
            <tr><td className="iceberg-td">매시간</td><td className="iceberg-td">EXECUTE optimize</td><td className="iceberg-td">dynamic 테이블</td></tr>
            <tr><td className="iceberg-td">매일</td><td className="iceberg-td">expire_snapshots (7d)</td><td className="iceberg-td">모든 테이블</td></tr>
            <tr><td className="iceberg-td">매주</td><td className="iceberg-td">EXECUTE optimize (sort)</td><td className="iceberg-td">static_prims</td></tr>
          </tbody>
        </table>
      </div>

      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
      {snapResult && <SqlResultTable columns={snapResult.columns} rows={snapResult.rows || []} loading={loading} />}
    </div>
  );
}
