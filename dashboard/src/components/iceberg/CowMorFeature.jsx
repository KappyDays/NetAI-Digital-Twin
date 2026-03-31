import React, { useState } from "react";
import { executeQuery } from "../../api.js";
import { showCreateTable, setWriteMode } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import useTableList from "./useTableList.js";

export default function CowMorFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [ddl, setDdl] = useState("");
  const [currentMode, setCurrentMode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    if (!selectedTable) return;
    setLoading(true); setError("");
    try {
      const res = await executeQuery(showCreateTable(selectedTable));
      const text = res.rows?.[0]?.[res.columns?.[0]] || "";
      setDdl(text);
      setCurrentMode(text.includes("merge-on-read") ? "merge-on-read" : "copy-on-write");
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  const switchMode = async (mode) => {
    setLoading(true); setError(""); setMsg("");
    try {
      await executeQuery(setWriteMode(selectedTable, mode));
      setMsg(`Mode changed to ${mode}!`);
      setCurrentMode(mode);
      load();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Copy-on-Write vs Merge-on-Read란?"
        description="COW는 삭제/수정 시 전체 데이터 파일을 재작성합니다 (읽기 빠름, 쓰기 느림). MOR는 삭제 표시 파일(Delete File)을 별도로 기록합니다 (쓰기 빠름, 읽기 시 병합 필요). IoT 센서 데이터처럼 쓰기가 많은 테이블은 MOR, 분석용 테이블은 COW가 적합합니다."
        sqlExample={`ALTER TABLE t SET PROPERTIES write_delete_mode = 'copy-on-write';\nALTER TABLE t SET PROPERTIES write_delete_mode = 'merge-on-read';`}
        bookRef="Ch.8 COW vs MOR (p.117-125)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />
      <button className="iceberg-btn" onClick={load}>Load Current Mode</button>

      <div className="iceberg-cow-mor-visual">
        <div className={`iceberg-mode-card ${currentMode === "copy-on-write" ? "iceberg-mode-active" : ""}`} onClick={() => switchMode("copy-on-write")}>
          <h4>Copy-on-Write (COW)</h4>
          <div className="iceberg-mode-diagram">
            <div className="iceberg-mode-step">DELETE row</div>
            <div className="iceberg-mode-arrow">→</div>
            <div className="iceberg-mode-step iceberg-mode-rewrite">Rewrite entire file</div>
          </div>
          <ul>
            <li>읽기 성능 최적</li>
            <li>쓰기 비용 높음</li>
            <li>분석 테이블에 적합</li>
          </ul>
        </div>

        <div className={`iceberg-mode-card ${currentMode === "merge-on-read" ? "iceberg-mode-active" : ""}`} onClick={() => switchMode("merge-on-read")}>
          <h4>Merge-on-Read (MOR)</h4>
          <div className="iceberg-mode-diagram">
            <div className="iceberg-mode-step">DELETE row</div>
            <div className="iceberg-mode-arrow">→</div>
            <div className="iceberg-mode-step iceberg-mode-delete">Write delete file</div>
          </div>
          <ul>
            <li>쓰기 성능 최적</li>
            <li>읽기 시 병합 비용</li>
            <li>IoT 센서 데이터에 적합</li>
          </ul>
        </div>
      </div>

      {currentMode && <div className="iceberg-hint">Current mode: <strong>{currentMode}</strong></div>}
      {msg && <div className="iceberg-success">{msg}</div>}
      {error && <div className="iceberg-error">{error}</div>}
    </div>
  );
}
