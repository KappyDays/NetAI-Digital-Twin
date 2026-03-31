"""Nucleus Pipeline v2 CLI — Complete Stage Backup + Time Travel.

Usage:
    # Local file
    python main.py --local-path ./scene.usda --api-url http://localhost:8100

    # Nucleus server (requires omniverseclient)
    python main.py --nucleus-path omniverse://10.38.38.48/Projects/scene.usd --api-url http://localhost:8100

    # Raw folder backup (incremental)
    python main.py --raw-backup --nucleus-folder omniverse://10.38.38.48/Projects/MyScene/
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time


def raw_backup_main(args, backup_time=None):
    """Execute raw folder backup with incremental support."""
    start_time = time.time()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 60)
    print("Nucleus Pipeline: Raw Folder Backup (Incremental)")
    print("=" * 60)
    print(f"Source: {args.nucleus_folder}")
    print(f"API:    {args.api_url}")

    # ── Step 1: List all files in Nucleus folder ──────────────
    print("\nStep 1: Scanning Nucleus folder...")
    cmd = [sys.executable, os.path.join(script_dir, "nucleus_client.py"),
           "--list-folder", args.nucleus_folder]
    env = os.environ.copy()
    if args.nucleus_token:
        env["NUCLEUS_TOKEN"] = args.nucleus_token
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"Folder scan failed:\n{result.stderr}")
        sys.exit(1)

    current_files = json.loads(result.stdout.strip().split("\n")[-1])
    print(f"  Files found: {len(current_files)}")
    total_size = sum(f.get("file_size", 0) for f in current_files)
    print(f"  Total size:  {total_size / (1024*1024):.1f} MB")

    # ── Step 2: Get previous backup for incremental comparison ─
    print("\nStep 2: Checking previous backup...")
    from lakehouse_client import get_latest_raw_backup_files
    folder_path = args.nucleus_folder.rstrip("/")
    prev_time, prev_files = get_latest_raw_backup_files(args.api_url, folder_path=folder_path)

    if prev_time:
        print(f"  Previous backup: {prev_time} ({len(prev_files)} files)")
    else:
        print("  No previous backup found (first run)")

    # ── Step 3: Classify files (new/modified/deleted/unchanged) ─
    print("\nStep 3: Comparing files...")
    from lakehouse_client import generate_backup_time
    if backup_time is None:
        backup_time = generate_backup_time()

    # Build lookup from previous backup
    prev_lookup = {}
    for pf in prev_files:
        prev_lookup[pf["file_path"]] = pf

    # Classify current files
    new_files = []
    modified_files = []
    unchanged_files = []

    for cf in current_files:
        fp = cf["file_path"]
        if fp not in prev_lookup:
            cf["status"] = "new"
            new_files.append(cf)
        else:
            pf = prev_lookup[fp]
            if (str(cf.get("modified_time", "")) != str(pf.get("modified_time", ""))
                    or cf.get("file_size", 0) != pf.get("file_size", 0)):
                cf["status"] = "modified"
                cf["prev_s3_key"] = pf.get("s3_key")
                modified_files.append(cf)
            else:
                cf["status"] = "unchanged"
                cf["s3_key"] = pf.get("s3_key")  # reuse previous s3_key
                unchanged_files.append(cf)

    # Detect deleted files
    current_paths = {f["file_path"] for f in current_files}
    deleted_files = []
    for pf in prev_files:
        if pf["file_path"] not in current_paths:
            deleted_files.append({
                "file_path": pf["file_path"],
                "file_name": pf.get("file_name", ""),
                "file_extension": pf.get("file_extension", ""),
                "file_size": 0,
                "modified_time": pf.get("modified_time", ""),
                "s3_key": None,
                "status": "deleted",
            })

    print(f"  New:       {len(new_files)}")
    print(f"  Modified:  {len(modified_files)}")
    print(f"  Deleted:   {len(deleted_files)}")
    print(f"  Unchanged: {len(unchanged_files)}")

    # ── Step 4: Download changed files ────────────────────────
    files_to_download = new_files + modified_files
    download_success = {}
    download_failed = []

    if files_to_download:
        print(f"\nStep 4: Downloading {len(files_to_download)} files...")
        dest_dir = tempfile.mkdtemp(prefix="nucleus_raw_backup_")
        # Write file list to temp file to avoid Windows command-line length limit
        files_json_path = os.path.join(dest_dir, "_filelist.json")
        with open(files_json_path, "w", encoding="utf-8") as jf:
            json.dump(files_to_download, jf)
        cmd = [sys.executable, os.path.join(script_dir, "nucleus_client.py"),
               "--download-files", "@" + files_json_path, dest_dir]
        env = os.environ.copy()
        if args.nucleus_token:
            env["NUCLEUS_TOKEN"] = args.nucleus_token
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode == 0:
            try:
                last_line = result.stdout.strip().split("\n")[-1]
                dl_result = json.loads(last_line)
                download_success = dl_result.get("success", {})
                download_failed = dl_result.get("failed", [])
            except (json.JSONDecodeError, IndexError):
                print(f"  Download parsing failed: {result.stdout[:200]}")
        else:
            print(f"  Download failed:\n{result.stderr[:300]}")

        if download_failed:
            print(f"  Failed: {len(download_failed)} files")
            for f in download_failed[:5]:
                print(f"    {f.get('file_path', 'unknown')}: {f.get('error', 'unknown')}")
            if len(download_failed) > 5:
                print(f"    ... and {len(download_failed) - 5} more")
    else:
        print("\nStep 4: No files to download (all unchanged)")

    # ── Step 5: Upload to MinIO ───────────────────────────────
    from lakehouse_client import upload_raw_file
    safe_time = backup_time.replace(" ", "_").replace(":", "-")
    # Extract folder name from nucleus path for MinIO prefix
    folder_name = folder_path.rstrip("/").rsplit("/", 1)[-1]
    uploaded = 0

    if download_success:
        print(f"\nStep 5: Uploading {len(download_success)} files to MinIO...")
        # Compute folder prefix for relative paths
        folder_path = args.nucleus_folder.rstrip("/")

        for file_path, local_path in download_success.items():
            # Compute relative path from nucleus folder
            if file_path.startswith(folder_path):
                rel_path = file_path[len(folder_path):].lstrip("/")
            else:
                rel_path = os.path.basename(file_path)
            # Sanitize: prevent path traversal in S3 keys
            rel_path = rel_path.replace("\\", "/")
            while "../" in rel_path:
                rel_path = rel_path.replace("../", "")
            rel_path = rel_path.lstrip("/")

            s3_key = f"raw-backups/{folder_name}/{safe_time}/{rel_path}"
            try:
                upload_raw_file(args.api_url, local_path, s3_key)
                # Update the file record with s3_key
                for f in files_to_download:
                    if f["file_path"] == file_path:
                        f["s3_key"] = s3_key
                        break
                uploaded += 1
            except Exception as e:
                print(f"  Upload failed: {rel_path} ({e})")
        print(f"  Uploaded: {uploaded} files")
    else:
        print("\nStep 5: No files to upload")

    # ── Step 6: Record in Iceberg ─────────────────────────────
    print(f"\nStep 6: Recording backup metadata in Iceberg...")
    from lakehouse_client import send_raw_backup_files

    # Build complete snapshot records (only successfully processed files)
    failed_paths = {f.get("file_path") for f in download_failed}
    all_records = []

    for f in new_files + modified_files:
        if f["file_path"] not in failed_paths and f.get("s3_key"):
            all_records.append({
                "file_path": f["file_path"],
                "file_name": f.get("file_name", ""),
                "file_extension": f.get("file_extension", ""),
                "file_size": f.get("file_size", 0),
                "modified_time": str(f.get("modified_time", "")),
                "s3_key": f.get("s3_key"),
                "status": f["status"],
            })

    for f in unchanged_files:
        s3_key = f.get("s3_key")
        if not s3_key:
            print(f"  WARNING: unchanged file has no s3_key (skipped): {f.get('file_path', 'unknown')}")
            continue
        all_records.append({
            "file_path": f["file_path"],
            "file_name": f.get("file_name", ""),
            "file_extension": f.get("file_extension", ""),
            "file_size": f.get("file_size", 0),
            "modified_time": str(f.get("modified_time", "")),
            "s3_key": s3_key,
            "status": "unchanged",
        })

    for f in deleted_files:
        all_records.append(f)

    try:
        api_result = send_raw_backup_files(
            api_url=args.api_url,
            backup_time=backup_time,
            files=all_records,
            folder_path=folder_path,
        )
        print(f"  Recorded: {api_result.get('files_inserted', 0)} file records")
    except Exception as e:
        print(f"  ERROR: Failed to record in Iceberg: {e}")
        sys.exit(1)

    # ── Step 7: Summary ───────────────────────────────────────
    elapsed = time.time() - start_time
    dl_size = sum(f.get("file_size", 0) for f in new_files + modified_files
                  if f["file_path"] not in failed_paths)

    print("\n" + "=" * 60)
    print("Raw Backup Complete")
    print("=" * 60)
    print(f"  Backup time:  {backup_time}")
    print(f"  New:          {len(new_files)}")
    print(f"  Modified:     {len(modified_files)}")
    print(f"  Deleted:      {len(deleted_files)}")
    print(f"  Unchanged:    {len(unchanged_files)}")
    print(f"  Failed:       {len(download_failed)}")
    print(f"  Uploaded:     {uploaded} files ({dl_size / (1024*1024):.1f} MB)")
    print(f"  Total files:  {len(all_records)}")
    print(f"  Elapsed:      {elapsed:.2f}s")
    print("=" * 60)


def entity_backup_main(args, backup_time=None):
    """Execute entity-level USD backup (Task 2)."""
    start_time = time.time()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    print("=" * 60)
    print("Nucleus Pipeline v2: Complete Stage Backup + Time Travel")
    print("=" * 60)

    # ── Step 1: Resolve input file ────────────────────────────
    if args.local_path:
        from nucleus_client import resolve_local_path
        local_path = resolve_local_path(args.local_path)
        backup_source = args.backup_source or "local"
        print(f"Input: {local_path} (local file)")
    else:
        print(f"Input: {args.nucleus_path} (Nucleus server)")
        print("Downloading from Nucleus (subprocess)...")
        dest_dir = tempfile.mkdtemp(prefix="nucleus_pipeline_")
        cmd = [sys.executable, os.path.join(script_dir, "nucleus_client.py"),
               args.nucleus_path, dest_dir]
        if args.nucleus_token:
            cmd.append(args.nucleus_token)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Download failed:\n{result.stderr}")
            sys.exit(1)
        local_path = result.stdout.strip().split("\n")[-1]
        backup_source = args.backup_source or "nucleus"
        print(f"Downloaded to: {local_path}")

    # ── Step 2: Parse USD — Entity ID + Override + Asset URLs ─
    print("\nParsing USD file...")
    from usd_parser import parse_usd
    entities, prim_snapshots, asset_urls = parse_usd(local_path)
    print(f"  Entities found: {len(entities)}")
    print(f"  Prim snapshots: {len(prim_snapshots)}")
    print(f"  Asset URLs:     {len(asset_urls)} ({len(set(asset_urls.values()))} unique)")

    if not entities:
        print("\nNo entities found. Nothing to backup.")
        sys.exit(0)

    # Print entity summary
    print("\n  Entity summary:")
    for e in entities:
        override_count = sum(1 for p in prim_snapshots if p["entity_path"] == e["entity_path"])
        url = asset_urls.get(e["entity_path"], "")
        url_short = os.path.basename(url) if url else "(container)"
        print(f"    {e['entity_path']} ({e['entity_type']}) — {override_count} override(s), asset={url_short}")

    # ── Step 3: Generate root.usda ────────────────────────────
    print("\nGenerating root.usda...")
    from usd_parser import generate_root_usda
    work_dir = tempfile.mkdtemp(prefix="nucleus_backup_")
    root_usda_path = os.path.join(work_dir, "root.usda")
    generate_root_usda(local_path, asset_urls, root_usda_path)
    print(f"  root.usda generated: {root_usda_path}")

    # ── Step 4: Download Entity USD files (Nucleus only) ────────
    # HTTPS/CDN assets (NVIDIA S3) are NOT downloaded — they are permanently
    # hosted and root.usda references them by original URL.
    # Only omniverse:// assets (user's Nucleus server) are downloaded as backup.
    entity_usd_paths = {}  # {url: local_path}
    omniverse_urls = {k: v for k, v in asset_urls.items() if v.startswith("omniverse://")}
    https_count = sum(1 for v in asset_urls.values() if v.startswith("https://") or v.startswith("http://"))

    if https_count:
        print(f"\n  Skipping {https_count} CDN asset(s) (NVIDIA S3 — permanently hosted)")

    if omniverse_urls and not args.skip_usd_upload:
        entities_dir = os.path.join(work_dir, "entities")
        os.makedirs(entities_dir, exist_ok=True)
        unique_count = len(set(omniverse_urls.values()))
        print(f"\nDownloading Nucleus Entity USDs ({unique_count} unique)...")
        urls_json = json.dumps(dict(omniverse_urls))
        cmd = [sys.executable, os.path.join(script_dir, "nucleus_client.py"),
               "--entity-usds", urls_json, work_dir]
        if args.nucleus_token:
            cmd.append(args.nucleus_token)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                last_line = result.stdout.strip().split("\n")[-1]
                entity_usd_paths.update(json.loads(last_line))
                print(f"  Downloaded: {len(entity_usd_paths)} files")
            except (json.JSONDecodeError, IndexError):
                print(f"  Download parsing failed: {result.stdout[:200]}")
        else:
            print(f"  Nucleus download failed (non-fatal):\n  {result.stderr[:300]}")

    # ── Step 5: Upload to MinIO ───────────────────────────────
    from lakehouse_client import generate_backup_time, upload_usd_files
    if backup_time is None:
        backup_time = generate_backup_time()
    usd_uploaded = 0

    if not args.skip_usd_upload:
        print(f"\nUploading USD files to MinIO...")
        try:
            upload_result = upload_usd_files(
                api_url=args.api_url,
                backup_time=backup_time,
                root_usda_path=root_usda_path,
                entity_usd_paths=entity_usd_paths,
            )
            usd_uploaded = upload_result.get("uploaded", 0)
            print(f"  Total uploaded: {usd_uploaded} files")
        except Exception as e:
            print(f"  MinIO upload failed (non-fatal): {e}")
    else:
        print("\n  USD upload skipped (--skip-usd-upload)")

    # ── Step 6: Save to Iceberg ───────────────────────────────
    print(f"\nSending to Lakehouse API ({args.api_url})...")
    from lakehouse_client import send_backup
    try:
        api_result = send_backup(
            api_url=args.api_url,
            entities=entities,
            prim_snapshots=prim_snapshots,
            backup_source=backup_source,
            backup_time=backup_time,
        )
        elapsed = time.time() - start_time

        # ── Step 7: Summary ───────────────────────────────────
        print("\n" + "=" * 60)
        print("Backup Complete")
        print("=" * 60)
        print(f"  Status:            {api_result.get('status', 'unknown')}")
        print(f"  Entities inserted:  {api_result.get('entities_inserted', 0)}")
        print(f"  Prims inserted:     {api_result.get('prims_inserted', 0)}")
        print(f"  USD files uploaded:  {usd_uploaded}")
        print(f"  Backup time:        {api_result.get('backup_time', backup_time)}")
        print(f"  Backup source:      {backup_source}")
        print(f"  Elapsed:            {elapsed:.2f}s")
        print("=" * 60)

    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\nERROR: Failed to send backup to API: {e}")
        print(f"  Elapsed: {elapsed:.2f}s")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Nucleus Pipeline v2: Complete Stage Backup + Time Travel"
    )
    # Existing Prim backup mode
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--local-path", help="Path to a local .usd/.usda file")
    group.add_argument("--nucleus-path", help="Nucleus path (omniverse://server/path/scene.usd)")

    # Raw backup mode
    parser.add_argument("--raw-backup", action="store_true", help="Raw folder backup mode (download entire Nucleus folder)")
    parser.add_argument("--nucleus-folder", help="Nucleus folder path for raw backup (omniverse://server/path/folder)")

    # Full backup mode (Task 1 + Task 2 combined)
    parser.add_argument("--full-backup", action="store_true",
                        help="Full backup mode: run raw backup (Task 1) + entity backup (Task 2) with shared backup_time")

    # Common args
    parser.add_argument(
        "--api-url",
        default=os.getenv("LAKEHOUSE_API_URL", "http://localhost:8100"),
        help="Lakehouse API base URL (default: http://localhost:8100)",
    )
    parser.add_argument(
        "--nucleus-token",
        default=os.getenv("NUCLEUS_TOKEN", ""),
        help="Nucleus auth token (or set NUCLEUS_TOKEN env var)",
    )
    parser.add_argument("--backup-source", default=None, help="Override backup_source label")
    parser.add_argument("--skip-usd-upload", action="store_true", help="Skip USD file upload to MinIO")
    parser.add_argument("--backup-time", default=None,
                        help="Pre-generated backup timestamp (used internally by --full-backup)")

    args = parser.parse_args()

    if args.full_backup:
        if not args.nucleus_folder:
            parser.error("--full-backup requires --nucleus-folder")
        if not args.nucleus_path:
            parser.error("--full-backup requires --nucleus-path")
        from lakehouse_client import generate_backup_time
        shared_backup_time = args.backup_time or generate_backup_time()
        print(f"Full Backup mode: shared backup_time = {shared_backup_time}")
        raw_backup_main(args, backup_time=shared_backup_time)
        entity_backup_main(args, backup_time=shared_backup_time)
        return

    if args.raw_backup:
        if not args.nucleus_folder:
            parser.error("--raw-backup requires --nucleus-folder")
        raw_backup_main(args, backup_time=args.backup_time)
        return
    elif not args.local_path and not args.nucleus_path:
        parser.error("Either --local-path, --nucleus-path, --raw-backup, or --full-backup is required")

    entity_backup_main(args, backup_time=args.backup_time)


if __name__ == "__main__":
    main()
