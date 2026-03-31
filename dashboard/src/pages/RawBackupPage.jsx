import React, { useState, useEffect, useCallback } from "react";
import SqlResultTable from "../components/iceberg/SqlResultTable.jsx";

/**
 * RawBackupPage — View Nucleus raw backup snapshots stored in Iceberg.
 *
 * Features:
 *   - List all backup timestamps (per folder)
 *   - View file list at a specific backup time
 *   - Compare two backup times (diff: new/modified/deleted)
 */

const API = "/api/v1";

export default function RawBackupPage() {
  const [backupTimes, setBackupTimes] = useState([]);
  const [snapshots, setSnapshots] = useState([]);
  const [selectedTime, setSelectedTime] = useState(null);
  const [compareTimeA, setCompareTimeA] = useState(null);
  const [compareTimeB, setCompareTimeB] = useState(null);
  const [files, setFiles] = useState([]);
  const [diffFiles, setDiffFiles] = useState(null);
  const [diffSummary, setDiffSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [view, setView] = useState("list"); // "list" | "diff"

  // Fetch backup times on mount
  useEffect(() => {
    fetchBackupTimes();
  }, []);

  const fetchBackupTimes = async () => {
    try {
      const res = await fetch(`${API}/raw-backup/times`);
      const data = await res.json();
      setBackupTimes(data.backup_times || []);
      setSnapshots(data.snapshots || []);
    } catch (e) {
      setError("Failed to fetch backup times: " + e.message);
    }
  };

  const fetchFiles = useCallback(async (bt) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/raw-backup/list?backup_time=${encodeURIComponent(bt)}`);
      const data = await res.json();
      setFiles(data.files || []);
      setSelectedTime(bt);
      setView("list");
    } catch (e) {
      setError("Failed to fetch files: " + e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchDiff = useCallback(async () => {
    if (!compareTimeA || !compareTimeB) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API}/raw-backup/diff?time_a=${encodeURIComponent(compareTimeA)}&time_b=${encodeURIComponent(compareTimeB)}`
      );
      const data = await res.json();
      setDiffFiles(data.files || []);
      setDiffSummary({ new: data.new, modified: data.modified, deleted: data.deleted, unchanged: data.unchanged });
      setView("diff");
    } catch (e) {
      setError("Failed to fetch diff: " + e.message);
    } finally {
      setLoading(false);
    }
  }, [compareTimeA, compareTimeB]);

  const fileColumns = ["file_path", "file_name", "file_extension", "file_size", "modified_time", "s3_key", "status"];
  const diffColumns = ["file_path", "file_name", "file_extension", "file_size", "modified_time", "status"];

  return (
    <div style={{ padding: "20px" }}>
      <h2 style={{ color: "#e0e0e0", marginBottom: "16px" }}>Raw Backup Explorer</h2>

      {error && <div style={{ color: "#ff6b6b", marginBottom: "12px", padding: "8px", background: "#2a1a1a", borderRadius: "4px" }}>{error}</div>}

      {/* Backup Times */}
      <div style={{ display: "flex", gap: "24px", marginBottom: "20px" }}>
        <div style={{ flex: 1 }}>
          <h3 style={{ color: "#aaa", fontSize: "14px", marginBottom: "8px" }}>Backup Snapshots ({backupTimes.length})</h3>
          <div style={{ maxHeight: "200px", overflow: "auto", background: "#1e1e2e", borderRadius: "6px", padding: "8px" }}>
            {snapshots.length === 0 ? (
              <div style={{ color: "#666", padding: "12px" }}>No backups found</div>
            ) : (
              snapshots.map((snap, i) => {
                const folderName = snap.folder_path ? snap.folder_path.split("/").filter(Boolean).pop() : "";
                return (
                  <div
                    key={i}
                    style={{
                      padding: "6px 10px",
                      cursor: "pointer",
                      borderRadius: "4px",
                      background: selectedTime === snap.backup_time ? "#3a3a5e" : "transparent",
                      color: selectedTime === snap.backup_time ? "#7ecfff" : "#ccc",
                      fontSize: "13px",
                      fontFamily: "monospace",
                      display: "flex",
                      gap: "8px",
                      alignItems: "center",
                    }}
                    onClick={() => fetchFiles(snap.backup_time)}
                  >
                    {folderName && (
                      <span style={{
                        background: "#2a4a6a",
                        color: "#7ecfff",
                        padding: "1px 6px",
                        borderRadius: "3px",
                        fontSize: "11px",
                        flexShrink: 0,
                      }}>
                        {folderName}
                      </span>
                    )}
                    <span>{snap.backup_time}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Diff Comparison */}
        <div style={{ flex: 1 }}>
          <h3 style={{ color: "#aaa", fontSize: "14px", marginBottom: "8px" }}>Compare Two Snapshots</h3>
          <div style={{ background: "#1e1e2e", borderRadius: "6px", padding: "12px" }}>
            <div style={{ marginBottom: "8px" }}>
              <label style={{ color: "#888", fontSize: "12px" }}>Time A (before): </label>
              <select
                value={compareTimeA || ""}
                onChange={(e) => setCompareTimeA(e.target.value || null)}
                style={{ background: "#2a2a3e", color: "#ccc", border: "1px solid #444", borderRadius: "4px", padding: "4px 8px", fontSize: "12px", fontFamily: "monospace" }}
              >
                <option value="">Select...</option>
                {backupTimes.map((bt, i) => <option key={i} value={bt}>{bt}</option>)}
              </select>
            </div>
            <div style={{ marginBottom: "8px" }}>
              <label style={{ color: "#888", fontSize: "12px" }}>Time B (after):  </label>
              <select
                value={compareTimeB || ""}
                onChange={(e) => setCompareTimeB(e.target.value || null)}
                style={{ background: "#2a2a3e", color: "#ccc", border: "1px solid #444", borderRadius: "4px", padding: "4px 8px", fontSize: "12px", fontFamily: "monospace" }}
              >
                <option value="">Select...</option>
                {backupTimes.map((bt, i) => <option key={i} value={bt}>{bt}</option>)}
              </select>
            </div>
            <button
              onClick={fetchDiff}
              disabled={!compareTimeA || !compareTimeB || loading}
              style={{
                background: compareTimeA && compareTimeB ? "#4a6fa5" : "#333",
                color: "#fff",
                border: "none",
                borderRadius: "4px",
                padding: "6px 16px",
                cursor: compareTimeA && compareTimeB ? "pointer" : "not-allowed",
                fontSize: "13px",
              }}
            >
              Compare
            </button>
          </div>
        </div>
      </div>

      {/* Results */}
      {view === "list" && selectedTime && (
        <div>
          <h3 style={{ color: "#aaa", fontSize: "14px", marginBottom: "8px" }}>
            Files at {selectedTime} ({files.length} files)
          </h3>
          <SqlResultTable
            columns={fileColumns}
            rows={files}
            loading={loading}
            error={null}
            maxHeight="500px"
          />
        </div>
      )}

      {view === "diff" && diffSummary && (
        <div>
          <h3 style={{ color: "#aaa", fontSize: "14px", marginBottom: "8px" }}>
            Diff: {compareTimeA} vs {compareTimeB}
          </h3>
          <div style={{ display: "flex", gap: "12px", marginBottom: "12px" }}>
            {[
              { label: "New", count: diffSummary.new, color: "#4caf50" },
              { label: "Modified", count: diffSummary.modified, color: "#ff9800" },
              { label: "Deleted", count: diffSummary.deleted, color: "#f44336" },
            ].map(({ label, count, color }) => (
              <div
                key={label}
                style={{
                  background: "#1e1e2e",
                  borderRadius: "6px",
                  padding: "10px 20px",
                  borderLeft: `3px solid ${color}`,
                }}
              >
                <div style={{ color: "#888", fontSize: "11px" }}>{label}</div>
                <div style={{ color, fontSize: "20px", fontWeight: "bold" }}>{count}</div>
              </div>
            ))}
          </div>
          <SqlResultTable
            columns={diffColumns}
            rows={diffFiles}
            loading={loading}
            error={null}
            maxHeight="500px"
          />
        </div>
      )}
    </div>
  );
}
