import React from "react";

/**
 * TableSelector — Dropdown to pick an Iceberg table.
 */
export default function TableSelector({ tables, selected, onChange, loading }) {
  return (
    <div className="iceberg-table-selector">
      <label>Table:</label>
      <select
        value={selected}
        onChange={e => onChange(e.target.value)}
        disabled={loading}
      >
        {loading && <option>Loading...</option>}
        {tables.map(t => <option key={t} value={t}>{t}</option>)}
      </select>
    </div>
  );
}
