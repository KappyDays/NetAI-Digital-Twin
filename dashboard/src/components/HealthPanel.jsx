import React from "react";

export default function HealthPanel({ health, onRefresh }) {
  if (!health) {
    return <span className="badge badge-degraded">connecting...</span>;
  }

  const statusClass = {
    healthy: "badge-healthy",
    degraded: "badge-degraded",
    unreachable: "badge-unreachable",
  }[health.status] || "badge-degraded";

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      <span className={`badge ${statusClass}`}>{health.status}</span>
      {health.uptime_seconds != null && (
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          up {Math.floor(health.uptime_seconds / 60)}m
        </span>
      )}
      <button
        className="btn"
        onClick={onRefresh}
        style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem" }}
        title="Refresh health"
      >
        &#8635;
      </button>
    </div>
  );
}
