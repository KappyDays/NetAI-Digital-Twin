import React, { useState, useCallback } from "react";
import { executeQuery } from "../../api.js";
import { describeTable, showCreateTable, addColumn, dropColumn, renameColumn } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

const TYPES = ["VARCHAR", "INTEGER", "BIGINT", "DOUBLE", "BOOLEAN", "TIMESTAMP", "DATE"];

export default function SchemaEvolutionFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [schema, setSchema] = useState(null);
  const [ddl, setDdl] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [action, setAction] = useState("add"); // add | rename | drop
  const [newCol, setNewCol] = useState("");
  const [newType, setNewType] = useState("VARCHAR");
  const [oldCol, setOldCol] = useState("");
  const [renamedCol, setRenamedCol] = useState("");

  const loadSchema = useCallback(async () => {
    if (!selectedTable) return;
    setLoading(true); setError(""); setMsg("");
    try {
      const [desc, create] = await Promise.all([
        executeQuery(describeTable(selectedTable)),
        executeQuery(showCreateTable(selectedTable)),
      ]);
      setSchema(desc);
      setDdl(create.rows?.[0]?.[create.columns?.[0]] || "");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [selectedTable]);

  const execute = async (sql) => {
    setLoading(true); setError(""); setMsg("");
    try {
      await executeQuery(sql);
      setMsg(`Success: ${sql}`);
      loadSchema();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Schema Evolution이란?"
        description="Iceberg는 기존 데이터를 재작성하지 않고 컬럼 추가/삭제/이름변경/타입변경이 가능합니다. 각 데이터 파일은 작성 시점의 스키마를 기억하고, 읽기 시 현재 스키마로 자동 매핑됩니다."
        sqlExample={`ALTER TABLE t ADD COLUMN color VARCHAR;\nALTER TABLE t RENAME COLUMN old TO new;\nALTER TABLE t DROP COLUMN deprecated;`}
        bookRef="Ch.1 Schema Evolution (p.27), Ch.6 DDL Operations"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={loadSchema}>Load Schema</button>

      {schema && <SqlResultTable columns={schema.columns} rows={schema.rows || []} />}
      {ddl && <pre className="iceberg-ddl">{ddl}</pre>}

      <div className="iceberg-tabs">
        <button className={action === "add" ? "active" : ""} onClick={() => setAction("add")}>Add Column</button>
        <button className={action === "rename" ? "active" : ""} onClick={() => setAction("rename")}>Rename Column</button>
        <button className={action === "drop" ? "active" : ""} onClick={() => setAction("drop")}>Drop Column</button>
      </div>

      {action === "add" && (
        <div className="iceberg-form-row">
          <input placeholder="Column name" value={newCol} onChange={e => setNewCol(e.target.value)} />
          <select value={newType} onChange={e => setNewType(e.target.value)}>
            {TYPES.map(t => <option key={t}>{t}</option>)}
          </select>
          <button className="iceberg-btn" onClick={() => execute(addColumn(selectedTable, newCol, newType))} disabled={!newCol}>Add</button>
        </div>
      )}
      {action === "rename" && (
        <div className="iceberg-form-row">
          <input placeholder="Old name" value={oldCol} onChange={e => setOldCol(e.target.value)} />
          <span>→</span>
          <input placeholder="New name" value={renamedCol} onChange={e => setRenamedCol(e.target.value)} />
          <button className="iceberg-btn" onClick={() => execute(renameColumn(selectedTable, oldCol, renamedCol))} disabled={!oldCol || !renamedCol}>Rename</button>
        </div>
      )}
      {action === "drop" && (
        <div className="iceberg-form-row">
          <input placeholder="Column to drop" value={oldCol} onChange={e => setOldCol(e.target.value)} />
          <button className="iceberg-btn iceberg-btn-danger" onClick={() => { if (confirm(`Drop column "${oldCol}"?`)) execute(dropColumn(selectedTable, oldCol)); }} disabled={!oldCol}>Drop</button>
        </div>
      )}

      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
    </div>
  );
}
