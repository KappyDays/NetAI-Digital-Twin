import React, { useState } from "react";
import { executeQuery } from "../../api.js";
import { snapshotsQuery, historyQuery, filesQuery, partitionsQuery, manifestsQuery } from "../../utils/icebergSql.js";
import InfoPanel from "./InfoPanel.jsx";
import TableSelector from "./TableSelector.jsx";
import SqlResultTable from "./SqlResultTable.jsx";
import useTableList from "./useTableList.js";

const TABS = [
  { key: "snapshots", label: "Snapshots", icon: "📸", fn: snapshotsQuery },
  { key: "history", label: "History", icon: "📜", fn: historyQuery },
  { key: "files", label: "Files", icon: "📁", fn: filesQuery },
  { key: "partitions", label: "Partitions", icon: "📊", fn: partitionsQuery },
  { key: "manifests", label: "Manifests", icon: "📋", fn: manifestsQuery },
];

export default function MetadataExplorerFeature() {
  const { tables, selectedTable, setSelectedTable, loading: tLoading } = useTableList();
  const [activeTab, setActiveTab] = useState("snapshots");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = async (tab) => {
    setActiveTab(tab);
    if (!selectedTable) return;
    setLoading(true); setError(""); setResult(null);
    try {
      const fn = TABS.find(t => t.key === tab).fn;
      const res = await executeQuery(fn(selectedTable));
      setResult(res);
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  };

  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="메타데이터 탐색기란?"
        description="Iceberg는 테이블 데이터 외에 풍부한 메타데이터를 관리합니다: 스냅샷 이력, 변경 히스토리, 데이터 파일 목록, 파티션 정보, 매니페스트. 이 메타데이터를 통해 테이블의 과거와 현재를 완전히 이해할 수 있습니다."
        sqlExample={`SELECT * FROM "table$snapshots";\nSELECT * FROM "table$files";\nSELECT * FROM "table$partitions";`}
        bookRef="Ch.2 Metadata Layer (p.33-43)"
      />
      <TableSelector tables={tables} selected={selectedTable} onChange={setSelectedTable} loading={tLoading} />

      <div className="iceberg-tabs">
        {TABS.map(tab => (
          <button key={tab.key} className={activeTab === tab.key ? "active" : ""} onClick={() => load(tab.key)}>
            {tab.icon} {tab.label}
          </button>
        ))}
      </div>

      {error && <div className="iceberg-error">{error}</div>}
      {result && <SqlResultTable columns={result.columns} rows={result.rows || []} loading={loading} />}
      {!result && !loading && <div className="iceberg-hint">Select a tab and click to load metadata</div>}
    </div>
  );
}
