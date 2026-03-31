import React, { useState } from "react";
import { executeQuery } from "../../api.js";
import { showCreateTable, partitionsQuery, setPartitioning } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

const TRANSFORMS = ["year", "month", "day", "hour", "bucket", "truncate"];

export default function PartitionEvolutionFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [ddl, setDdl] = useState("");
  const [partResult, setPartResult] = useState(null);
  const [newSpec, setNewSpec] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const [cr, pr] = await Promise.all([
        executeQuery(showCreateTable(selectedTable)),
        executeQuery(partitionsQuery(selectedTable)),
      ]);
      setDdl(cr.rows?.[0]?.[cr.columns?.[0]] || "");
      setPartResult(pr);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const applyPartition = async () => {
    if (!newSpec.trim()) return;
    setLoading(true); setError(""); setMsg("");
    try {
      const specs = newSpec.split(",").map(s => s.trim());
      await executeQuery(setPartitioning(selectedTable, specs));
      setMsg("Partition evolution applied!");
      load();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Partition Evolution이란?"
        description="데이터가 쌓이면서 파티셔닝 전략을 변경해야 할 때, Iceberg는 기존 데이터를 재작성하지 않고 파티셔닝을 진화시킬 수 있습니다. 새 파티셔닝은 새 데이터에만 적용되고, 쿼리 엔진은 두 스펙을 모두 인식합니다."
        sqlExample={`ALTER TABLE t SET PROPERTIES\n  partitioning = ARRAY['hour(timestamp)', 'bucket(object_id, 8)'];`}
        bookRef="Ch.4 Partition Evolution (p.85-87)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={load}>Load Partition Info</button>

      {ddl && (
        <div className="iceberg-section">
          <h4>Current DDL</h4>
          <pre className="iceberg-ddl">{ddl}</pre>
        </div>
      )}

      <div className="iceberg-section">
        <h4>Available Transforms</h4>
        <div className="iceberg-tag-grid">
          {TRANSFORMS.map(t => (
            <span key={t} className="iceberg-tag" onClick={() => setNewSpec(prev => prev ? `${prev}, ${t}(column)` : `${t}(column)`)}>
              {t}()
            </span>
          ))}
        </div>
      </div>

      <div className="iceberg-form-row">
        <input placeholder="e.g. hour(timestamp), bucket(object_id, 8)" value={newSpec} onChange={e => setNewSpec(e.target.value)} style={{ flex: 1 }} />
        <button className="iceberg-btn" onClick={applyPartition} disabled={!newSpec.trim() || loading}>Apply</button>
      </div>

      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
      {partResult && <SqlResultTable columns={partResult.columns} rows={partResult.rows || []} loading={loading} />}
    </div>
  );
}
