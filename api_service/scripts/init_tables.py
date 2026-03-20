#!/usr/bin/env python3
"""
Standalone catalog initialization script.

Creates Iceberg namespaces and tables required by the Lakehouse API.
Can be run independently of FastAPI for headless/CI setup.

Usage:
    # From api_service directory:
    python -m scripts.init_tables

    # Or directly:
    python scripts/init_tables.py

    # Flags:
    python -m scripts.init_tables --no-wait     # Skip Trino readiness check
    python -m scripts.init_tables --describe     # Print schema definitions only
    python -m scripts.init_tables --verify-only  # Verify existing schemas
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the parent (api_service/) is on sys.path so app.* imports work
_this = Path(__file__).resolve()
_api_root = _this.parent.parent
if str(_api_root) not in sys.path:
    sys.path.insert(0, str(_api_root))

from app.core.logging import logger
from app.services.catalog_init import (
    DYNAMIC_OBJECT_TABLE_TEMPLATE,
    STATIC_PRIMS_TABLE,
    bootstrap_catalog,
    describe_table,
    get_catalog_status,
    verify_schema_via_trino,
)


def main():
    parser = argparse.ArgumentParser(
        description="Initialize Iceberg Lakehouse catalog tables"
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Skip waiting for Trino readiness",
    )
    parser.add_argument(
        "--describe",
        action="store_true",
        help="Print table schema definitions and exit (no DB connection needed)",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify existing schemas against expected (requires Trino)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=15,
        help="Max retries when waiting for Trino (default: 15)",
    )
    args = parser.parse_args()

    # ── Describe mode (offline) ───────────────────────────────────────
    if args.describe:
        print("=" * 70)
        print("  Lakehouse Table Definitions")
        print("=" * 70)
        for tbl in (STATIC_PRIMS_TABLE, DYNAMIC_OBJECT_TABLE_TEMPLATE):
            info = describe_table(tbl)
            print(f"\n{'─' * 60}")
            print(f"  {info['fqn']}")
            print(f"  {info['description'][:80]}")
            print(f"{'─' * 60}")
            print(f"  Columns ({info['column_count']}):")
            for col in info["columns"]:
                req = " [REQUIRED]" if col["required"] else ""
                print(f"    {col['field_id']:>2}. {col['name']:<16s} {col['trino_type']:<16s}{req}")
                if col["description"]:
                    print(f"        {col['description']}")
            if info["partition_columns"]:
                print(f"  Partition: {info['partition_columns']}")
            print(f"\n  DDL:\n{info['trino_ddl']}")
        return 0

    # ── Verify-only mode ──────────────────────────────────────────────
    if args.verify_only:
        print("Verifying schema for static_prims...")
        check = verify_schema_via_trino(STATIC_PRIMS_TABLE)
        print(json.dumps(check.to_dict(), indent=2))
        return 0 if check.matches else 1

    # ── Full bootstrap ────────────────────────────────────────────────
    print("Starting Lakehouse catalog initialization...")
    result = bootstrap_catalog(
        wait_for_trino=not args.no_wait,
        verify_schemas=True,
        max_retries=args.max_retries,
    )

    print(json.dumps(result.to_dict(), indent=2))

    if result.success:
        print("\nCatalog initialization completed successfully.")
        return 0
    else:
        print("\nCatalog initialization FAILED.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
