"""Pydantic schemas for Nucleus Raw Backup system."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel


class RawBackupFileRecord(BaseModel):
    """Single file record in a raw backup snapshot."""
    file_path: str          # Nucleus original path (omniverse://...)
    file_name: str          # filename
    file_extension: str     # extension (.usd, .png, .mdl etc)
    file_size: int          # bytes
    modified_time: str      # Nucleus server modified time (ISO format)
    s3_key: Optional[str] = None  # MinIO storage path (None for deleted)
    status: Literal["new", "modified", "deleted", "unchanged"] = "new"


class RawBackupFilesRequest(BaseModel):
    """Bulk insert request for raw backup file records."""
    backup_time: str
    backup_source: str = "nucleus"
    folder_path: str = ""  # Nucleus folder path (for per-folder incremental comparison)
    files: List[RawBackupFileRecord]


class RawBackupFilesResponse(BaseModel):
    status: str = "ok"
    files_inserted: int = 0
    backup_time: str = ""


class RawBackupTimesResponse(BaseModel):
    backup_times: List[str]


class RawBackupDiffResponse(BaseModel):
    time_a: str
    time_b: str
    new: int = 0
    modified: int = 0
    deleted: int = 0
    unchanged: int = 0
    files: List[dict]
