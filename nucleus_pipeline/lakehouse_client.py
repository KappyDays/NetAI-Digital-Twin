"""HTTP client for Lakehouse API — sends backup data and uploads USD files."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests


def generate_backup_time() -> str:
    """Generate a backup timestamp string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def send_backup(
    api_url: str,
    entities: list[dict],
    prim_snapshots: list[dict],
    backup_source: str = "local",
    backup_time: str | None = None,
) -> dict:
    """Send entity backup data to the Lakehouse API.

    Args:
        api_url: Base URL of Lakehouse API (e.g. http://localhost:8100)
        entities: List of entity dicts matching EntityRecord schema
        prim_snapshots: List of prim snapshot dicts matching PrimSnapshotRecord schema
        backup_source: "local" | "nucleus" | "extension"
        backup_time: Timestamp string. Auto-generated if None.

    Returns:
        API response dict
    """
    backup_time = backup_time or generate_backup_time()

    payload = {
        "backup_time": backup_time,
        "backup_source": backup_source,
        "entities": entities,
        "prim_snapshots": prim_snapshots,
    }

    url = f"{api_url.rstrip('/')}/api/v1/entities/backup"
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def upload_usd_files(
    api_url: str,
    backup_time: str,
    root_usda_path: str,
    entity_usd_paths: dict[str, str],
) -> dict:
    """Upload root.usda + Entity USD files to MinIO via Lakehouse API.

    Args:
        api_url: Base URL of Lakehouse API
        backup_time: Timestamp string for folder structure
        root_usda_path: Local path to generated root.usda
        entity_usd_paths: {original_url: local_file_path}

    Returns:
        {"uploaded": count}
    """
    base_url = api_url.rstrip("/")
    # Sanitize backup_time for S3 key (replace spaces/colons)
    safe_time = backup_time.replace(" ", "_").replace(":", "-")
    uploaded = 0

    # 1. Upload root.usda
    s3_key = f"backups/{safe_time}/root.usda"
    _upload_single(base_url, root_usda_path, s3_key)
    uploaded += 1
    print(f"  Uploaded: {s3_key}")

    # 2. Upload Entity USD files (deduplicated by local path)
    seen_paths = set()
    for orig_url, local_path in entity_usd_paths.items():
        if local_path in seen_paths:
            continue
        seen_paths.add(local_path)
        filename = Path(local_path).name
        s3_key = f"backups/{safe_time}/entities/{filename}"
        _upload_single(base_url, local_path, s3_key)
        uploaded += 1
        print(f"  Uploaded: {s3_key}")

    return {"uploaded": uploaded, "backup_folder": f"backups/{safe_time}/"}


def _upload_single(base_url: str, local_path: str, s3_key: str):
    """Upload a single file to MinIO via POST /api/v1/upload-usd with s3_key."""
    url = f"{base_url}/api/v1/upload-usd"
    filename = Path(local_path).name
    with open(local_path, "rb") as f:
        files = {"file": (filename, f, "application/octet-stream")}
        data = {"s3_key": s3_key}
        resp = requests.post(url, files=files, data=data, timeout=120)
    resp.raise_for_status()


def send_raw_backup_files(
    api_url: str,
    backup_time: str,
    files: list[dict],
    backup_source: str = "nucleus",
    folder_path: str = "",
) -> dict:
    """Send raw backup file metadata to the Lakehouse API.

    Args:
        api_url: Base URL of Lakehouse API (e.g. http://localhost:8100)
        backup_time: Timestamp string
        files: List of file record dicts (file_path, file_name, file_extension,
               file_size, modified_time, s3_key, status)
        backup_source: "nucleus"
        folder_path: Nucleus folder path (for per-folder incremental comparison)

    Returns:
        API response dict
    """
    payload = {
        "backup_time": backup_time,
        "backup_source": backup_source,
        "folder_path": folder_path,
        "files": files,
    }
    url = f"{api_url.rstrip('/')}/api/v1/raw-backup/files"
    resp = requests.post(url, json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json()


def get_latest_raw_backup_files(
    api_url: str,
    folder_path: str = "",
) -> tuple[str | None, list[dict]]:
    """Get the most recent raw backup file list for incremental comparison.

    Args:
        api_url: Base URL of Lakehouse API
        folder_path: Nucleus folder path to filter by (for per-folder comparison)

    Returns:
        (backup_time, files_list) or (None, []) if no previous backup exists
    """
    url = f"{api_url.rstrip('/')}/api/v1/raw-backup/latest-files"
    if folder_path:
        url += f"?folder_path={folder_path}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        backup_time = data.get("backup_time")
        files = data.get("files", [])
        if not backup_time:
            return None, []
        return backup_time, files
    except requests.exceptions.RequestException as e:
        print(f"  WARNING: Could not fetch previous backup ({e}). Treating as first run.")
        return None, []


def upload_raw_file(api_url: str, local_path: str, s3_key: str):
    """Upload a single raw backup file to MinIO via the existing upload endpoint.

    Args:
        api_url: Base URL of Lakehouse API
        local_path: Path to local file
        s3_key: Target S3 key in MinIO
    """
    _upload_single(api_url.rstrip("/"), local_path, s3_key)
