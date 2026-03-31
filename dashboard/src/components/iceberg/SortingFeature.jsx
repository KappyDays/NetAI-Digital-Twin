import React, { useState } from "react";
import { executeQuery } from "../../api.js";
import { showCreateTable, setSortOrder } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import useTableList from "./useTableList.js";

export default function SortingFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [ddl, setDdl] = useState("");
  const [sortCols, setSortCols] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(showCreateTable(selectedTable));
      setDdl(res.rows?.[0]?.[res.columns?.[0]] || "");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const apply = async () => {
    if (!sortCols.trim()) return;
    setLoading(true); setError(""); setMsg("");
    try {
      const cols = sortCols.split(",").map(s => s.trim()).filter(Boolean);
      await executeQuery(setSortOrder(selectedTable, cols));
      setMsg("Sort order applied!");
      load();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Sorting & Z-ordering이란?"
        description="데이터를 특정 컬럼으로 정렬하면, 해당 컬럼으로 필터링할 때 스캔 파일 수가 크게 줄어듭니다. Z-ordering은 여러 컬럼(예: pos_x, pos_y)을 동시에 클러스터링하여 공간 범위 쿼리를 최적화합니다."
        sqlExample={`ALTER TABLE t SET PROPERTIES sorted_by = ARRAY['space_id'];\n\n-- Z-ordering (Spark only)\nCALL catalog.system.rewrite_data_files(\n  table => 't', strategy => 'sort',\n  sort_order => 'zorder(pos_x, pos_y)'\n);`}
        bookRef="Ch.7 Sorting & Z-ordering (p.110-115)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={load}>Load Current Settings</button>

      {ddl && <pre className="iceberg-ddl">{ddl}</pre>}

      <div className="iceberg-section">
        <h4>Z-ordering 개념</h4>
        <div className="iceberg-zorder-visual">
          <div className="iceberg-zorder-before">
            <h5>Before (Random)</h5>
            <div className="iceberg-grid-demo">
              {Array.from({ length: 16 }, (_, i) => (
                <div key={i} className="iceberg-grid-cell" style={{ background: `hsl(${Math.random() * 360}, 70%, 60%)` }} />
              ))}
            </div>
          </div>
          <div className="iceberg-zorder-arrow">→</div>
          <div className="iceberg-zorder-after">
            <h5>After Z-order(x, y)</h5>
            <div className="iceberg-grid-demo">
              {Array.from({ length: 16 }, (_, i) => (
                <div key={i} className="iceberg-grid-cell" style={{ background: `hsl(${(i / 16) * 240}, 70%, 60%)` }} />
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="iceberg-form-row">
        <input placeholder="e.g. space_id, timestamp" value={sortCols} onChange={e => setSortCols(e.target.value)} style={{ flex: 1 }} />
        <button className="iceberg-btn" onClick={apply} disabled={!sortCols.trim() || loading}>Set Sort Order</button>
      </div>

      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
    </div>
  );
}
