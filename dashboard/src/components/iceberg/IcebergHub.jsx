import React, { useState } from "react";
import FeatureCard from "./FeatureCard.jsx";
import TimeTravelFeature from "./TimeTravelFeature.jsx";
import SchemaEvolutionFeature from "./SchemaEvolutionFeature.jsx";
import PartitionEvolutionFeature from "./PartitionEvolutionFeature.jsx";
import CompactionFeature from "./CompactionFeature.jsx";
import HiddenPartitioningFeature from "./HiddenPartitioningFeature.jsx";
import SortingFeature from "./SortingFeature.jsx";
import CowMorFeature from "./CowMorFeature.jsx";
import AcidFeature from "./AcidFeature.jsx";
import MaintenanceFeature from "./MaintenanceFeature.jsx";
import MetadataExplorerFeature from "./MetadataExplorerFeature.jsx";
import "./iceberg.css";

const FEATURES = [
  { id: "time-travel", icon: "⏰", title: "Time Travel", desc: "과거 시점 데이터 조회 & 스냅샷 비교", component: TimeTravelFeature },
  { id: "schema", icon: "📐", title: "Schema Evolution", desc: "무중단 스키마 변경 (추가/삭제/이름변경)", component: SchemaEvolutionFeature },
  { id: "partition", icon: "📦", title: "Partition Evolution", desc: "데이터 재작성 없이 파티셔닝 전략 변경", component: PartitionEvolutionFeature },
  { id: "compaction", icon: "🗜️", title: "Compaction", desc: "작은 파일 병합으로 쿼리 성능 향상", component: CompactionFeature },
  { id: "hidden-part", icon: "🔮", title: "Hidden Partitioning", desc: "자동 파티션 프루닝 & Transform 함수", component: HiddenPartitioningFeature },
  { id: "sorting", icon: "📊", title: "Sorting & Z-ordering", desc: "데이터 클러스터링으로 스캔 최적화", component: SortingFeature },
  { id: "cow-mor", icon: "🔄", title: "COW vs MOR", desc: "읽기/쓰기 중심 테이블 전략 선택", component: CowMorFeature },
  { id: "acid", icon: "🔒", title: "ACID Transactions", desc: "동시 읽기/쓰기 데이터 일관성 보장", component: AcidFeature },
  { id: "maintenance", icon: "🔧", title: "Table Maintenance", desc: "스냅샷 만료 & 유지보수 스케줄", component: MaintenanceFeature },
  { id: "metadata", icon: "🔍", title: "Metadata Explorer", desc: "스냅샷/파일/파티션/매니페스트 탐색", component: MetadataExplorerFeature },
];

export default function IcebergHub() {
  const [activeFeature, setActiveFeature] = useState(null);

  const ActiveComponent = activeFeature
    ? FEATURES.find(f => f.id === activeFeature)?.component
    : null;

  return (
    <div className="iceberg-hub">
      {/* Header */}
      <div className="iceberg-hub-header">
        <h2>
          <span className="iceberg-hub-icon">❄️</span>
          Apache Iceberg Features
        </h2>
        <p className="iceberg-hub-subtitle">
          10대 핵심 기능을 시각적으로 탐색하고 실행하세요. IoT + OpenUSD 데이터를 효율적으로 관리합니다.
        </p>
      </div>

      {/* Feature Grid */}
      {!activeFeature && (
        <div className="iceberg-card-grid">
          {FEATURES.map(f => (
            <FeatureCard
              key={f.id}
              icon={f.icon}
              title={f.title}
              description={f.desc}
              isActive={false}
              onClick={() => setActiveFeature(f.id)}
            />
          ))}
        </div>
      )}

      {/* Active Feature Detail */}
      {activeFeature && (
        <div className="iceberg-detail">
          <button className="iceberg-back-btn" onClick={() => setActiveFeature(null)}>
            ← Back to Features
          </button>
          <h3 className="iceberg-detail-title">
            {FEATURES.find(f => f.id === activeFeature)?.icon}{" "}
            {FEATURES.find(f => f.id === activeFeature)?.title}
          </h3>
          {ActiveComponent && <ActiveComponent />}
        </div>
      )}
    </div>
  );
}
