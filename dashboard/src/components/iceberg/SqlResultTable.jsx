import React from "react";

/**
 * SqlResultTable — Renders SQL query results as a table.
 * Handles both array rows ([[v1,v2,...]]) and object rows ([{col:v,...}]).
 */
export default function SqlResultTable({ columns, rows, loading, error, maxHeight = "400px" }) {
  if (loading) {
    return <div className="iceberg-loading">Executing query...</div>;
  }
  if (error) {
    return <div className="iceberg-error">{error}</div>;
  }
  if (!columns || columns.length === 0) {
    return <div className="iceberg-empty">No results</div>;
  }
  if (!rows || rows.length === 0) {
    return (
      <div>
        <div className="iceberg-table-wrap">
          <table className="iceberg-table">
            <thead><tr>{columns.map(c => <th key={c} className="iceberg-th">{c}</th>)}</tr></thead>
          </table>
        </div>
        <div className="iceberg-row-count">0 rows</div>
      </div>
    );
  }

  // Detect row format: array or object
  const isArrayRow = Array.isArray(rows[0]);

  const getCellValue = (row, colIndex, colName) => {
    if (isArrayRow) return row[colIndex];
    return row[colName];
  };

  return (
    <div className="iceberg-table-wrap" style={{ maxHeight, overflow: "auto" }}>
      <table className="iceberg-table">
        <thead>
          <tr>
            <th className="iceberg-th">#</th>
            {columns.map((col) => (
              <th key={col} className="iceberg-th">{col}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "iceberg-tr-even" : ""}>
              <td className="iceberg-td iceberg-td-num">{i + 1}</td>
              {columns.map((col, ci) => (
                <td key={ci} className="iceberg-td">
                  {formatCell(getCellValue(row, ci, col))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="iceberg-row-count">{rows.length} rows</div>
    </div>
  );
}

function formatCell(value) {
  if (value === null || value === undefined) return <span className="iceberg-null">NULL</span>;
  if (typeof value === "object") return JSON.stringify(value);
  const s = String(value);
  if (s.length > 120) return s.slice(0, 120) + "\u2026";
  return s;
}
