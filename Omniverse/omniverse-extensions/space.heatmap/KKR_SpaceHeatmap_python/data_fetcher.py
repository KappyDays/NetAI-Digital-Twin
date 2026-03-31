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
Data Fetcher Module for Space Heatmap Congestion Data.

Provides HTTP helpers and a HeatmapFetcher class that queries the
Lakehouse API for congestion summary and grid data. Falls back to
demo data when the API is unreachable.

Endpoints consumed:
    - GET /api/v1/spaces/congestion/summary  (space-level congestion)
    - GET /api/v1/congestion/grid            (spatial grid heatmap)
    - GET /api/v1/health                     (health check)

Design constraints:
    - Only stdlib modules (urllib, json) -- no external pip packages
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
from typing import Any, Callable, Dict, List, Optional, Tuple

# =========================================================================
#  Configuration
# =========================================================================

# Default API base URL. Overridden by env-var in Docker/k8s deployment.
_DEFAULT_API_BASE = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")

# HTTP timeout for API calls (seconds).
_DEFAULT_TIMEOUT = int(os.getenv("LAKEHOUSE_API_TIMEOUT", "30"))

# Maximum retries for transient HTTP errors.
_MAX_RETRIES = 2

# Retry delay base in seconds (exponential backoff: base * 2^attempt).
_RETRY_DELAY_BASE = 0.5


# =========================================================================
#  Data Models (lightweight dataclasses -- no Pydantic dependency)
# =========================================================================

@dataclass
class SpaceCongestion:
    """Congestion data for a single space."""
    space_id: str
    congestion_level: float = 0.0
    static_count: int = 0
    dynamic_count: int = 0
    total_count: int = 0
    type_distribution: Dict[str, int] = field(default_factory=dict)

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
class GridCell:
    """A single cell in the spatial heatmap grid."""
    row: int
    col: int
    x_center: float
    y_center: float
    count: int = 0
    congestion_level: float = 0.0


@dataclass
class HeatmapGrid:
    """Spatial grid of congestion cells for viewport overlay."""
    cells: List[GridCell] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    x_min: float = -50.0
    x_max: float = 50.0
    y_min: float = -50.0
    y_max: float = 50.0


@dataclass
class CongestionSummary:
    """Aggregated congestion summary across all spaces."""
    spaces: List[SpaceCongestion] = field(default_factory=list)
    total_spaces: int = 0
    total_static: int = 0
    total_dynamic: int = 0
    snapshot_time: str = ""
    source: str = ""  # "api" | "demo"

    @property
    def total_objects(self) -> int:
        return self.total_static + self.total_dynamic


@dataclass
class FetchResult:
    """Wrapper for any fetch operation result with error metadata."""
    success: bool
    data: Any = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    source: str = ""  # "api" | "fallback" | "demo"
    elapsed_ms: float = 0.0


# =========================================================================
#  HTTP Utility Layer (urllib-only, no requests/httpx)
# =========================================================================

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


# =========================================================================
#  Response Parsers
# =========================================================================

def _parse_congestion_summary(data: dict) -> CongestionSummary:
    """Parse the ``/spaces/congestion/summary`` response."""
    spaces = []
    for sp in data.get("spaces", []):
        spaces.append(SpaceCongestion(
            space_id=sp.get("space_id", "unknown"),
            congestion_level=float(sp.get("congestion_level", 0.0)),
            static_count=int(sp.get("static_prim_count", 0)),
            dynamic_count=int(sp.get("dynamic_object_count", 0)),
            total_count=int(sp.get("total_object_count", 0)),
            type_distribution=sp.get("type_distribution", {}),
        ))

    return CongestionSummary(
        spaces=spaces,
        total_spaces=int(data.get("total_spaces", len(spaces))),
        total_static=int(data.get("total_static_prims", 0)),
        total_dynamic=int(data.get("total_dynamic_objects", 0)),
        snapshot_time=str(data.get("snapshot_time", "")),
        source="api",
    )


def _parse_congestion_grid(data: dict) -> HeatmapGrid:
    """Parse the ``/congestion/grid`` response."""
    cells = []
    for c in data.get("cells", []):
        cells.append(GridCell(
            row=int(c.get("row", 0)),
            col=int(c.get("col", 0)),
            x_center=float(c.get("x_center", 0.0)),
            y_center=float(c.get("y_center", 0.0)),
            count=int(c.get("count", 0)),
            congestion_level=float(c.get("congestion_level", 0.0)),
        ))

    return HeatmapGrid(
        cells=cells,
        rows=int(data.get("rows", 0)),
        cols=int(data.get("cols", 0)),
        x_min=float(data.get("x_min", -50.0)),
        x_max=float(data.get("x_max", 50.0)),
        y_min=float(data.get("y_min", -50.0)),
        y_max=float(data.get("y_max", 50.0)),
    )


# =========================================================================
#  Demo Data Generators (offline/disconnected fallback)
# =========================================================================

def _generate_demo_summary() -> CongestionSummary:
    """Generate demo congestion summary with 4 spaces."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()

    demo_spaces = [
        SpaceCongestion(
            space_id="Cube",
            congestion_level=0.8,
            static_count=35,
            dynamic_count=8,
            total_count=43,
            type_distribution={"Mesh": 25, "Xform": 10},
        ),
        SpaceCongestion(
            space_id="Cylinder",
            congestion_level=0.4,
            static_count=20,
            dynamic_count=3,
            total_count=23,
            type_distribution={"Mesh": 15, "Xform": 5},
        ),
        SpaceCongestion(
            space_id="Cube_01",
            congestion_level=0.2,
            static_count=10,
            dynamic_count=1,
            total_count=11,
            type_distribution={"Mesh": 8, "Xform": 2},
        ),
        SpaceCongestion(
            space_id="Plane",
            congestion_level=0.1,
            static_count=5,
            dynamic_count=0,
            total_count=5,
            type_distribution={"Mesh": 5},
        ),
    ]

    return CongestionSummary(
        spaces=demo_spaces,
        total_spaces=len(demo_spaces),
        total_static=sum(s.static_count for s in demo_spaces),
        total_dynamic=sum(s.dynamic_count for s in demo_spaces),
        snapshot_time=now,
        source="demo",
    )


def _generate_demo_grid(rows: int = 10, cols: int = 10) -> HeatmapGrid:
    """Generate synthetic grid with hotspot pattern centered around (0,0)."""
    x_min, x_max = -50.0, 50.0
    y_min, y_max = -50.0, 50.0
    cell_w = (x_max - x_min) / cols
    cell_h = (y_max - y_min) / rows

    cells = []
    for r in range(rows):
        for c in range(cols):
            x_center = x_min + (c + 0.5) * cell_w
            y_center = y_min + (r + 0.5) * cell_h

            # Gaussian hotspot centered at (0, 0)
            dist = math.sqrt(x_center ** 2 + y_center ** 2)
            sigma = 25.0
            level = math.exp(-(dist ** 2) / (2 * sigma ** 2))

            # Add secondary hotspot at (20, 20)
            dist2 = math.sqrt((x_center - 20) ** 2 + (y_center - 20) ** 2)
            level2 = 0.6 * math.exp(-(dist2 ** 2) / (2 * (15.0 ** 2)))

            congestion = min(1.0, level + level2)
            count = int(congestion * 10)

            cells.append(GridCell(
                row=r,
                col=c,
                x_center=x_center,
                y_center=y_center,
                count=count,
                congestion_level=congestion,
            ))

    return HeatmapGrid(
        cells=cells,
        rows=rows,
        cols=cols,
        x_min=x_min,
        x_max=x_max,
        y_min=y_min,
        y_max=y_max,
    )


# =========================================================================
#  HeatmapFetcher -- Main Public API
# =========================================================================

class HeatmapFetcher:
    """
    Fetches congestion summary and grid data from the Lakehouse API.

    Provides a clean, testable interface for the Extension UI and
    viewport overlay. Falls back to demo data when API is unreachable.

    Usage::

        fetcher = HeatmapFetcher(api_base="http://lakehouse-api:8000")
        result = fetcher.fetch_congestion_summary()

        if result.success:
            summary = result.data  # CongestionSummary
            for space in summary.spaces:
                print(f"{space.space_id}: {space.congestion_label}")

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
        return self._api_base

    @api_base.setter
    def api_base(self, value: str) -> None:
        self._api_base = value.rstrip("/")

    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self._api_base}/{path}"

    # -- Congestion Summary ------------------------------------------------

    def fetch_congestion_summary(self) -> FetchResult:
        """
        Fetch per-space congestion summary.

        Strategy:
            1. Try GET /api/v1/spaces/congestion/summary
            2. If unreachable and use_demo_fallback is True, return demo data
        """
        t0 = time.monotonic()

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
                    source="api",
                    elapsed_ms=elapsed,
                )
        except Exception as e:
            self._on_status(f"Summary endpoint failed: {e}")

        # Demo fallback
        if self._use_demo_fallback:
            summary = _generate_demo_summary()
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
            error="Congestion summary endpoint unreachable and demo fallback disabled",
            elapsed_ms=elapsed,
        )

    # -- Congestion Grid ---------------------------------------------------

    def fetch_congestion_grid(
        self,
        x_min: float = -50.0,
        x_max: float = 50.0,
        y_min: float = -50.0,
        y_max: float = 50.0,
        rows: int = 20,
        cols: int = 20,
    ) -> FetchResult:
        """
        Fetch spatial congestion grid for viewport overlay.

        Calls GET /api/v1/congestion/grid with query params.
        """
        t0 = time.monotonic()

        try:
            self._on_status("Fetching congestion grid from API...")
            params = (
                f"x_min={x_min}&x_max={x_max}"
                f"&y_min={y_min}&y_max={y_max}"
                f"&rows={rows}&cols={cols}"
            )
            url = self._url(f"api/v1/congestion/grid?{params}")
            status, data = _http_get_with_retry(url, timeout=self._timeout)

            if status == 200:
                grid = _parse_congestion_grid(data)
                elapsed = (time.monotonic() - t0) * 1000
                self._on_status(
                    f"[OK] Grid: {grid.rows}x{grid.cols} cells ({elapsed:.0f}ms)"
                )
                return FetchResult(
                    success=True,
                    data=grid,
                    status_code=status,
                    source="api",
                    elapsed_ms=elapsed,
                )
        except Exception as e:
            self._on_status(f"Grid endpoint failed: {e}")

        # Demo fallback
        if self._use_demo_fallback:
            grid = _generate_demo_grid(rows=rows, cols=cols)
            elapsed = (time.monotonic() - t0) * 1000
            self._on_status(
                f"[DEMO] Using demo grid: {grid.rows}x{grid.cols} cells "
                f"(API unreachable)"
            )
            return FetchResult(
                success=True,
                data=grid,
                source="demo",
                elapsed_ms=elapsed,
            )

        elapsed = (time.monotonic() - t0) * 1000
        return FetchResult(
            success=False,
            error="Grid endpoint unreachable and demo fallback disabled",
            elapsed_ms=elapsed,
        )

    # -- Demo Data (public wrappers) ---------------------------------------

    def generate_demo_summary(self) -> CongestionSummary:
        """Generate demo summary: 4 spaces (Cube high, Cylinder medium, Cube_01 low, Plane low)."""
        return _generate_demo_summary()

    def generate_demo_grid(self, rows: int = 10, cols: int = 10) -> HeatmapGrid:
        """Generate synthetic grid with hotspot pattern centered around (0,0)."""
        return _generate_demo_grid(rows=rows, cols=cols)

    # -- Health Check ------------------------------------------------------

    def check_health(self) -> FetchResult:
        """Quick health check: GET /api/v1/health."""
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
