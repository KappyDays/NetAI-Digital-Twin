import React from "react";
import InfoPanel from "./InfoPanel.jsx";

const TRANSFORMS = [
  { name: "year(ts)", desc: "연도 기반 파티셔닝", example: "PARTITIONED BY year(timestamp)", color: "#3b82f6" },
  { name: "month(ts)", desc: "월+연도 기반", example: "PARTITIONED BY months(timestamp)", color: "#6366f1" },
  { name: "day(ts)", desc: "일+월+연도", example: "PARTITIONED BY days(timestamp)", color: "#8b5cf6" },
  { name: "hour(ts)", desc: "시+일+월+연도", example: "PARTITIONED BY hours(timestamp)", color: "#a855f7" },
  { name: "bucket(N, col)", desc: "해시 기반 N개 버킷 분배", example: "PARTITIONED BY bucket(24, space_id)", color: "#06b6d4" },
  { name: "truncate(N, col)", desc: "값의 앞 N자리로 그룹화", example: "PARTITIONED BY truncate(name, 1)", color: "#14b8a6" },
];

export default function HiddenPartitioningFeature() {
  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="Hidden Partitioning이란?"
        description="Hive는 사용자가 파생 컬럼을 직접 생성하고 필터링해야 파티션 이점을 얻었습니다. Iceberg의 Hidden Partitioning은 원본 컬럼만 필터해도 자동으로 파티션 프루닝이 적용됩니다. 사용자는 파티셔닝의 존재를 몰라도 됩니다."
        sqlExample={`-- Hive: 파생 컬럼 필수\nSELECT * FROM events WHERE month = 3;\n\n-- Iceberg: 원본 컬럼만으로 자동 프루닝\nSELECT * FROM events WHERE timestamp > '2026-03-01';`}
        bookRef="Ch.4 Hidden Partitioning (p.83-86)"
      />

      <h4>Transform Functions</h4>
      <div className="iceberg-transform-grid">
        {TRANSFORMS.map(t => (
          <div key={t.name} className="iceberg-transform-card" style={{ borderLeftColor: t.color }}>
            <div className="iceberg-transform-name" style={{ color: t.color }}>{t.name}</div>
            <div className="iceberg-transform-desc">{t.desc}</div>
            <pre className="iceberg-transform-example">{t.example}</pre>
          </div>
        ))}
      </div>

      <div className="iceberg-section">
        <h4>Digital Twin 추천</h4>
        <table className="iceberg-table">
          <thead><tr><th className="iceberg-th">테이블</th><th className="iceberg-th">추천 파티셔닝</th><th className="iceberg-th">이유</th></tr></thead>
          <tbody>
            <tr><td className="iceberg-td">dynamic_*</td><td className="iceberg-td">hour(timestamp)</td><td className="iceberg-td">시간 기반 센서 쿼리 최적화</td></tr>
            <tr><td className="iceberg-td">static_prims</td><td className="iceberg-td">bucket(space_id, 8)</td><td className="iceberg-td">공간별 균등 분배</td></tr>
            <tr><td className="iceberg-td">congestion</td><td className="iceberg-td">day(timestamp)</td><td className="iceberg-td">일별 집계 최적화</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
