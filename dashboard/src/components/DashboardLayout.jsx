import React, { useState, useEffect, useCallback } from "react";
import { NavLink, Outlet } from "react-router-dom";
import HealthPanel from "./HealthPanel.jsx";

/**
 * DashboardLayout — Main layout wrapper with header, sidebar navigation, and content area.
 *
 * Uses React Router <Outlet> to render child routes in the main content area.
 * Sidebar provides persistent navigation across all dashboard pages.
 */

const NAV_ITEMS = [
  {
    to: "/query",
    label: "SQL Query",
    icon: "\u276f_",
    description: "Ad-hoc Trino SQL",
  },
  {
    to: "/iceberg",
    label: "Iceberg Features",
    icon: "\u2744",
    description: "Apache Iceberg 10대 기능 탐색기",
  },
  {
    to: "/entity-diff",
    label: "Entity Diff",
    icon: "\u0394",
    description: "Entity 변경감지 3-Level 드릴다운",
  },
  {
    to: "/raw-backup",
    label: "Raw Backup",
    icon: "\u2601",
    description: "Nucleus 폴더 Raw 백업 탐색기",
  },
  {
    to: "/pipeline-guide",
    label: "Pipeline Guide",
    icon: "\u25B6",
    description: "Nucleus Pipeline 커맨드 가이드",
  },
  {
    to: "/pipeline",
    label: "Pipeline Monitor",
    icon: "\uD83D\uDCCA",
    description: "5개 Iceberg 테이블 빠른 조회",
  },
];

export default function DashboardLayout() {
  const [health, setHealth] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const refreshHealth = useCallback(async () => {
    try {
      const res = await fetch("/health");
      setHealth(await res.json());
    } catch {
      setHealth({ status: "unreachable" });
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const iv = setInterval(refreshHealth, 30000);
    return () => clearInterval(iv);
  }, [refreshHealth]);

  return (
    <div className="dashboard-layout">
      {/* Header */}
      <header className="app-header">
        <div className="header-left">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed((c) => !c)}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? "\u2630" : "\u2715"}
          </button>
          <h1 className="logo">
            <span className="logo-icon">&#9670;</span> Lakehouse Digital Twin
          </h1>
          <span className="subtitle">
            Iceberg &middot; OpenUSD &middot; Isaac Sim
          </span>
        </div>
        <div className="header-right">
          <HealthPanel health={health} onRefresh={refreshHealth} />
        </div>
      </header>

      <div className="layout-body">
        {/* Sidebar Navigation */}
        <nav className={`sidebar ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
          <div className="sidebar-nav">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `sidebar-link ${isActive ? "sidebar-link-active" : ""}`
                }
                title={item.description}
              >
                <span className="sidebar-icon">{item.icon}</span>
                {!sidebarCollapsed && (
                  <div className="sidebar-label-group">
                    <span className="sidebar-label">{item.label}</span>
                    <span className="sidebar-desc">{item.description}</span>
                  </div>
                )}
              </NavLink>
            ))}
          </div>

          {/* Sidebar footer */}
          {!sidebarCollapsed && (
            <div className="sidebar-footer">
              <a
                href="/docs"
                target="_blank"
                rel="noopener noreferrer"
                className="sidebar-footer-link"
              >
                API Docs
              </a>
              <span className="sidebar-version">v1.0.0</span>
            </div>
          )}
        </nav>

        {/* Main Content Area */}
        <main className="main-content">
          <Outlet />
        </main>
      </div>

      {/* Footer */}
      <footer className="app-footer">
        <span>Lakehouse API v1.0.0</span>
        <span>&middot;</span>
        <span>Apache Iceberg + Trino + MinIO</span>
        <span>&middot;</span>
        <span>
          <a href="/docs" target="_blank" rel="noopener noreferrer">
            API Docs
          </a>
        </span>
      </footer>
    </div>
  );
}
