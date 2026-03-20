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
Data Fetcher Module for Lakehouse API Congestion Data.

Provides a clean separation between API communication and UI rendering.
Queries per-space congestion summary data from the FastAPI middleware
(api_service) and parses the responses into typed Python dataclasses.

Endpoints consumed:
    - GET /api/v1/spaces/congestion/summary  (primary — rich data)
    - GET /api/v1/congestion                 (fallback — simpler snapshot)
    - GET /api/v1/spaces/{space_id}/objects   (per-space drill-down)

Design constraints:
    - Only stdlib modules (urllib, json) — no external pip packages
    - Isaac Sim Extension compatibility (omni.ui + urllib only)
    - Graceful degradation with demo data when API is unreachable
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

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
class SpaceCongestionData:
    """Parsed congestion data for a single space.

    Fields mirror the ``SpaceCongestionDetail`` Pydantic model from
    ``api_service.app.api.v1.spaces`` but as a plain dataclass for
    zero-dependency use inside Isaac Sim extensions.
    """
    space_id: str
    static_prim_count: int = 0
    dynamic_object_count: int = 0
    total_object_count: int = 0
    congestion_level: float = 0.0
    type_distribution: Dict[str, int] = field(default_factory=dict)

    # Extra fields from the simpler /congestion endpoint fallback
    object_count: int = 0
    timestamp: Optional[str] = None

    @property
    def display_name(self) -> str:
        """Human-friendly space name (strips /World/ prefix if present)."""
        if self.space_id.startswith("/World/"):
            return self.space_id[len("/World/"):]
        return self.space_id

    @property
    def congestion_label(self) -> str:
        """Textual congestion level: Low / Medium / High."""
        if self.congestion_level < 0.4:
            return "Low"
        elif self.congestion_level < 0.7:
            return "Medium"
        return "High"


@dataclass
class CongestionSummary:
    """Aggregated congestion summary across all spaces.

    Returned by ``CongestionFetcher.fetch_summary()``.
    """
    spaces: List[SpaceCongestionData] = field(default_factory=list)
    total_spaces: int = 0
    total_static_prims: int = 0
    total_dynamic_objects: int = 0
    snapshot_time: str = ""
    source: str = ""  # "summary" | "congestion" | "demo" — indicates data origin

    @property
    def total_objects(self) -> int:
        """Total object count across all spaces."""
        return self.total_static_prims + self.total_dynamic_objects

    @property
    def max_object_count(self) -> int:
        """Maximum total_object_count among all spaces (for normalization)."""
        if not self.spaces:
            return 0
        return max(s.total_object_count for s in self.spaces)

    def get_space(self, space_id: str) -> Optional[SpaceCongestionData]:
        """Look up a space by id."""
        for s in self.spaces:
            if s.space_id == space_id:
                return s
        return None

    def sorted_by_congestion(self, descending: bool = True) -> List[SpaceCongestionData]:
        """Return spaces sorted by congestion_level."""
        return sorted(self.spaces, key=lambda s: s.congestion_level, reverse=descending)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "spaces": [
                {
                    "space_id": s.space_id,
                    "static_prim_count": s.static_prim_count,
                    "dynamic_object_count": s.dynamic_object_count,
                    "total_object_count": s.total_object_count,
                    "congestion_level": s.congestion_level,
                    "type_distribution": s.type_distribution,
                    "object_count": s.object_count,
                    "timestamp": s.timestamp,
                }
                for s in self.spaces
            ],
            "total_spaces": self.total_spaces,
            "total_static_prims": self.total_static_prims,
            "total_dynamic_objects": self.total_dynamic_objects,
            "snapshot_time": self.snapshot_time,
            "source": self.source,
        }


@dataclass
class StaticObjectData:
    """Parsed static Prim object data from drill-down response."""
    prim_path: str
    object_type: str
    properties: str = "{}"


@dataclass
class DynamicObjectData:
    """Parsed dynamic object data from drill-down response."""
    object_id: str
    pos_x: float = 0.0
    pos_y: float = 0.0
    pos_z: float = 0.0
    speed: float = 0.0
    timestamp: Optional[str] = None
    properties: str = "{}"


@dataclass
class SpaceObjectsData:
    """Combined static + dynamic objects for a single space."""
    space_id: str
    static_objects: List[StaticObjectData] = field(default_factory=list)
    dynamic_objects: List[DynamicObjectData] = field(default_factory=list)
    static_count: int = 0
    dynamic_count: int = 0
    total_count: int = 0


@dataclass
class FetchResult:
    """Wrapper for any fetch operation result with error metadata."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    source: str = ""  # "api" | "fallback" | "demo"
    elapsed_ms: float = 0.0


# ═════════════════════════════════════════════════════════════════════════
#  HTTP Utility Layer (urllib-only, no requests/httpx)
# ═════════════════════════════════════════════════════════════════════════

def _http_get(url: str, timeout: int = _DEFAULT_TIMEOUT) -> Tuple[int, dict]:
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
) -> Tuple[int, dict]:
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


# ═════════════════════════════════════════════════════════════════════════
#  Response Parsers
# ═════════════════════════════════════════════════════════════════════════

def _parse_congestion_summary(data: dict) -> CongestionSummary:
    """Parse the rich ``/spaces/congestion/summary`` response.

    Expected shape::

        {
            "spaces": [
                {
                    "space_id": "Room_A",
                    "static_prim_count": 42,
                    "dynamic_object_count": 3,
                    "total_object_count": 45,
                    "congestion_level": 0.25,
                    "type_distribution": {"Mesh": 30, "Xform": 12}
                },
                ...
            ],
            "total_spaces": 4,
            "total_static_prims": 150,
            "total_dynamic_objects": 12,
            "snapshot_time": "2026-03-19T12:34:56"
        }
    """
    spaces = []
    for sp in data.get("spaces", []):
        spaces.append(SpaceCongestionData(
            space_id=sp.get("space_id", "unknown"),
            static_prim_count=int(sp.get("static_prim_count", 0)),
            dynamic_object_count=int(sp.get("dynamic_object_count", 0)),
            total_object_count=int(sp.get("total_object_count", 0)),
            congestion_level=float(sp.get("congestion_level", 0.0)),
            type_distribution=sp.get("type_distribution", {}),
            object_count=int(sp.get("total_object_count", sp.get("object_count", 0))),
        ))

    return CongestionSummary(
        spaces=spaces,
        total_spaces=int(data.get("total_spaces", len(spaces))),
        total_static_prims=int(data.get("total_static_prims", 0)),
        total_dynamic_objects=int(data.get("total_dynamic_objects", 0)),
        snapshot_time=str(data.get("snapshot_time", "")),
        source="summary",
    )


def _parse_congestion_simple(data: dict) -> CongestionSummary:
    """Parse the simpler ``/congestion`` response (fallback).

    Expected shape::

        {
            "spaces": [
                {
                    "space_id": "Room_A",
                    "object_count": 5,
                    "congestion_level": 0.45,
                    "timestamp": "2026-03-19T12:34:56+00:00"
                },
                ...
            ],
            "total_objects": 12,
            "snapshot_time": "2026-03-19T12:34:56+00:00"
        }
    """
    spaces = []
    for sp in data.get("spaces", []):
        obj_count = int(sp.get("object_count", 0))
        spaces.append(SpaceCongestionData(
            space_id=sp.get("space_id", "unknown"),
            dynamic_object_count=obj_count,
            total_object_count=obj_count,
            congestion_level=float(sp.get("congestion_level", 0.0)),
            object_count=obj_count,
            timestamp=sp.get("timestamp"),
        ))

    total_objects = int(data.get("total_objects", 0))
    return CongestionSummary(
        spaces=spaces,
        total_spaces=len(spaces),
        total_dynamic_objects=total_objects,
        snapshot_time=str(data.get("snapshot_time", "")),
        source="congestion",
    )


def _parse_space_objects(data: dict) -> SpaceObjectsData:
    """Parse the ``/spaces/{space_id}/objects`` response."""
    static_objs = []
    for obj in data.get("static_objects", []):
        static_objs.append(StaticObjectData(
            prim_path=obj.get("prim_path", ""),
            object_type=obj.get("object_type", ""),
            properties=obj.get("properties", "{}"),
        ))

    dynamic_objs = []
    for obj in data.get("dynamic_objects", []):
        dynamic_objs.append(DynamicObjectData(
            object_id=obj.get("object_id", ""),
            pos_x=float(obj.get("pos_x", 0.0)),
            pos_y=float(obj.get("pos_y", 0.0)),
            pos_z=float(obj.get("pos_z", 0.0)),
            speed=float(obj.get("speed", 0.0)),
            timestamp=obj.get("timestamp"),
            properties=obj.get("properties", "{}"),
        ))

    return SpaceObjectsData(
        space_id=data.get("space_id", ""),
        static_objects=static_objs,
        dynamic_objects=dynamic_objs,
        static_count=int(data.get("static_count", len(static_objs))),
        dynamic_count=int(data.get("dynamic_count", len(dynamic_objs))),
        total_count=int(data.get("total_count", len(static_objs) + len(dynamic_objs))),
    )


# ═════════════════════════════════════════════════════════════════════════
#  Demo Data Generator (offline/disconnected fallback)
# ═════════════════════════════════════════════════════════════════════════

def generate_demo_summary() -> CongestionSummary:
    """Generate realistic demo data when the API is unreachable.

    Useful for:
    - Extension UI development without a running Docker stack
    - Automated testing of the visualization layer
    - Offline demos and presentations
    """
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    demo_spaces = [
        SpaceCongestionData(
            space_id="Room_A",
            static_prim_count=42,
            dynamic_object_count=3,
            total_object_count=45,
            congestion_level=0.25,
            type_distribution={"Mesh": 30, "Xform": 10, "Scope": 2},
            object_count=45,
            timestamp=now,
        ),
        SpaceCongestionData(
            space_id="Room_B",
            static_prim_count=78,
            dynamic_object_count=7,
            total_object_count=85,
            congestion_level=0.58,
            type_distribution={"Mesh": 55, "Xform": 15, "Camera": 3, "Scope": 5},
            object_count=85,
            timestamp=now,
        ),
        SpaceCongestionData(
            space_id="Hallway_01",
            static_prim_count=15,
            dynamic_object_count=10,
            total_object_count=25,
            congestion_level=0.83,
            type_distribution={"Mesh": 10, "Xform": 5},
            object_count=25,
            timestamp=now,
        ),
        SpaceCongestionData(
            space_id="Lab_C",
            static_prim_count=120,
            dynamic_object_count=2,
            total_object_count=122,
            congestion_level=0.17,
            type_distribution={"Mesh": 80, "Xform": 25, "Scope": 10, "Camera": 5},
            object_count=122,
            timestamp=now,
        ),
    ]

    return CongestionSummary(
        spaces=demo_spaces,
        total_spaces=len(demo_spaces),
        total_static_prims=sum(s.static_prim_count for s in demo_spaces),
        total_dynamic_objects=sum(s.dynamic_object_count for s in demo_spaces),
        snapshot_time=now,
        source="demo",
    )


# ═════════════════════════════════════════════════════════════════════════
#  CongestionFetcher — Main Public API
# ═════════════════════════════════════════════════════════════════════════

class CongestionFetcher:
    """
    Fetches per-space congestion summary data from the Lakehouse API.

    Provides a clean, testable interface for the Extension UI and
    web dashboard data layer. Implements a two-tier fallback strategy:

    1. Primary:  ``GET /api/v1/spaces/congestion/summary``
       → Rich data (static + dynamic counts, type distributions)
    2. Fallback: ``GET /api/v1/congestion``
       → Simpler snapshot (dynamic-only object counts)
    3. Demo:     ``generate_demo_summary()``
       → Offline-safe synthetic data

    Usage::

        fetcher = CongestionFetcher(api_base="http://lakehouse-api:8000")
        result = fetcher.fetch_summary()

        if result.success:
            summary = result.data  # CongestionSummary
            for space in summary.spaces:
                print(f"{space.space_id}: {space.congestion_label}")
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
        """
        Args:
            api_base: API base URL (e.g., "http://lakehouse-api:8000").
                      Defaults to LAKEHOUSE_API_URL env or localhost fallback.
            timeout:  HTTP request timeout in seconds.
            use_demo_fallback: If True, return demo data when API is unreachable.
            on_status: Optional callback for status messages (e.g., UI log updates).
        """
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

    # ── Primary: Congestion Summary ────────────────────────────────────

    def fetch_summary(self) -> FetchResult:
        """
        Fetch the per-space congestion summary with two-tier fallback.

        Returns a ``FetchResult`` whose ``.data`` is a ``CongestionSummary``.

        Strategy:
            1. Try ``GET /api/v1/spaces/congestion/summary`` (rich data)
            2. Fallback to ``GET /api/v1/congestion`` (simpler data)
            3. If both fail and ``use_demo_fallback`` is True, return demo data
        """
        t0 = time.monotonic()

        # ── Tier 1: Rich summary endpoint ────────────────────────────
        try:
            self._on_status("Fetching congestion summary from API...")
            url = self._url("api/v1/spaces/congestion/summary")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                summary = _parse_congestion_summary(data)
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(
                    f"[OK] Congestion summary: {summary.total_spaces} spaces, "
                    f"{summary.total_objects} total objects ({elapsed:.0f}ms)"
                )
                return FetchResult(
                    success=True,
                    data=summary,
                    status_code=status,
                    source="summary",
                    elapsed_ms=elapsed,
                )
        except Exception as e:
            self._on_status(f"Summary endpoint failed: {e}. Trying fallback...")

        # ── Tier 2: Simpler congestion endpoint ──────────────────────
        try:
            url = self._url("api/v1/congestion")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                summary = _parse_congestion_simple(data)
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(
                    f"[OK] Congestion (fallback): {summary.total_spaces} spaces, "
                    f"{summary.total_dynamic_objects} dynamic objects ({elapsed:.0f}ms)"
                )
                return FetchResult(
                    success=True,
                    data=summary,
                    status_code=status,
                    source="fallback",
                    elapsed_ms=elapsed,
                )
        except Exception as e:
            self._on_status(f"Fallback endpoint also failed: {e}")

        # ── Tier 3: Demo data (offline safe) ─────────────────────────
        if self._use_demo_fallback:
            summary = generate_demo_summary()
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(
                f"[DEMO] Using demo data: {summary.total_spaces} spaces "
                f"(API unreachable)"
            )
            return FetchResult(
                success=True,
                data=summary,
                source="demo",
                elapsed_ms=elapsed,
            )

        elapsed = (time.monotonic() - t0) * 1000
        return FetchResult(
            success=False,
            error="All congestion endpoints unreachable and demo fallback disabled",
            elapsed_ms=elapsed,
        )

    # ── Per-Space Objects (Drill-Down) ─────────────────────────────────

    def fetch_space_objects(self, space_id: str) -> FetchResult:
        """
        Fetch detailed static + dynamic objects for a specific space.

        Calls ``GET /api/v1/spaces/{space_id}/objects``.

        Returns a ``FetchResult`` whose ``.data`` is a ``SpaceObjectsData``.
        """
        t0 = time.monotonic()
        encoded = urllib.request.quote(space_id, safe="")
        url = self._url(f"api/v1/spaces/{encoded}/objects")

        try:
            self._on_status(f"Fetching objects for space '{space_id}'...")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                objects_data = _parse_space_objects(data)
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(
                    f"[OK] Space '{space_id}': {objects_data.static_count} static + "
                    f"{objects_data.dynamic_count} dynamic objects ({elapsed:.0f}ms)"
                )
                return FetchResult(
                    success=True,
                    data=objects_data,
                    status_code=status,
                    source="api",
                    elapsed_ms=elapsed,
                )

            elapsed = (time.monotonic() - t0) * 1000
            return FetchResult(
                success=False,
                error=f"HTTP {status}",
                status_code=status,
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(f"[FAIL] Space objects fetch error: {e}")
            return FetchResult(
                success=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

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
