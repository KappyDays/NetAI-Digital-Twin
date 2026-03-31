import React from "react";
import { Routes, Route } from "react-router-dom";
import DashboardLayout from "./components/DashboardLayout.jsx";
import CongestionPage from "./pages/CongestionPage.jsx";
import StaticPage from "./pages/StaticPage.jsx";
import DynamicPage from "./pages/DynamicPage.jsx";
import QueryPage from "./pages/QueryPage.jsx";
import IcebergPage from "./pages/IcebergPage.jsx";
import EntityDiffPage from "./pages/EntityDiffPage.jsx";
import RawBackupPage from "./pages/RawBackupPage.jsx";
import "./App.css";

/**
 * App — Root component with React Router routing.
 *
 * Routes:
 *   /           — Congestion heatmap (default)
 *   /static     — Static object browser
 *   /dynamic    — Dynamic sensor data
 *   /query      — Ad-hoc SQL query
 */
export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<CongestionPage />} />
        <Route path="static" element={<StaticPage />} />
        <Route path="dynamic" element={<DynamicPage />} />
        <Route path="query" element={<QueryPage />} />
        <Route path="iceberg" element={<IcebergPage />} />
        <Route path="entity-diff" element={<EntityDiffPage />} />
        <Route path="raw-backup" element={<RawBackupPage />} />
        {/* Catch-all: redirect to congestion page */}
        <Route path="*" element={<CongestionPage />} />
      </Route>
    </Routes>
  );
}
