"""
Table Maintenance Job — Iceberg Compaction & Cleanup
=====================================================
PySpark job for maintaining Iceberg tables: expire old snapshots,
rewrite data files (compaction), and remove orphan files.

Usage:
    spark-submit /opt/spark-jobs/table_maintenance.py \
        --namespace static_db \
        --table static_prims \
        --action compact

    spark-submit /opt/spark-jobs/table_maintenance.py \
        --namespace dynamic_db \
        --table robot_01 \
        --action expire_snapshots \
        --retain-days 7
"""
import argparse
from datetime import datetime, timedelta

from pyspark.sql import SparkSession


def get_spark() -> SparkSession:
    return (
        SparkSession.builder
        .appName("NetAI-DT-TableMaintenance")
        .getOrCreate()
    )


def compact_data_files(spark: SparkSession, fqn: str):
    """Rewrite small data files into larger ones for better read performance."""
    spark.sql(f"CALL iceberg.system.rewrite_data_files(table => '{fqn}')")
    print(f"[OK] Compacted data files for {fqn}")


def expire_snapshots(spark: SparkSession, fqn: str, retain_days: int = 7):
    """Remove snapshots older than the retention period."""
    cutoff = (datetime.now() - timedelta(days=retain_days)).strftime("%Y-%m-%d %H:%M:%S")
    spark.sql(
        f"CALL iceberg.system.expire_snapshots("
        f"table => '{fqn}', older_than => TIMESTAMP '{cutoff}')"
    )
    print(f"[OK] Expired snapshots older than {cutoff} for {fqn}")


def remove_orphan_files(spark: SparkSession, fqn: str):
    """Remove data files not referenced by any snapshot."""
    spark.sql(f"CALL iceberg.system.remove_orphan_files(table => '{fqn}')")
    print(f"[OK] Removed orphan files for {fqn}")


def show_snapshots(spark: SparkSession, fqn: str):
    """Display snapshot history for an Iceberg table."""
    spark.sql(f"SELECT * FROM {fqn}.snapshots ORDER BY committed_at DESC").show(
        n=20, truncate=False
    )


def main():
    parser = argparse.ArgumentParser(description="Iceberg Table Maintenance")
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--table", required=True)
    parser.add_argument("--action", required=True,
                        choices=["compact", "expire_snapshots",
                                 "remove_orphans", "show_snapshots"])
    parser.add_argument("--retain-days", type=int, default=7,
                        help="Days to retain snapshots (default: 7)")
    args = parser.parse_args()

    spark = get_spark()
    fqn = f"iceberg.{args.namespace}.{args.table}"

    actions = {
        "compact": lambda: compact_data_files(spark, fqn),
        "expire_snapshots": lambda: expire_snapshots(spark, fqn, args.retain_days),
        "remove_orphans": lambda: remove_orphan_files(spark, fqn),
        "show_snapshots": lambda: show_snapshots(spark, fqn),
    }

    actions[args.action]()
    spark.stop()


if __name__ == "__main__":
    main()
