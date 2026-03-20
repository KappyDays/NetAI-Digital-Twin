"""
Polaris + Trino + Iceberg Lakehouse Integration Test

This script verifies the full Iceberg Lakehouse stack:
  1. MinIO  - S3-compatible object storage  (localhost:9000)
  2. Polaris - Iceberg REST catalog         (localhost:8181)
  3. Trino  - Distributed SQL query engine  (localhost:8443)

Workflow:
  Step 0: Create 'warehouse' bucket in MinIO (via S3 API)
  Step 1: Obtain OAuth2 token from Polaris
  Step 2: Create an Iceberg catalog in Polaris (via Management API)
  Step 3: Connect to Trino and run Iceberg SQL operations

Requirements:
  pip install trino boto3 requests
"""

import sys
import time
import requests
import boto3
from botocore.client import Config as BotoConfig
from trino.dbapi import connect as trino_connect
from trino.auth import OAuth2Authentication

# =============================================================================
# Configuration (match your .env file)
# =============================================================================
MINIO_ENDPOINT = "http://localhost:9000"
MINIO_ACCESS_KEY = "asd"
MINIO_SECRET_KEY = "asdasdasd"
MINIO_BUCKET = "warehouse2"

POLARIS_ENDPOINT = "http://localhost:8181"
POLARIS_CLIENT_ID = "root"
POLARIS_CLIENT_SECRET = "s3cr3t00"
POLARIS_CATALOG_NAME = "iceberg2"

TRINO_HOST = "localhost"
TRINO_PORT = 8443


# =============================================================================
# Step 0: Create MinIO bucket
# =============================================================================
def setup_minio_bucket():
    print("=" * 60)
    print("Step 0: Setting up MinIO bucket")
    print("=" * 60)

    s3 = boto3.client(
        "s3",
        endpoint_url=MINIO_ENDPOINT,
        aws_access_key_id=MINIO_ACCESS_KEY,
        aws_secret_access_key=MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=BotoConfig(signature_version="s3v4"),
    )

    existing = [b["Name"] for b in s3.list_buckets().get("Buckets", [])]
    if MINIO_BUCKET in existing:
        print(f"  -> Bucket '{MINIO_BUCKET}' already exists. Skipping.")
    else:
        s3.create_bucket(Bucket=MINIO_BUCKET)
        print(f"  -> Bucket '{MINIO_BUCKET}' created.")

    print()


# =============================================================================
# Step 1: Get Polaris OAuth2 token
# =============================================================================
def get_polaris_token():
    print("=" * 60)
    print("Step 1: Obtaining Polaris OAuth2 token")
    print("=" * 60)

    resp = requests.post(
        f"{POLARIS_ENDPOINT}/api/catalog/v1/oauth/tokens",
        data={
            "grant_type": "client_credentials",
            "client_id": POLARIS_CLIENT_ID,
            "client_secret": POLARIS_CLIENT_SECRET,
            "scope": "PRINCIPAL_ROLE:ALL",
        },
    )

    if resp.status_code != 200:
        print(f"  [ERROR] Failed to get token: {resp.status_code}")
        print(f"  Response: {resp.text}")
        sys.exit(1)

    token = resp.json()["access_token"]
    print(f"  -> Token obtained (first 20 chars): {token[:20]}...")
    print()
    return token


# =============================================================================
# Step 2: Create Polaris catalog
# =============================================================================
def setup_polaris_catalog(token):
    print("=" * 60)
    print("Step 2: Creating Polaris catalog")
    print("=" * 60)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Check if catalog already exists
    resp = requests.get(
        f"{POLARIS_ENDPOINT}/api/management/v1/catalogs/{POLARIS_CATALOG_NAME}",
        headers=headers,
    )

    if resp.status_code == 200:
        print(f"  -> Catalog '{POLARIS_CATALOG_NAME}' exists. Deleting and recreating.")
        del_resp = requests.delete(
            f"{POLARIS_ENDPOINT}/api/management/v1/catalogs/{POLARIS_CATALOG_NAME}",
            headers=headers,
        )
        if del_resp.status_code not in (200, 204):
            print(f"  [ERROR] Failed to delete catalog: {del_resp.status_code} {del_resp.text}")
            sys.exit(1)
    elif resp.status_code != 404:
        print(f"  [ERROR] Failed to check catalog: {resp.status_code}")
        print(f"  Response: {resp.text}")
        sys.exit(1)

    # Create catalog
    catalog_base = f"s3://{MINIO_BUCKET}/{POLARIS_CATALOG_NAME}/"

    catalog_payload = {
        "catalog": {
            "name": POLARIS_CATALOG_NAME,
            "type": "INTERNAL",
            "storageConfigInfo": {
                "storageType": "S3",
                "allowedLocations": [catalog_base],
                "endpoint": "http://minio:9000",
                "endpointInternal": "http://minio:9000",
                "region": "us-east-1",
                "pathStyleAccess": True,
                "stsUnavailable": True,
            },
            "properties": {
                "default-base-location": catalog_base,
            },
        }
    }

    resp = requests.post(
        f"{POLARIS_ENDPOINT}/api/management/v1/catalogs",
        headers=headers,
        json=catalog_payload,
    )

    if resp.status_code in (200, 201):
        print(f"  -> Catalog '{POLARIS_CATALOG_NAME}' created successfully.")
    else:
        print(f"  [ERROR] Failed to create catalog: {resp.status_code}")
        print(f"  Response: {resp.text}")
        sys.exit(1)

    # 여기 추가
    check = requests.get(
        f"{POLARIS_ENDPOINT}/api/management/v1/catalogs/{POLARIS_CATALOG_NAME}",
        headers=headers,
    )
    print("  -> Stored catalog config:")
    print(check.text)

    # --- Grant catalog access to the root principal role ---
    print("  -> Configuring catalog role permissions...")

    print("  -> Configuring catalog role permissions...")

    catalog_role = "catalog_admin"
    principal_role = "service_admin"
    resp = requests.put(
        f"{POLARIS_ENDPOINT}/api/management/v1/principal-roles/{principal_role}/catalog-roles/{POLARIS_CATALOG_NAME}",
        headers=headers,
        json={"name": catalog_role},
    )
    if resp.status_code in (200, 201):
        print(f"  -> Assigned '{catalog_role}' to principal role '{principal_role}'.")
    else:
        print(f"  [WARN] catalog_role assign: {resp.status_code} {resp.text}")

    print()

# =============================================================================
# Step 3: Trino SQL operations on Iceberg tables
# =============================================================================
def run_trino_queries():
    print("=" * 60)
    print("Step 3: Running Trino queries on Iceberg tables")
    print("=" * 60)

    # Wait for Trino to be ready
    print("  Waiting for Trino to be ready...", end="", flush=True)
    for attempt in range(30):
        try:
            test_conn = trino_connect(
                host=TRINO_HOST,
                port=TRINO_PORT,
                user="test",
                http_scheme="http",
            )
            test_cursor = test_conn.cursor()
            test_cursor.execute("SELECT 1")
            test_cursor.fetchall()
            test_cursor.close()
            test_conn.close()
            print(" Ready!")
            break
        except Exception:
            print(".", end="", flush=True)
            time.sleep(2)
    else:
        print("\n  [ERROR] Trino did not become ready in 60 seconds.")
        sys.exit(1)

    conn = trino_connect(
        host=TRINO_HOST,
        port=TRINO_PORT,
        user="test",
        catalog="iceberg",
        schema="db",
        http_scheme="http",
    )
    cursor = conn.cursor()

    def execute_and_print(description, sql, fetch=True):
        print(f"\n  >> {description}")
        print(f"     SQL: {sql}")
        cursor.execute(sql)
        if fetch:
            rows = cursor.fetchall()
            if rows:
                # Print column headers
                col_names = [desc[0] for desc in cursor.description]
                header = " | ".join(f"{c:>15}" for c in col_names)
                print(f"     {header}")
                print(f"     {'-' * len(header)}")
                for row in rows:
                    line = " | ".join(f"{str(v):>15}" for v in row)
                    print(f"     {line}")
            else:
                print("     (empty result)")
        else:
            print("     OK")

    # --- Create namespace ---
    execute_and_print(
        "Create schema 'db'",
        "CREATE SCHEMA IF NOT EXISTS iceberg.db",
        fetch=False,
    )

    # --- Create table ---
    execute_and_print(
        "Create table 'demo'",
        """CREATE TABLE IF NOT EXISTS iceberg.db.demo (
            id BIGINT,
            data VARCHAR,
            created_at TIMESTAMP(6) WITH TIME ZONE
        ) WITH (format = 'PARQUET')""",
        fetch=False,
    )

    # --- Insert data ---
    execute_and_print(
        "Insert sample data",
        """INSERT INTO iceberg.db.demo VALUES
            (1, 'alpha',   TIMESTAMP '2025-01-01 00:00:00.000000 UTC'),
            (2, 'bravo',   TIMESTAMP '2025-01-02 00:00:00.000000 UTC'),
            (3, 'charlie', TIMESTAMP '2025-01-03 00:00:00.000000 UTC'),
            (4, 'delta',   TIMESTAMP '2025-01-04 00:00:00.000000 UTC')""",
        fetch=False,
    )

    # --- Query data ---
    execute_and_print(
        "Select all rows",
        "SELECT * FROM iceberg.db.demo ORDER BY id",
    )

    # --- Iceberg metadata: snapshots ---
    execute_and_print(
        "Iceberg snapshots (version history)",
        """SELECT snapshot_id, parent_id, operation, summary
           FROM iceberg.db.\"demo$snapshots\"
           ORDER BY committed_at""",
    )

    # --- Iceberg metadata: files ---
    execute_and_print(
        "Iceberg data files",
        """SELECT file_path, file_format, record_count, file_size_in_bytes
           FROM iceberg.db.\"demo$files\"""",
    )

    # --- Schema evolution: add column ---
    execute_and_print(
        "Schema evolution: add 'category' column",
        "ALTER TABLE iceberg.db.demo ADD COLUMN IF NOT EXISTS category VARCHAR",
        fetch=False,
    )

    execute_and_print(
        "Insert data with new column",
        """INSERT INTO iceberg.db.demo VALUES
            (5, 'echo', TIMESTAMP '2025-01-05 00:00:00.000000 UTC', 'test')""",
        fetch=False,
    )

    execute_and_print(
        "Select all rows after schema evolution",
        "SELECT * FROM iceberg.db.demo ORDER BY id",
    )

    # --- Time travel: query previous snapshot ---
    cursor.execute(
        """SELECT snapshot_id FROM iceberg.db."demo$snapshots"
           ORDER BY committed_at LIMIT 1"""
    )
    first_snapshot = cursor.fetchone()
    if first_snapshot:
        snapshot_id = first_snapshot[0]
        execute_and_print(
            f"Time travel: query snapshot {snapshot_id}",
            f"""SELECT * FROM iceberg.db.demo
                FOR VERSION AS OF {snapshot_id}
                ORDER BY id""",
        )

    # --- Cleanup ---
    try:
        execute_and_print(
            "Cleanup: drop table",
            "DROP TABLE IF EXISTS iceberg.db.demo",
            fetch=False,
        )
    except Exception as e:
        print(f"  [WARN] Cleanup: drop table failed: {e}")

    try:
        execute_and_print(
            "Cleanup: drop schema",
            "DROP SCHEMA IF EXISTS iceberg.db",
            fetch=False,
        )
    except Exception as e:
        print(f"  [WARN] Cleanup: drop schema failed: {e}")

    cursor.close()
    conn.close()
    print("\n" + "=" * 60)
    print("Core tests passed! (cleanup may require manual handling)")
    print("=" * 60)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    setup_minio_bucket()
    token = get_polaris_token()
    setup_polaris_catalog(token)
    run_trino_queries()
