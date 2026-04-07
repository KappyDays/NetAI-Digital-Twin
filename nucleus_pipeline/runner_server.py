"""
Pipeline Runner — WebSocket server for executing Nucleus Pipeline commands.
Runs on the host machine (not in Docker) to access the local Python venv.

Start:
    cd nucleus_pipeline
    .venv\\Scripts\\python.exe runner_server.py
"""

import asyncio
import os
import sys
from pathlib import Path

try:
    import uvicorn
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
except ImportError:
    print("Missing dependencies. Install with:")
    print(f"  {sys.executable} -m pip install fastapi uvicorn")
    sys.exit(1)

PIPELINE_DIR = Path(__file__).parent.resolve()
VENV_PYTHON = PIPELINE_DIR / ".venv" / "Scripts" / "python.exe"

app = FastAPI(title="Pipeline Runner", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "cwd": str(PIPELINE_DIR),
        "python": str(VENV_PYTHON),
        "python_exists": VENV_PYTHON.exists(),
    }


def _prepare_command(raw: str) -> list[str]:
    """Parse command string: resolve venv python, handle line continuations."""
    cmd = raw.replace("\\\n", " ").replace("\\\r\n", " ")
    cmd = " ".join(cmd.split())
    parts = cmd.split()
    if not parts:
        return []
    if parts[0] == "python" and VENV_PYTHON.exists():
        parts[0] = str(VENV_PYTHON)
    return parts


@app.websocket("/ws/run")
async def ws_run(ws: WebSocket):
    await ws.accept()
    process = None

    try:
        while True:
            data = await ws.receive_json()
            action = data.get("action", "run")

            if action == "kill":
                if process:
                    process.terminate()
                    await ws.send_json({"type": "info", "data": "\n[Process terminated]\n"})
                continue

            if action != "run":
                continue

            command = data.get("command", "").strip()
            if not command:
                await ws.send_json({"type": "error", "data": "Empty command"})
                continue

            parts = _prepare_command(command)
            if not parts:
                await ws.send_json({"type": "error", "data": "Invalid command"})
                continue

            await ws.send_json({"type": "info", "data": f"$ {command}\n\n"})

            try:
                process = await asyncio.create_subprocess_exec(
                    *parts,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(PIPELINE_DIR),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )

                async def read_stream(stream, stream_type):
                    async for line in stream:
                        text = line.decode("utf-8", errors="replace")
                        await ws.send_json({"type": stream_type, "data": text})

                await asyncio.gather(
                    read_stream(process.stdout, "stdout"),
                    read_stream(process.stderr, "stderr"),
                )

                code = await process.wait()
                await ws.send_json({"type": "exit", "code": code})

            except FileNotFoundError as e:
                await ws.send_json({"type": "error", "data": f"Command not found: {e}\n"})
            except Exception as e:
                await ws.send_json({"type": "error", "data": f"Execution error: {e}\n"})
            finally:
                process = None

    except WebSocketDisconnect:
        if process:
            process.terminate()
    except Exception:
        if process:
            process.terminate()


if __name__ == "__main__":
    print(f"Pipeline Runner starting...")
    print(f"  Directory: {PIPELINE_DIR}")
    print(f"  Python:    {VENV_PYTHON} ({'found' if VENV_PYTHON.exists() else 'NOT FOUND'})")
    print(f"  URL:       http://127.0.0.1:8200")
    print(f"  WebSocket: ws://127.0.0.1:8200/ws/run")
    print()
    uvicorn.run(app, host="127.0.0.1", port=8200, log_level="info")
