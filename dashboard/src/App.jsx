import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import DashboardLayout from "./components/DashboardLayout.jsx";
import QueryPage from "./pages/QueryPage.jsx";
import IcebergPage from "./pages/IcebergPage.jsx";
import EntityDiffPage from "./pages/EntityDiffPage.jsx";
import RawBackupPage from "./pages/RawBackupPage.jsx";
import PipelineGuidePage from "./pages/PipelineGuidePage.jsx";
import PipelineMonitorPage from "./pages/PipelineMonitorPage.jsx";
import "./App.css";

export default function App() {
  return (
    <Routes>
      <Route element={<DashboardLayout />}>
        <Route index element={<Navigate to="/entity-diff" replace />} />
        <Route path="query" element={<QueryPage />} />
        <Route path="iceberg" element={<IcebergPage />} />
        <Route path="entity-diff" element={<EntityDiffPage />} />
        <Route path="raw-backup" element={<RawBackupPage />} />
        <Route path="pipeline-guide" element={<PipelineGuidePage />} />
        <Route path="pipeline" element={<PipelineMonitorPage />} />
        <Route path="*" element={<Navigate to="/entity-diff" replace />} />
      </Route>
    </Routes>
  );
}
