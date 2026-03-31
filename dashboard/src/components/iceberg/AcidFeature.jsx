import React from "react";
import InfoPanel from "./InfoPanel.jsx";

export default function AcidFeature() {
  return (
    <div className="iceberg-feature">
      <InfoPanel
        title="ACID 트랜잭션이란?"
        description="Iceberg는 데이터 레이크 위에서 ACID(Atomicity, Consistency, Isolation, Durability) 트랜잭션을 보장합니다. 동시에 여러 작업이 실행되어도 데이터 일관성이 유지됩니다. 낙관적 동시성 제어(Optimistic Concurrency Control)를 사용하여 충돌 시 자동 재시도합니다."
        sqlExample={`-- Iceberg는 모든 INSERT/DELETE/UPDATE가 원자적\nINSERT INTO t VALUES (...);\n-- 실패 시 이전 스냅샷으로 자동 롤백`}
        bookRef="Ch.9 ACID Transactions (p.127-133)"
      />

      <div className="iceberg-acid-grid">
        {[
          { letter: "A", name: "Atomicity (원자성)", desc: "모든 변경이 전부 적용되거나, 전부 취소됩니다. 부분 적용은 없습니다.", icon: "⚛️" },
          { letter: "C", name: "Consistency (일관성)", desc: "트랜잭션 전후 데이터는 항상 유효한 상태입니다. 스키마 위반 데이터는 거부됩니다.", icon: "✅" },
          { letter: "I", name: "Isolation (격리성)", desc: "동시에 실행되는 쿼리들은 서로의 중간 상태를 볼 수 없습니다. 스냅샷 격리를 제공합니다.", icon: "🔒" },
          { letter: "D", name: "Durability (지속성)", desc: "커밋된 데이터는 시스템 장애에도 보존됩니다. S3/MinIO에 영구 저장됩니다.", icon: "💾" },
        ].map(p => (
          <div key={p.letter} className="iceberg-acid-card">
            <div className="iceberg-acid-letter">{p.icon} {p.letter}</div>
            <h4>{p.name}</h4>
            <p>{p.desc}</p>
          </div>
        ))}
      </div>

      <div className="iceberg-section">
        <h4>Optimistic Concurrency Control</h4>
        <div className="iceberg-occ-diagram">
          <div className="iceberg-occ-step">
            <div className="iceberg-occ-num">1</div>
            <div>Writer A reads snapshot #5</div>
          </div>
          <div className="iceberg-occ-step">
            <div className="iceberg-occ-num">2</div>
            <div>Writer B reads snapshot #5</div>
          </div>
          <div className="iceberg-occ-step">
            <div className="iceberg-occ-num">3</div>
            <div>Writer A commits → snapshot #6 ✅</div>
          </div>
          <div className="iceberg-occ-step">
            <div className="iceberg-occ-num">4</div>
            <div>Writer B tries to commit → conflict detected → retry from #6 🔄</div>
          </div>
        </div>
      </div>
    </div>
  );
}
