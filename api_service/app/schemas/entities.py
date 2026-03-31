"""Pydantic schemas for Entity-Level backup/restore/diff system."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ── Backup Request/Response ───────────────────────────────────────────

class EntityRecord(BaseModel):
    entity_id: str
    entity_path: str
    entity_type: str
    source_type: str = ""
    source_asset: str = ""
    is_dynamic: bool = False
    dynamic_table: str = ""
    child_count: int = 0
    entity_hash: str = ""
    usd_file_path: str = ""


class PrimSnapshotRecord(BaseModel):
    entity_path: str
    relative_path: str
    prim_type: str
    properties: str = "{}"
    prim_hash: str = ""


class EntityBackupRequest(BaseModel):
    backup_time: str
    backup_source: str = "extension"  # "extension" | "nucleus" | "local"
    entities: List[EntityRecord]
    prim_snapshots: List[PrimSnapshotRecord]


class EntityBackupResponse(BaseModel):
    status: str = "ok"
    entities_inserted: int = 0
    prims_inserted: int = 0
    backup_time: str = ""


# ── List / Query ──────────────────────────────────────────────────────

class EntityListResponse(BaseModel):
    backup_time: str
    entities: List[dict]


class BackupTimesResponse(BaseModel):
    backup_times: List[str]
    backup_sources: List[str] = []


# ── Diff ──────────────────────────────────────────────────────────────

class EntityDiffItem(BaseModel):
    entity_path: str
    status: str  # "added", "removed", "changed", "unchanged"
    hash_a: Optional[str] = None
    hash_b: Optional[str] = None
    entity_type: Optional[str] = None


class EntityDiffResponse(BaseModel):
    time_a: str
    time_b: str
    total_a: int = 0
    total_b: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    unchanged: int = 0
    entities: List[EntityDiffItem]


class PrimDiffItem(BaseModel):
    relative_path: str
    status: str  # "added", "removed", "changed", "unchanged"
    prim_type: Optional[str] = None
    hash_a: Optional[str] = None
    hash_b: Optional[str] = None
    properties_a: Optional[str] = None
    properties_b: Optional[str] = None


class PrimDiffResponse(BaseModel):
    entity_path: str
    time_a: str
    time_b: str
    added: int = 0
    removed: int = 0
    changed: int = 0
    unchanged: int = 0
    prims: List[PrimDiffItem]


# ── Restore ───────────────────────────────────────────────────────────

class EntityRestoreResponse(BaseModel):
    entity_path: str
    backup_time: str
    entity: Optional[dict] = None
    prim_snapshots: List[dict] = []


# ── Sample IoT ────────────────────────────────────────────────────────

class SampleIoTRequest(BaseModel):
    entity_path: str = "/World/Robots/Jetbot"
    count: int = Field(default=10, ge=1, le=1000)


class SampleIoTResponse(BaseModel):
    status: str = "ok"
    entity_path: str
    records_generated: int = 0
    table_name: str = ""
