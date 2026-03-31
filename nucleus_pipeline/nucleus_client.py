"""Nucleus file download client — omniverseclient SDK or local file passthrough."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

try:
    import omni.client as _omni_client

    HAS_OMNICLIENT = True
except ImportError:
    HAS_OMNICLIENT = False


def download_from_nucleus(
    nucleus_path: str,
    token: str | None = None,
    dest_dir: str | None = None,
) -> str:
    """Download a USD file from Nucleus using omniverseclient SDK.

    Args:
        nucleus_path: omniverse://server/path/scene.usd
        token: Nucleus auth token (optional)
        dest_dir: Directory to save downloaded files. Uses temp dir if None.

    Returns:
        Local file path of the downloaded USD file.

    Raises:
        ImportError: If omniverseclient is not installed.
        RuntimeError: If download fails.
    """
    if not HAS_OMNICLIENT:
        raise ImportError(
            "omniverseclient is not installed. Install with:\n"
            "  pip install omniverseclient --extra-index-url https://pypi.nvidia.com\n"
            "Requires Python 3.10-3.12."
        )

    _omni_client.initialize()

    # Register auth callback if token provided
    if token:

        def auth_callback(prefix):
            return (token, token)

        _omni_client.register_authentication_callback(auth_callback)

    # Determine destination path
    if dest_dir is None:
        dest_dir = tempfile.mkdtemp(prefix="nucleus_pipeline_")
    os.makedirs(dest_dir, exist_ok=True)

    filename = Path(nucleus_path).name
    local_path = os.path.join(dest_dir, filename)

    # Read file from Nucleus
    result, _, content = _omni_client.read_file(nucleus_path)
    if result != _omni_client.Result.OK:
        _omni_client.shutdown()
        raise RuntimeError(f"Failed to read {nucleus_path}: {result}")

    with open(local_path, "wb") as f:
        f.write(memoryview(content))

    # Download sublayers if any (graceful — skip if pxr DLL conflicts with omniverseclient)
    try:
        _download_sublayers(nucleus_path, local_path, dest_dir)
    except (ImportError, OSError) as e:
        print(f"  SubLayer check skipped (DLL conflict): {e}")

    _omni_client.shutdown()
    return local_path


def _download_sublayers(
    nucleus_base_path: str,
    local_usd_path: str,
    dest_dir: str,
) -> list[str]:
    """Parse sublayer references from a USD file and download them.

    Args:
        nucleus_base_path: Original Nucleus path (for resolving relative refs)
        local_usd_path: Local path of the downloaded root USD file
        dest_dir: Directory to save sublayer files

    Returns:
        List of downloaded sublayer local paths.
    """
    from pxr import Sdf

    layer = Sdf.Layer.FindOrOpen(local_usd_path)
    if not layer:
        return []

    sublayer_paths = list(layer.subLayerPaths)
    if not sublayer_paths:
        return []

    # Resolve relative paths against the Nucleus base directory
    nucleus_dir = nucleus_base_path.rsplit("/", 1)[0]
    downloaded = []

    for sub_path in sublayer_paths:
        if sub_path.startswith("omniverse://") or sub_path.startswith("http"):
            # Absolute Nucleus path
            full_path = sub_path
        else:
            # Relative path — resolve against Nucleus directory
            full_path = f"{nucleus_dir}/{sub_path}"

        try:
            sub_filename = Path(sub_path).name
            sub_local = os.path.join(dest_dir, sub_filename)

            result, _, content = _omni_client.read_file(full_path)
            if result == _omni_client.Result.OK:
                with open(sub_local, "wb") as f:
                    f.write(memoryview(content))
                downloaded.append(sub_local)
                print(f"  SubLayer downloaded: {sub_path}")
            else:
                print(f"  SubLayer download failed: {sub_path} ({result})")
        except Exception as e:
            print(f"  SubLayer download error: {sub_path} ({e})")

    return downloaded


def download_entity_usds(
    asset_urls: dict[str, str],
    dest_dir: str,
    token: str | None = None,
) -> dict[str, str]:
    """Download original Entity USD files from Nucleus.

    Deduplicates by URL — same asset referenced by multiple entities is downloaded once.

    Args:
        asset_urls: {entity_path: "omniverse://server/path/asset.usd"}
        dest_dir: Directory to save entity USD files (entities/ subfolder created)
        token: Nucleus auth token (optional)

    Returns:
        {original_url: local_file_path} for successfully downloaded files
    """
    if not HAS_OMNICLIENT:
        raise ImportError(
            "omniverseclient is not installed. Install with:\n"
            "  pip install omniverseclient --extra-index-url https://pypi.nvidia.com"
        )

    entities_dir = os.path.join(dest_dir, "entities")
    os.makedirs(entities_dir, exist_ok=True)

    # Deduplicate: unique URLs only
    unique_urls = set(asset_urls.values())
    downloaded = {}

    _omni_client.initialize()
    if token:
        def auth_callback(prefix):
            return (token, token)
        _omni_client.register_authentication_callback(auth_callback)

    for url in unique_urls:
        if not url:
            continue
        filename = Path(url).name
        local_path = os.path.join(entities_dir, filename)

        try:
            result, _, content = _omni_client.read_file(url)
            if result == _omni_client.Result.OK:
                with open(local_path, "wb") as f:
                    f.write(memoryview(content))
                downloaded[url] = local_path
                print(f"  Entity USD downloaded: {filename} ({url})")
            else:
                print(f"  Entity USD download failed: {filename} ({result})")
        except Exception as e:
            print(f"  Entity USD download error: {filename} ({e})")

    _omni_client.shutdown()
    return downloaded


def resolve_local_path(file_path: str) -> str:
    """Validate and return absolute path for a local USD file."""
    abs_path = os.path.abspath(file_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"USD file not found: {abs_path}")
    return abs_path


def list_folder_recursive(
    folder_path: str,
    token: str | None = None,
) -> list[dict]:
    """Recursively list all files in a Nucleus folder.

    Args:
        folder_path: omniverse://server/path/folder
        token: Nucleus auth token (optional)

    Returns:
        List of dicts: [{"file_path": "omniverse://...", "file_name": "...",
                         "file_extension": ".usd", "file_size": 12345,
                         "modified_time": "2026-03-30T10:00:00Z"}]
    """
    if not HAS_OMNICLIENT:
        raise ImportError(
            "omniverseclient is not installed. Install with:\n"
            "  pip install omniverseclient --extra-index-url https://pypi.nvidia.com"
        )

    _omni_client.initialize()

    if token:

        def auth_callback(prefix):
            return (token, token)

        _omni_client.register_authentication_callback(auth_callback)

    def _collect_files(path: str) -> list[dict]:
        files = []
        result, entries = _omni_client.list(path)
        if result != _omni_client.Result.OK:
            print(f"  Failed to list {path}: {result}")
            return files

        for entry in entries:
            full_path = path.rstrip("/") + "/" + entry.relative_path
            if entry.flags & _omni_client.ItemFlags.CAN_HAVE_CHILDREN:
                files.extend(_collect_files(full_path))
            else:
                name = os.path.basename(entry.relative_path)
                _, ext = os.path.splitext(name)
                mt = entry.modified_time
                if hasattr(mt, "isoformat"):
                    modified_str = mt.isoformat()
                else:
                    from datetime import datetime, timezone
                    modified_str = datetime.fromtimestamp(mt, tz=timezone.utc).isoformat()
                files.append(
                    {
                        "file_path": full_path,
                        "file_name": name,
                        "file_extension": ext,
                        "file_size": entry.size,
                        "modified_time": modified_str,
                    }
                )
        return files

    try:
        result = _collect_files(folder_path)
    finally:
        _omni_client.shutdown()
    return result


def download_files(
    file_list: list[dict],
    dest_dir: str,
    token: str | None = None,
    base_folder: str | None = None,
) -> tuple[dict, list[dict]]:
    """Download multiple files from Nucleus with retry logic.

    Args:
        file_list: List of file dicts with 'file_path' key
        dest_dir: Local directory to save files
        token: Nucleus auth token (optional)

    Returns:
        (success_map: {file_path: local_path}, failed_list: [{"file_path": ..., "error": ...}])
    """
    if not HAS_OMNICLIENT:
        raise ImportError(
            "omniverseclient is not installed. Install with:\n"
            "  pip install omniverseclient --extra-index-url https://pypi.nvidia.com"
        )

    _omni_client.initialize()

    if token:

        def auth_callback(prefix):
            return (token, token)

        _omni_client.register_authentication_callback(auth_callback)

    # Find common prefix for relative path computation
    if base_folder:
        common_prefix = base_folder.rstrip("/") + "/"
    else:
        paths = [f["file_path"] for f in file_list]
        common_prefix = os.path.commonprefix(paths)
        common_prefix = common_prefix[: common_prefix.rfind("/") + 1]

    os.makedirs(dest_dir, exist_ok=True)
    success_map: dict[str, str] = {}
    failed_list: list[dict] = []
    total = len(file_list)

    try:
        for idx, file_info in enumerate(file_list, 1):
            file_path = file_info["file_path"]
            rel_path = file_path[len(common_prefix) :] if common_prefix else os.path.basename(file_path)
            local_path = os.path.join(dest_dir, rel_path)

            # Prevent path traversal
            local_path = os.path.realpath(local_path)
            dest_real = os.path.realpath(dest_dir)
            if not local_path.startswith(dest_real + os.sep) and local_path != dest_real:
                failed_list.append({"file_path": file_path, "error": "path traversal detected"})
                continue

            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            file_size = file_info.get("file_size", 0)
            size_mb = file_size / (1024 * 1024) if file_size else 0
            name = os.path.basename(file_path)
            print(f"[{idx}/{total}] Downloading {name} ({size_mb:.1f} MB)...")

            last_error = None
            for attempt in range(3):
                try:
                    result, _, content = _omni_client.read_file(file_path)
                    if result == _omni_client.Result.OK:
                        with open(local_path, "wb") as f:
                            f.write(memoryview(content))
                        success_map[file_path] = local_path
                        last_error = None
                        break
                    else:
                        last_error = f"read_file returned {result}"
                except Exception as e:
                    last_error = str(e)

                if attempt < 2:
                    time.sleep(1)

            if last_error:
                failed_list.append({"file_path": file_path, "error": last_error})
    finally:
        _omni_client.shutdown()
    return success_map, failed_list


if __name__ == "__main__":
    """Standalone mode — runs in subprocess to avoid DLL conflicts with PyUSD.

    Mode 1 (download root): python nucleus_client.py <nucleus_path> <dest_dir> [token]
    Mode 2 (download entities): python nucleus_client.py --entity-usds <json_urls> <dest_dir> [token]

    Prints the local file path(s) as the last line of stdout.
    """
    import json as _json
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "--entity-usds":
        # Mode 2: Download entity USD files
        urls_json = sys.argv[2]
        dest_dir = sys.argv[3]
        token = sys.argv[4] if len(sys.argv) > 4 else None
        asset_urls = _json.loads(urls_json)
        result = download_entity_usds(asset_urls, dest_dir, token=token)
        # Output as JSON: {url: local_path}
        print(_json.dumps(result))
    elif len(sys.argv) >= 3 and sys.argv[1] == "--list-folder":
        # Mode 3: List folder recursively
        folder_path = sys.argv[2]
        token = os.environ.get("NUCLEUS_TOKEN") or (sys.argv[3] if len(sys.argv) > 3 else None)
        files = list_folder_recursive(folder_path, token=token)
        print(_json.dumps(files))
    elif len(sys.argv) >= 4 and sys.argv[1] == "--download-files":
        # Mode 4: Download files from JSON list (or @filepath for large lists)
        files_arg = sys.argv[2]
        dest_dir = sys.argv[3]
        token = os.environ.get("NUCLEUS_TOKEN") or (sys.argv[4] if len(sys.argv) > 4 else None)
        if files_arg.startswith("@"):
            with open(files_arg[1:], "r", encoding="utf-8") as _f:
                file_list = _json.load(_f)
        else:
            file_list = _json.loads(files_arg)
        success, failed = download_files(file_list, dest_dir, token=token)
        print(_json.dumps({"success": success, "failed": failed}))
    elif len(sys.argv) >= 3:
        # Mode 1: Download root USD file
        nucleus_path = sys.argv[1]
        dest_dir = sys.argv[2]
        token = sys.argv[3] if len(sys.argv) > 3 else None
        local_path = download_from_nucleus(nucleus_path, token=token, dest_dir=dest_dir)
        print(local_path)
    else:
        print("Usage:", file=sys.stderr)
        print("  python nucleus_client.py <nucleus_path> <dest_dir> [token]", file=sys.stderr)
        print("  python nucleus_client.py --entity-usds '<json_urls>' <dest_dir> [token]", file=sys.stderr)
        print("  python nucleus_client.py --list-folder <folder_path> [token]", file=sys.stderr)
        print("  python nucleus_client.py --download-files '<json_file_list>' <dest_dir> [token]", file=sys.stderr)
        sys.exit(1)
