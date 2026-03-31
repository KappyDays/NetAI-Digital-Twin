import React from "react";

/**
 * FeatureCard — Clickable card for each Iceberg feature in the hub grid.
 */
export default function FeatureCard({ icon, title, description, isActive, onClick }) {
  return (
    <button
      className={`iceberg-card ${isActive ? "iceberg-card-active" : ""}`}
      onClick={onClick}
    >
      <span className="iceberg-card-icon">{icon}</span>
      <span className="iceberg-card-title">{title}</span>
      <span className="iceberg-card-desc">{description}</span>
    </button>
  );
}
