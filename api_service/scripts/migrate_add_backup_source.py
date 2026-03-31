"""One-time migration: add backup_source column to entities table.

Trino Iceberg does not support ALTER TABLE ADD COLUMN.
This script drops and recreates both entities and prim_snapshots tables
with the updated schema.

WARNING: This destroys existing backup data. Run only in lab/dev environments.

Usage:
    python -m scripts.migrate_add_backup_source
    # or from api_service/:
    python scripts/migrate_add_backup_source.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.config import settings
from app.core.trino_config import trino_cursor, init_namespace


def check_column_exists(cursor, catalog, ns, table, column):
    """Check if a column exists in a Trino table."""
    cursor.execute(f"SHOW COLUMNS FROM {catalog}.{ns}.{table}")
    columns = [row[0] for row in cursor.fetchall()]
    return column in columns


def migrate():
    catalog = settings.trino_catalog
    ns = settings.iceberg_namespace
    init_namespace(ns)

    with trino_cursor(schema=ns) as cursor:
        # Check if entities table exists
        cursor.execute(f"SHOW TABLES FROM {catalog}.{ns} LIKE 'entities'")
        tables = [row[0] for row in cursor.fetchall()]

        if "entities" not in tables:
            print("entities table does not exist yet. No migration needed.")
            print("The table will be created with backup_source on next API startup.")
            return

        # Check if backup_source column already exists
        if check_column_exists(cursor, catalog, ns, "entities", "backup_source"):
            print("backup_source column already exists. No migration needed.")
            return

        # Column missing — need to drop and recreate
        print("=" * 60)
        print("WARNING: entities and prim_snapshots tables will be DROPPED")
        print("         and recreated with the backup_source column.")
        print("         Existing backup data will be LOST.")
        print("=" * 60)

        confirm = input("Continue? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Migration cancelled.")
            return

        # Drop tables
        print("Dropping entities table...")
        cursor.execute(f"DROP TABLE IF EXISTS {catalog}.{ns}.entities")
        cursor.fetchall()

        print("Dropping prim_snapshots table...")
        cursor.execute(f"DROP TABLE IF EXISTS {catalog}.{ns}.prim_snapshots")
        cursor.fetchall()

        print("Tables dropped. They will be recreated on next API startup.")
        print("Restart the lakehouse-api container: docker compose restart lakehouse-api")
        print("Migration complete.")


if __name__ == "__main__":
    migrate()
