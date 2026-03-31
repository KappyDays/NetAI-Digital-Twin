"""HTTP helpers and StaticPrimFetcher with demo fallback.

Uses only stdlib (urllib) -- no third-party packages allowed inside Isaac Sim.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
#  Configuration (env-var-driven for Docker / k8s portability)
# ---------------------------------------------------------------------------

_DEFAULT_API_BASE: str = os.getenv("LAKEHOUSE_API_URL", "http://lakehouse-api:8000")
_DEFAULT_TIMEOUT: int = int(os.getenv("LAKEHOUSE_API_TIMEOUT", "30"))
_MAX_RETRIES: int = 2
_RETRY_DELAY_BASE: float = 0.5

# ---------------------------------------------------------------------------
#  Low-level HTTP helpers
# ---------------------------------------------------------------------------


def _http_get(url: str, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    """Perform a GET request and return parsed JSON.

    Raises urllib.error.URLError or json.JSONDecodeError on failure.
    """
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_with_retry(
    url: str,
    timeout: int = _DEFAULT_TIMEOUT,
    max_retries: int = _MAX_RETRIES,
) -> dict:
    """GET with exponential back-off on transient errors (502/503/504)."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return _http_get(url, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (502, 503, 504) and attempt < max_retries:
                last_exc = exc
                time.sleep(_RETRY_DELAY_BASE * (2 ** attempt))
                continue
            raise
        except urllib.error.URLError as exc:
            if attempt < max_retries:
                last_exc = exc
                time.sleep(_RETRY_DELAY_BASE * (2 ** attempt))
                continue
            raise
    # Should not reach here, but just in case
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
#  Data classes
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    """Wrapper around any fetch operation result."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    source: str = "api"  # "api" or "demo"
    elapsed_ms: float = 0.0


@dataclass
class PrimRecord:
    """Single prim record (mirrors Iceberg schema)."""

    prim_path: str
    prim_type: str
    space_id: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TypeDistribution:
    """Aggregated type counts."""

    type_counts: Dict[str, int] = field(default_factory=dict)
    total: int = 0


# ---------------------------------------------------------------------------
#  StaticPrimFetcher
# ---------------------------------------------------------------------------


class StaticPrimFetcher:
    """Fetches static prim data from the Lakehouse API with demo fallback."""

    def __init__(self, api_base: Optional[str] = None):
        self._api_base = (api_base or _DEFAULT_API_BASE).rstrip("/")

    # -- API calls ----------------------------------------------------------

    def fetch_prims(
        self,
        space_id: Optional[str] = None,
        prim_type: Optional[str] = None,
        limit: int = 5000,
    ) -> FetchResult:
        """GET /api/v1/static/prims with optional query params."""
        t0 = time.time()
        params: list[str] = [f"limit={limit}"]
        if space_id:
            params.append(f"space_id={urllib.request.quote(space_id, safe='')}")
        if prim_type:
            params.append(f"prim_type={urllib.request.quote(prim_type, safe='')}")
        qs = "&".join(params)
        url = f"{self._api_base}/api/v1/static/prims?{qs}"

        try:
            raw = _http_get_with_retry(url)
            elapsed = (time.time() - t0) * 1000
            records = [
                PrimRecord(
                    prim_path=r.get("prim_path", ""),
                    prim_type=r.get("prim_type", "Unknown"),
                    space_id=r.get("space_id", ""),
                    properties=r.get("properties", {}),
                )
                for r in (raw if isinstance(raw, list) else raw.get("data", raw.get("prims", [])))
            ]
            return FetchResult(success=True, data=records, source="api", elapsed_ms=elapsed)
        except Exception as exc:
            elapsed = (time.time() - t0) * 1000
            return FetchResult(success=False, error=str(exc), source="api", elapsed_ms=elapsed)

    def fetch_type_distribution(self) -> FetchResult:
        """GET /api/v1/static/types."""
        t0 = time.time()
        url = f"{self._api_base}/api/v1/static/types"
        try:
            raw = _http_get_with_retry(url)
            elapsed = (time.time() - t0) * 1000
            counts = raw if isinstance(raw, dict) else raw.get("data", {})
            dist = TypeDistribution(type_counts=counts, total=sum(counts.values()))
            return FetchResult(success=True, data=dist, source="api", elapsed_ms=elapsed)
        except Exception as exc:
            elapsed = (time.time() - t0) * 1000
            return FetchResult(success=False, error=str(exc), source="api", elapsed_ms=elapsed)

    # -- Demo / fallback data -----------------------------------------------

    def generate_demo_prims(self) -> list[PrimRecord]:
        """Realistic demo hierarchy (~30 prims across 4 spaces)."""
        prims: list[PrimRecord] = []
        spaces = {
            "/World/RoomA": [
                ("Table_01", "Mesh"), ("Table_02", "Mesh"), ("Chair_01", "Mesh"),
                ("Chair_02", "Mesh"), ("Lamp_01", "Mesh"), ("Overhead", "DistantLight"),
                ("Cam_RoomA", "Camera"), ("Group_Furniture", "Xform"),
            ],
            "/World/RoomB": [
                ("Desk_01", "Mesh"), ("Monitor_01", "Mesh"), ("Keyboard_01", "Mesh"),
                ("ServerRack_01", "Mesh"), ("Cam_RoomB", "Camera"),
                ("Group_Equipment", "Xform"), ("Ceiling_Light", "DistantLight"),
            ],
            "/World/Hallway": [
                ("Floor", "Mesh"), ("Wall_Left", "Mesh"), ("Wall_Right", "Mesh"),
                ("EmergencyLight", "DistantLight"), ("HallCam", "Camera"),
                ("Corridor_Group", "Xform"),
            ],
            "/World/Lab": [
                ("Bench_01", "Mesh"), ("Microscope_01", "Mesh"),
                ("Fume_Hood", "Mesh"), ("Safety_Shower", "Mesh"),
                ("Lab_Scope", "Scope"), ("Lab_Light", "DistantLight"),
                ("Lab_Cam", "Camera"), ("Lab_Group", "Xform"),
                ("LabEnvironment", "Scope"),
            ],
        }
        for space_path, items in spaces.items():
            space_id = space_path.split("/")[-1]
            # Add the space root Xform
            prims.append(PrimRecord(prim_path=space_path, prim_type="Xform", space_id=space_id))
            for name, ptype in items:
                prims.append(PrimRecord(
                    prim_path=f"{space_path}/{name}",
                    prim_type=ptype,
                    space_id=space_id,
                ))
        return prims

    def generate_demo_types(self) -> TypeDistribution:
        """Derive type distribution from demo prims."""
        counts: Dict[str, int] = {}
        for p in self.generate_demo_prims():
            counts[p.prim_type] = counts.get(p.prim_type, 0) + 1
        return TypeDistribution(type_counts=counts, total=sum(counts.values()))
