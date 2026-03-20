"""
Schema Evolution Job — Iceberg Table Maintenance
=================================================
PySpark job for managing schema evolution on Dynamic object Iceberg tables.
Supports adding columns, renaming fields, and type promotion while preserving
backward compatibility.

Usage:
    spark-submit /opt/spark-jobs/schema_evolution.py \
        --namespace dynamic_db \
        --table <table_name> \
        --action add_column \
        --column "new_field" \
        --type "string"
"""
import argparse
import sys

from pyspark.sql import SparkSession


def get_spark() -> SparkSession:
    """Create a SparkSession with Iceberg catalog pre-configured."""
    return (
        SparkSession.builder
        .appName("NetAI-DT-SchemaEvolution")
        .getOrCreate()
    )


def add_column(spark: SparkSession, fqn: str, col_name: str, col_type: str):
    """Add a new column to an existing Iceberg table."""
    spark.sql(f"ALTER TABLE {fqn} ADD COLUMNS ({col_name} {col_type})")
    print(f"[OK] Added column '{col_name}' ({col_type}) to {fqn}")


def rename_column(spark: SparkSession, fqn: str, old_name: str, new_name: str):
    """Rename a column in an Iceberg table."""
    spark.sql(f"ALTER TABLE {fqn} RENAME COLUMN {old_name} TO {new_name}")
    print(f"[OK] Renamed column '{old_name}' -> '{new_name}' in {fqn}")


def show_schema(spark: SparkSession, fqn: str):
    """Display the current schema of an Iceberg table."""
    spark.sql(f"DESCRIBE {fqn}").show(truncate=False)


def main():
    parser = argparse.ArgumentParser(description="Iceberg Schema Evolution")
    parser.add_argument("--namespace", required=True, help="Iceberg namespace (e.g. dynamic_db)")
    parser.add_argument("--table", required=True, help="Table name")
    parser.add_argument("--action", required=True,
                        choices=["add_column", "rename_column", "show_schema"],
                        help="Schema evolution action")
    parser.add_argument("--column", help="Column name (for add_column)")
    parser.add_argument("--type", help="Column type (for add_column)")
    parser.add_argument("--old-name", help="Old column name (for rename_column)")
    parser.add_argument("--new-name", help="New column name (for rename_column)")
    args = parser.parse_args()

    spark = get_spark()
    fqn = f"iceberg.{args.namespace}.{args.table}"

    if args.action == "add_column":
        if not args.column or not args.type:
            print("ERROR: --column and --type required for add_column")
            sys.exit(1)
        add_column(spark, fqn, args.column, args.type)
    elif args.action == "rename_column":
        if not args.old_name or not args.new_name:
            print("ERROR: --old-name and --new-name required for rename_column")
            sys.exit(1)
        rename_column(spark, fqn, args.old_name, args.new_name)
    elif args.action == "show_schema":
        show_schema(spark, fqn)

    spark.stop()


if __name__ == "__main__":
    main()
