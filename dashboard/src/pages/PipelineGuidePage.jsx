import React, { useState, useRef, useEffect, useCallback } from "react";

const RUNNER_DEFAULT = "localhost:8200";
const WORKING_DIR =
  "C:\\Users\\kang\\workspace\\branch\\NetAI-Digital-Twin\\nucleus_pipeline";

const COMMANDS = [
  {
    title: "Task 1 (Raw Backup) 실행",
    items: [
      {
        comment: "# Nucleus 서버 폴더 백업",
        cmd: `python main.py --raw-backup --nucleus-folder {nucleus_folder} --api-url {api_url}`,
        placeholders: {
          nucleus_folder: { label: "Nucleus Folder URI", default: "omniverse://10.38.38.48/Projects/Dream-AI+Twin/" },
          api_url: { label: "API URL", default: "http://localhost:8100" },
        },
      },
    ],
  },
  {
    title: "Task 2 (Entity Backup) 실행",
    items: [
      {
        comment: "# Nucleus 서버 USD 파일 백업",
        cmd: `python main.py --nucleus-path {nucleus_path} --api-url {api_url}`,
        placeholders: {
          nucleus_path: { label: "Nucleus USD Path", default: "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI+Twin.usd" },
          api_url: { label: "API URL", default: "http://localhost:8100" },
        },
      },
      {
        comment: "# 또는 로컬 파일로 테스트",
        cmd: `python main.py --local-path {local_path} --api-url {api_url}`,
        placeholders: {
          local_path: { label: "Local USD Path", default: "./AI-Grad_Building.usda" },
          api_url: { label: "API URL", default: "http://localhost:8100" },
        },
      },
    ],
  },
  {
    title: "Task 1 + Task 2 동시 실행 (Full Backup)",
    items: [
      {
        cmd: `python main.py --full-backup \\\n    --nucleus-folder {nucleus_folder} \\\n    --nucleus-path {nucleus_path} \\\n    --api-url {api_url}`,
        placeholders: {
          nucleus_folder: { label: "Nucleus Folder URI", default: "omniverse://10.38.38.48/Projects/Dream-AI+Twin/" },
          nucleus_path: { label: "Nucleus USD Path", default: "omniverse://10.38.38.48/Projects/Dream-AI+Twin/Dream-AI+Twin.usd" },
          api_url: { label: "API URL", default: "http://localhost:8100" },
        },
      },
    ],
  },
];

const OPTIONS = [
  {
    option: "--api-url",
    desc: "Lakehouse API 주소 (기본: http://localhost:8100)",
  },
  { option: "--nucleus-token", desc: "Nucleus 인증 토큰 (필요 시)" },
  { option: "--skip-usd-upload", desc: "USD 파일 MinIO 업로드 스킵" },
  {
    option: "--backup-source",
    desc: '백업 소스 식별자 (local / nucleus)',
  },
];

/* ── Runner WebSocket hook ───────────────────────────── */

function useRunner(url) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [lines, setLines] = useState([]);

  const connect = useCallback(() => {
    if (wsRef.current) return;
    const wsUrl = `ws://${url}/ws/run`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      setConnected(true);
      setLines((prev) => [
        ...prev,
        { text: `Connected to runner (${url})\n`, color: "#58a6ff" },
      ]);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        const colorMap = {
          stdout: "#e6edf3",
          stderr: "#f0883e",
          info: "#58a6ff",
          error: "#f85149",
        };
        if (msg.type === "exit") {
          const ok = msg.code === 0;
          setLines((prev) => [
            ...prev,
            {
              text: `\nProcess exited with code ${msg.code}\n`,
              color: ok ? "#3fb950" : "#f85149",
            },
          ]);
          setRunning(false);
        } else {
          setLines((prev) => [
            ...prev,
            { text: msg.data, color: colorMap[msg.type] || "#e6edf3" },
          ]);
        }
      } catch {
        /* ignore parse errors */
      }
    };

    ws.onclose = () => {
      setConnected(false);
      setRunning(false);
      wsRef.current = null;
      setLines((prev) => [
        ...prev,
        { text: "Disconnected from runner\n", color: "#8b949e" },
      ]);
    };

    ws.onerror = () => {
      setConnected(false);
      setRunning(false);
      wsRef.current = null;
    };

    wsRef.current = ws;
  }, [url]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
    setRunning(false);
  }, []);

  const run = useCallback(
    (command) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      setRunning(true);
      wsRef.current.send(JSON.stringify({ action: "run", command }));
    },
    []
  );

  const kill = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({ action: "kill" }));
  }, []);

  const clearLines = useCallback(() => setLines([]), []);

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  return { connected, running, lines, connect, disconnect, run, kill, clearLines };
}

/* ── Components ──────────────────────────────────────── */

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard not available */
    }
  };
  return (
    <button
      className="btn"
      onClick={handleCopy}
      style={{ fontSize: "0.65rem", padding: "0.2rem 0.5rem", opacity: 0.7 }}
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

function CommandBlock({ comment, cmd, placeholders = {}, onRun, isRunning, isConnected }) {
  const placeholderKeys = Object.keys(placeholders);
  const hasFill = placeholderKeys.length > 0;

  const resolveCmd = (vals) =>
    cmd.replace(/\{(\w+)\}/g, (_, k) => vals[k] ?? `{${k}}`);

  const [values, setValues] = useState(() =>
    Object.fromEntries(placeholderKeys.map((k) => [k, placeholders[k].default]))
  );
  const [showFill, setShowFill] = useState(false);
  const [editedCmd, setEditedCmd] = useState(() => resolveCmd(
    Object.fromEntries(placeholderKeys.map((k) => [k, placeholders[k].default]))
  ));
  const [editing, setEditing] = useState(false);

  const handleValueChange = (key, val) => {
    const newVals = { ...values, [key]: val };
    setValues(newVals);
    if (!editing) setEditedCmd(resolveCmd(newVals));
  };

  const preRadius = showFill
    ? "var(--radius) var(--radius) 0 0"
    : "var(--radius)";

  return (
    <div style={{ marginBottom: "0.5rem" }}>
      {editing ? (
        <div>
          <textarea
            value={editedCmd}
            onChange={(e) => setEditedCmd(e.target.value)}
            spellCheck={false}
            style={{
              width: "100%",
              minHeight: "80px",
              background: "var(--bg-primary)",
              border: "1px solid var(--accent, #58a6ff)",
              borderRadius: "var(--radius)",
              padding: "0.75rem",
              fontFamily: "'Cascadia Code', 'Fira Code', monospace",
              fontSize: "0.8rem",
              lineHeight: 1.6,
              color: "var(--text-primary)",
              resize: "vertical",
            }}
          />
          <div
            style={{
              display: "flex",
              gap: "0.3rem",
              justifyContent: "flex-end",
              marginTop: "0.3rem",
            }}
          >
            <button
              className="btn"
              style={{ fontSize: "0.65rem" }}
              onClick={() => setEditing(false)}
            >
              Done
            </button>
            <button
              className="btn"
              style={{ fontSize: "0.65rem" }}
              onClick={() => {
                setEditedCmd(resolveCmd(values));
                setEditing(false);
              }}
            >
              Reset
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div style={{ position: "relative" }}>
            <pre
              style={{
                background: "var(--bg-primary)",
                border: "1px solid var(--border)",
                borderBottom: showFill ? "none" : "1px solid var(--border)",
                borderRadius: preRadius,
                padding: `0.75rem ${hasFill ? "12rem" : "8rem"} 0.75rem 0.75rem`,
                margin: 0,
                overflowX: "auto",
                fontSize: "0.8rem",
                fontFamily: "'Cascadia Code', 'Fira Code', monospace",
                lineHeight: 1.6,
                color: "var(--text-primary)",
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                cursor: "pointer",
              }}
              onClick={() => { setEditing(true); setShowFill(false); }}
              title="Click to edit"
            >
              {comment && (
                <span style={{ color: "#6ec86e" }}>
                  {comment}
                  {"\n"}
                </span>
              )}
              <span>{editedCmd}</span>
            </pre>
            <div
              style={{
                position: "absolute",
                top: "0.5rem",
                right: "0.5rem",
                display: "flex",
                gap: "0.3rem",
              }}
            >
              <button
                className="btn btn-primary"
                onClick={() => onRun(editedCmd)}
                disabled={isRunning || !isConnected}
                style={{
                  fontSize: "0.65rem",
                  padding: "0.2rem 0.6rem",
                  opacity: isConnected ? 1 : 0.4,
                }}
                title={
                  !isConnected
                    ? "Runner에 연결하세요"
                    : isRunning
                    ? "실행 중..."
                    : "명령 실행"
                }
              >
                {isRunning ? "Running..." : "Run"}
              </button>
              {hasFill && (
                <button
                  className="btn"
                  onClick={() => setShowFill((v) => !v)}
                  style={{
                    fontSize: "0.65rem",
                    padding: "0.2rem 0.5rem",
                    borderColor: showFill ? "var(--accent, #58a6ff)" : undefined,
                    color: showFill ? "var(--accent, #58a6ff)" : undefined,
                  }}
                  title="파라미터 값 입력"
                >
                  Fill
                </button>
              )}
              <CopyButton text={editedCmd} />
            </div>
          </div>

          {hasFill && showFill && (
            <div
              style={{
                background: "var(--bg-primary)",
                border: "1px solid var(--border)",
                borderTop: "1px solid var(--accent, #58a6ff)",
                borderRadius: "0 0 var(--radius) var(--radius)",
                padding: "0.6rem 0.75rem",
                display: "grid",
                gridTemplateColumns: "auto 1fr",
                gap: "0.4rem 0.75rem",
                alignItems: "center",
              }}
            >
              {placeholderKeys.map((key) => (
                <React.Fragment key={key}>
                  <label
                    style={{
                      fontSize: "0.7rem",
                      color: "var(--text-muted)",
                      fontFamily: "'Cascadia Code', 'Fira Code', monospace",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {placeholders[key].label}
                  </label>
                  <input
                    type="text"
                    value={values[key]}
                    onChange={(e) => handleValueChange(key, e.target.value)}
                    style={{
                      background: "var(--bg-secondary)",
                      border: "1px solid var(--border)",
                      borderRadius: "var(--radius)",
                      padding: "0.25rem 0.5rem",
                      fontSize: "0.72rem",
                      fontFamily: "'Cascadia Code', 'Fira Code', monospace",
                      color: "var(--text-primary)",
                      width: "100%",
                    }}
                  />
                </React.Fragment>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Terminal({ lines, onClear, onKill, isRunning }) {
  const termRef = useRef(null);

  useEffect(() => {
    if (termRef.current) {
      termRef.current.scrollTop = termRef.current.scrollHeight;
    }
  }, [lines]);

  return (
    <div className="card" style={{ marginBottom: "1rem" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "0.5rem",
        }}
      >
        <div className="card-title" style={{ margin: 0 }}>
          Terminal Output
        </div>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          {isRunning && (
            <button
              className="btn"
              onClick={onKill}
              style={{
                fontSize: "0.65rem",
                borderColor: "var(--danger, #f85149)",
                color: "var(--danger, #f85149)",
              }}
            >
              Kill
            </button>
          )}
          <button
            className="btn"
            onClick={onClear}
            style={{ fontSize: "0.65rem" }}
          >
            Clear
          </button>
        </div>
      </div>
      <div
        ref={termRef}
        style={{
          background: "#0d1117",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "0.75rem",
          height: "320px",
          overflowY: "auto",
          fontFamily: "'Cascadia Code', 'Fira Code', monospace",
          fontSize: "0.78rem",
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-all",
        }}
      >
        {lines.length === 0 ? (
          <span style={{ color: "#6e7681" }}>
            Ready. Runner에 연결한 후 "Run" 버튼으로 명령을 실행하세요.
          </span>
        ) : (
          lines.map((line, i) => (
            <span key={i} style={{ color: line.color }}>
              {line.text}
            </span>
          ))
        )}
      </div>
    </div>
  );
}

/* ── Main Page ───────────────────────────────────────── */

export default function PipelineGuidePage() {
  const [runnerUrl, setRunnerUrl] = useState(RUNNER_DEFAULT);
  const runner = useRunner(runnerUrl);

  return (
    <div>
      <h2 style={{ fontSize: "1.1rem", marginBottom: "0.25rem" }}>
        Nucleus Pipeline Commands
      </h2>
      <p
        style={{
          fontSize: "0.8rem",
          color: "var(--text-muted)",
          marginBottom: "1rem",
        }}
      >
        Task 1 (Raw Backup)과 Task 2 (Entity Backup) 명령을 확인하고 직접
        실행할 수 있습니다
      </p>

      {/* Runner connection bar */}
      <div
        className="card"
        style={{
          marginBottom: "1rem",
          borderColor: runner.connected
            ? "var(--success, #3fb950)"
            : "var(--border)",
          background: runner.connected
            ? "rgba(63, 185, 80, 0.05)"
            : undefined,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.75rem",
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              width: "8px",
              height: "8px",
              borderRadius: "50%",
              background: runner.connected ? "#3fb950" : "#6e7681",
              flexShrink: 0,
            }}
          />
          <span
            style={{
              fontSize: "0.8rem",
              fontWeight: 600,
              color: runner.connected
                ? "var(--success, #3fb950)"
                : "var(--text-muted)",
            }}
          >
            Pipeline Runner
          </span>

          <input
            type="text"
            value={runnerUrl}
            onChange={(e) => setRunnerUrl(e.target.value)}
            placeholder="localhost:8200"
            disabled={runner.connected}
            style={{
              background: "var(--bg-primary)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "0.3rem 0.5rem",
              fontSize: "0.75rem",
              fontFamily: "'Cascadia Code', 'Fira Code', monospace",
              color: "var(--text-primary)",
              width: "160px",
            }}
          />

          {runner.connected ? (
            <button
              className="btn"
              onClick={runner.disconnect}
              style={{ fontSize: "0.7rem" }}
            >
              Disconnect
            </button>
          ) : (
            <button
              className="btn btn-primary"
              onClick={runner.connect}
              style={{ fontSize: "0.7rem" }}
            >
              Connect
            </button>
          )}

          {!runner.connected && (
            <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              Runner 시작:{" "}
              <code
                style={{
                  background: "var(--bg-primary)",
                  padding: "0.1rem 0.3rem",
                  borderRadius: "3px",
                  fontSize: "0.68rem",
                }}
              >
                .venv\Scripts\python.exe runner_server.py
              </code>
            </span>
          )}
        </div>
      </div>

      {/* Working directory */}
      <div className="card" style={{ marginBottom: "1rem" }}>
        <div
          style={{
            fontSize: "0.75rem",
            color: "var(--text-muted)",
            marginBottom: "0.35rem",
          }}
        >
          Working Directory
        </div>
        <div style={{ position: "relative" }}>
          <pre
            style={{
              background: "var(--bg-primary)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              padding: "0.75rem 3rem 0.75rem 0.75rem",
              margin: 0,
              fontSize: "0.8rem",
              fontFamily: "'Cascadia Code', 'Fira Code', monospace",
              color: "#5eb3f7",
            }}
          >
            cd {WORKING_DIR}
          </pre>
          <div style={{ position: "absolute", top: "0.5rem", right: "0.5rem" }}>
            <CopyButton text={`cd ${WORKING_DIR}`} />
          </div>
        </div>
      </div>

      {/* Command sections */}
      {COMMANDS.map((section) => (
        <div
          className="card"
          key={section.title}
          style={{ marginBottom: "1rem" }}
        >
          <div className="card-title" style={{ marginBottom: "0.75rem" }}>
            {section.title}
          </div>
          {section.items.map((item, i) => (
            <CommandBlock
              key={i}
              comment={item.comment}
              cmd={item.cmd}
              placeholders={item.placeholders}
              onRun={runner.run}
              isRunning={runner.running}
              isConnected={runner.connected}
            />
          ))}
        </div>
      ))}

      {/* Terminal output */}
      <Terminal
        lines={runner.lines}
        onClear={runner.clearLines}
        onKill={runner.kill}
        isRunning={runner.running}
      />

      {/* Options table */}
      <div className="card" style={{ marginBottom: "1rem" }}>
        <div className="card-title" style={{ marginBottom: "0.75rem" }}>
          주요 옵션
        </div>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: "200px" }}>옵션</th>
                <th>설명</th>
              </tr>
            </thead>
            <tbody>
              {OPTIONS.map((opt) => (
                <tr key={opt.option}>
                  <td
                    style={{
                      fontFamily: "'Cascadia Code', 'Fira Code', monospace",
                      fontSize: "0.8rem",
                      color: "#5eb3f7",
                    }}
                  >
                    {opt.option}
                  </td>
                  <td style={{ fontSize: "0.8rem" }}>{opt.desc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Prerequisite note */}
      <div
        className="card"
        style={{
          borderColor: "var(--warning, #e6a817)",
          background: "rgba(230, 168, 23, 0.05)",
        }}
      >
        <div style={{ fontSize: "0.8rem" }}>
          <strong>사전 조건:</strong>
          <ul style={{ margin: "0.5rem 0 0 1.2rem", padding: 0 }}>
            <li>
              Lakehouse 스택이 실행 중이어야 합니다 (
              <code
                style={{
                  background: "var(--bg-primary)",
                  padding: "0.15rem 0.4rem",
                  borderRadius: "3px",
                  fontSize: "0.75rem",
                }}
              >
                cd Lakehouse/Iceberg && ./start.sh
              </code>
              )
            </li>
            <li>
              명령 실행 시 Pipeline Runner가 필요합니다 (
              <code
                style={{
                  background: "var(--bg-primary)",
                  padding: "0.15rem 0.4rem",
                  borderRadius: "3px",
                  fontSize: "0.75rem",
                }}
              >
                cd nucleus_pipeline && .venv\Scripts\python.exe runner_server.py
              </code>
              )
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
