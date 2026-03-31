import React, { useState } from "react";

/**
 * InfoPanel — Collapsible explanation panel for each Iceberg feature.
 * Shows "What is this?" description + SQL example for demos.
 */
export default function InfoPanel({ title, description, sqlExample, bookRef }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="iceberg-info-panel">
      <button className="iceberg-info-toggle" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} {title || "이 기능이 뭔가요?"}
      </button>
      {open && (
        <div className="iceberg-info-body">
          <p className="iceberg-info-desc">{description}</p>
          {sqlExample && (
            <pre className="iceberg-info-sql">{sqlExample}</pre>
          )}
          {bookRef && (
            <p className="iceberg-info-ref">📖 {bookRef}</p>
          )}
        </div>
      )}
    </div>
  );
}
