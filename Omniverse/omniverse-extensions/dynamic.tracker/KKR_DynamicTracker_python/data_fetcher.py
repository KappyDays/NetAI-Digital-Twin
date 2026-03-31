# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Data Fetcher Module for Dynamic Object Trajectory Data.

Provides a clean separation between API communication and UI rendering.
Queries dynamic object trajectory and state data from the FastAPI middleware
(api_service) and parses the responses into typed Python dataclasses.

Endpoints consumed:
    - POST /api/v1/dynamic/query/trajectory  (trajectory history)
    - GET  /api/v1/dynamic/query/latest       (latest states)
    - GET  /api/v1/dynamic/tables             (available dynamic tables)
    - GET  /api/v1/health                     (health check)

Design constraints:
    - Only stdlib modules (urllib, json) — no external pip packages
    - Isaac Sim Extension compatibility (omni.ui + urllib only)
    - Graceful degradation with demo data when API is unreachable
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

# ═════════════════════════════════════════════════════════════════════════
#  Configuration
# ═════════════════════════════════════════════════════════════════════════

# Default API base URL. Overridden by env-var in Docker/k8s deployment.
_DEFAULT_API_BASE = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")

# HTTP timeout for API calls (seconds).
_DEFAULT_TIMEOUT = int(os.getenv("LAKEHOUSE_API_TIMEOUT", "30"))

# Maximum retries for transient HTTP errors.
_MAX_RETRIES = 2

# Retry delay base in seconds (exponential backoff: base * 2^attempt).
_RETRY_DELAY_BASE = 0.5


# ═════════════════════════════════════════════════════════════════════════
#  Data Models (lightweight dataclasses — no Pydantic dependency)
# ═════════════════════════════════════════════════════════════════════════

@dataclass
class TrajectoryPoint:
    """A single point along an object's trajectory."""
    timestamp: str
    pos_x: float
    pos_y: float
    pos_z: float
    speed: float = 0.0


@dataclass
class ObjectTrajectory:
    """Complete trajectory for a single dynamic object."""
    object_id: str
    points: List[TrajectoryPoint] = field(default_factory=list)
    color: int = 0  # 0xAABBGGRR format; 0 means use palette default


@dataclass
class ObjectState:
    """Latest state snapshot for a single dynamic object."""
    object_id: str
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    speed: float = 0.0
    space_id: str = ""
    timestamp: str = ""


@dataclass
class FetchResult:
    """Wrapper for any fetch operation result with error metadata."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    source: str = ""  # "api" | "demo"
    elapsed_ms: float = 0.0


# ═════════════════════════════════════════════════════════════════════════
#  HTTP Utility Layer (urllib-only, no requests/httpx)
# ═════════════════════════════════════════════════════════════════════════

def _http_get(url: str, timeout: int = _DEFAULT_TIMEOUT) -> Tuple[int, Any]:
    """
    Perform an HTTP GET request and return (status_code, parsed_json).

    Raises ``urllib.error.URLError`` or ``ValueError`` on failure.
    """
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        body = resp.read().decode("utf-8")
        return status, json.loads(body)


def _http_get_with_retry(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT,
    max_retries: int = _MAX_RETRIES,
) -> Tuple[int, Any]:
    """
    HTTP GET with exponential backoff retry for transient errors.

    Retries on:
        - urllib.error.URLError (network/DNS issues)
        - HTTP 502, 503, 504 (gateway / service unavailable)
    Does NOT retry on 4xx client errors.
    """
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            status, data = _http_get(url, timeout=timeout)
            if status in (502, 503, 504) and attempt < max_retries:
                time.sleep(_RETRY_DELAY_BASE * (2 ** attempt))
                continue
            return status, data
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < max_retries:
                last_error = e
                time.sleep(_RETRY_DELAY_BASE * (2 ** attempt))
                continue
            raise
        except urllib.error.URLError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(_RETRY_DELAY_BASE * (2 ** attempt))
                continue
            raise
    # Should not reach here, but just in case
    raise last_error or RuntimeError("Max retries exceeded")


def _http_post_json(
    url: str,
    payload: dict,
    timeout: int = _DEFAULT_TIMEOUT,
) -> Tuple[int, Any]:
    """
    Perform an HTTP POST request with JSON body and return (status_code, parsed_json).

    Raises ``urllib.error.URLError`` or ``ValueError`` on failure.
    """
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        status = resp.getcode()
        resp_body = resp.read().decode("utf-8")
        return status, json.loads(resp_body)


# ═════════════════════════════════════════════════════════════════════════
#  Demo Data Generator (offline/disconnected fallback)
# ═════════════════════════════════════════════════════════════════════════

def generate_demo_trajectories() -> List[ObjectTrajectory]:
    """Generate realistic demo trajectories when the API is unreachable.

    Creates 3 demo objects with distinct motion patterns over 60 seconds:
        - worker_01: circular path, radius 5, center (0,0), color blue
        - worker_02: figure-8 path, color green
        - agv_01: straight line with speed variation, color orange
    """
    import datetime as _dt
    base_time = _dt.datetime(2026, 3, 24, 12, 0, 0, tzinfo=_dt.timezone.utc)
    num_points = 60  # one point per second

    trajectories = []

    # worker_01: circular path
    pts_w1 = []
    for i in range(num_points):
        t = i / num_points * 2 * math.pi
        px = 5.0 * math.cos(t)
        py = 5.0 * math.sin(t)
        pz = 0.0
        speed = 5.0 * 2 * math.pi / num_points  # constant angular speed
        ts = (base_time + _dt.timedelta(seconds=i)).isoformat()
        pts_w1.append(TrajectoryPoint(timestamp=ts, pos_x=px, pos_y=py, pos_z=pz, speed=speed))
    trajectories.append(ObjectTrajectory(
        object_id="worker_01", points=pts_w1, color=0xFFFF4444,  # Blue (BGR)
    ))

    # worker_02: figure-8 path
    pts_w2 = []
    for i in range(num_points):
        t = i / num_points * 2 * math.pi
        px = 4.0 * math.sin(t)
        py = 4.0 * math.sin(t) * math.cos(t)
        pz = 0.0
        speed = abs(4.0 * math.cos(t))
        ts = (base_time + _dt.timedelta(seconds=i)).isoformat()
        pts_w2.append(TrajectoryPoint(timestamp=ts, pos_x=px, pos_y=py, pos_z=pz, speed=speed))
    trajectories.append(ObjectTrajectory(
        object_id="worker_02", points=pts_w2, color=0xFF44FF44,  # Green
    ))

    # agv_01: straight line with speed variation
    pts_a1 = []
    for i in range(num_points):
        frac = i / num_points
        px = -10.0 + 20.0 * frac
        py = 3.0
        pz = 0.0
        speed = 0.5 + 2.0 * abs(math.sin(frac * math.pi * 3))
        ts = (base_time + _dt.timedelta(seconds=i)).isoformat()
        pts_a1.append(TrajectoryPoint(timestamp=ts, pos_x=px, pos_y=py, pos_z=pz, speed=speed))
    trajectories.append(ObjectTrajectory(
        object_id="agv_01", points=pts_a1, color=0xFF4488FF,  # Orange (BGR)
    ))

    return trajectories


def generate_demo_latest() -> List[ObjectState]:
    """Generate demo latest-state data when the API is unreachable."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    return [
        ObjectState(object_id="worker_01", pos_x=5.0, pos_y=0.0, pos_z=0.0, speed=0.52, space_id="Room_A", timestamp=now),
        ObjectState(object_id="worker_02", pos_x=0.0, pos_y=0.0, pos_z=0.0, speed=1.10, space_id="Room_B", timestamp=now),
        ObjectState(object_id="agv_01", pos_x=10.0, pos_y=3.0, pos_z=0.0, speed=2.30, space_id="Hallway_01", timestamp=now),
    ]


# ═════════════════════════════════════════════════════════════════════════
#  TrajectoryFetcher — Main Public API
# ═════════════════════════════════════════════════════════════════════════

class TrajectoryFetcher:
    """
    Fetches dynamic object trajectory and state data from the Lakehouse API.

    Provides a clean, testable interface for the Extension UI.

    Usage::

        fetcher = TrajectoryFetcher(api_base="http://lakehouse-api:8000")
        result = fetcher.fetch_trajectory("worker_01", "2026-03-24T00:00:00Z", "2026-03-24T01:00:00Z")

        if result.success:
            trajectory = result.data  # ObjectTrajectory
            for pt in trajectory.points:
                print(f"  {pt.timestamp}: ({pt.pos_x}, {pt.pos_y}, {pt.pos_z})")
        else:
            print(f"Error: {result.error}")

    Thread Safety
    -------------
    This class is stateless and safe for concurrent use.
    Each method creates its own HTTP request independently.
    """

    def __init__(
        self,
        api_base: Optional[str] = None,
        timeout: int = _DEFAULT_TIMEOUT,
        use_demo_fallback: bool = True,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        self._api_base = (api_base or _DEFAULT_API_BASE).rstrip("/")
        self._timeout = timeout
        self._use_demo_fallback = use_demo_fallback
        self._on_status = on_status or (lambda _: None)

    @property
    def api_base(self) -> str:
        """Current API base URL."""
        return self._api_base

    @api_base.setter
    def api_base(self, value: str) -> None:
        self._api_base = value.rstrip("/")

    def _url(self, path: str) -> str:
        """Build a full API URL."""
        path = path.lstrip("/")
        return f"{self._api_base}/{path}"

    # ── Trajectory Fetch ──────────────────────────────────────────────

    def fetch_trajectory(
        self,
        object_id: str,
        start_time: str,
        end_time: str,
        sample_interval: int = 5,
    ) -> FetchResult:
        """
        Fetch trajectory history for a single object.

        Calls ``POST /api/v1/dynamic/query/trajectory`` with JSON body.

        Returns a ``FetchResult`` whose ``.data`` is an ``ObjectTrajectory``.
        """
        t0 = time.monotonic()
        url = self._url("api/v1/dynamic/query/trajectory")
        payload = {
            "object_id": object_id,
            "start_time": start_time,
            "end_time": end_time,
            "sample_interval_seconds": sample_interval,
            "limit": 1000,
            "offset": 0,
        }

        try:
            self._on_status(f"Fetching trajectory for '{object_id}'...")
            status, data = _http_post_json(url, payload, timeout=self._timeout)

            if status == 200:
                points = []
                for row in data.get("points", data.get("rows", [])):
                    points.append(TrajectoryPoint(
                        timestamp=str(row.get("timestamp", "")),
                        pos_x=float(row.get("pos_x", 0.0)),
                        pos_y=float(row.get("pos_y", 0.0)),
                        pos_z=float(row.get("pos_z", 0.0)),
                        speed=float(row.get("speed", 0.0)),
                    ))
                trajectory = ObjectTrajectory(object_id=object_id, points=points)
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(
                    f"[OK] Trajectory '{object_id}': {len(points)} points ({elapsed:.0f}ms)"
                )
                return FetchResult(
                    success=True, data=trajectory,
                    status_code=status, source="api", elapsed_ms=elapsed,
                )

            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=False, error=f"HTTP {status}",
                status_code=status, elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(f"[FAIL] Trajectory fetch error: {e}")
            return FetchResult(success=False, error=str(e), elapsed_ms=elapsed)

    # ── Latest States ─────────────────────────────────────────────────

    def fetch_latest_states(self, limit: int = 500) -> FetchResult:
        """
        Fetch the latest state for all dynamic objects.

        Calls ``GET /api/v1/dynamic/query/latest?limit={limit}``.

        Returns a ``FetchResult`` whose ``.data`` is a ``list[ObjectState]``.
        """
        t0 = time.monotonic()
        url = self._url(f"api/v1/dynamic/query/latest?limit={limit}")

        try:
            self._on_status("Fetching latest dynamic object states...")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                states = []
                rows = data if isinstance(data, list) else data.get("objects", data.get("rows", []))
                for row in rows:
                    states.append(ObjectState(
                        object_id=str(row.get("object_id", "")),
                        pos_x=float(row.get("pos_x", 0.0)),
                        pos_y=float(row.get("pos_y", 0.0)),
                        pos_z=float(row.get("pos_z", 0.0)),
                        speed=float(row.get("speed", 0.0)),
                        space_id=str(row.get("space_id", "")),
                        timestamp=str(row.get("timestamp", "")),
                    ))
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(f"[OK] Latest states: {len(states)} objects ({elapsed:.0f}ms)")
                return FetchResult(
                    success=True, data=states,
                    status_code=status, source="api", elapsed_ms=elapsed,
                )

            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=False, error=f"HTTP {status}",
                status_code=status, elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(f"[FAIL] Latest states fetch error: {e}")

            if self._use_demo_fallback:
                states = generate_demo_latest()
                self._on_status(f"[DEMO] Using demo data: {len(states)} objects (API unreachable)")
                return FetchResult(
                    success=True, data=states, source="demo", elapsed_ms=elapsed,
                )

            return FetchResult(success=False, error=str(e), elapsed_ms=elapsed)

    # ── Dynamic Tables ────────────────────────────────────────────────

    def fetch_dynamic_tables(self) -> FetchResult:
        """
        Fetch list of available dynamic object tables.

        Calls ``GET /api/v1/dynamic/tables``.

        IMPORTANT: Returns list[str] (JSON array), NOT a dict!

        Returns a ``FetchResult`` whose ``.data`` is a ``list[str]``.
        """
        t0 = time.monotonic()
        url = self._url("api/v1/dynamic/tables")

        try:
            self._on_status("Fetching dynamic tables list...")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                # Response is a JSON array of strings: ["worker_01", "agv_01", ...]
                if isinstance(data, list):
                    table_names = [str(t) for t in data]
                else:
                    # Fallback: try extracting from dict wrapper
                    table_names = [str(t) for t in data.get("tables", data.get("items", []))]

                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(f"[OK] Dynamic tables: {len(table_names)} found ({elapsed:.0f}ms)")
                return FetchResult(
                    success=True, data=table_names,
                    status_code=status, source="api", elapsed_ms=elapsed,
                )

            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=False, error=f"HTTP {status}",
                status_code=status, elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(f"[FAIL] Dynamic tables fetch error: {e}")

            if self._use_demo_fallback:
                demo_tables = ["worker_01", "worker_02", "agv_01"]
                self._on_status(f"[DEMO] Using demo tables: {len(demo_tables)} (API unreachable)")
                return FetchResult(
                    success=True, data=demo_tables, source="demo", elapsed_ms=elapsed,
                )

            return FetchResult(success=False, error=str(e), elapsed_ms=elapsed)

    # ── Health Check ──────────────────────────────────────────────────

    def check_health(self) -> FetchResult:
        """
        Quick health check: ``GET /api/v1/health``.

        Returns a ``FetchResult`` whose ``.data`` is the raw health dict.
        """
        t0 = time.monotonic()
        url = self._url("api/v1/health")

        try:
            status, data = _http_get(url, timeout=min(self._timeout, 10))
            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=(status == 200),
                data=data,
                status_code=status,
                source="api",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )
