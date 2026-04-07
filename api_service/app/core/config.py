"""
Application settings loaded from environment variables.

All env vars are injected via docker-compose.yml -> lakehouse-api service.
See Lakehouse/Iceberg/example.env for reference values.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration – maps 1:1 to docker-compose env vars."""

    # ── App ──────────────────────────────────────────────────────────
    app_name: str = "Lakehouse API Middleware"
    debug: bool = False

    # ── Polaris / Iceberg REST Catalog ───────────────────────────────
    iceberg_catalog_uri: str = "http://polaris:8181/api/catalog"
    polaris_credential: str = "root:s3cr3t00"
    polaris_scope: str = "PRINCIPAL_ROLE:ALL"
    iceberg_warehouse: str = "iceberg2"
    iceberg_namespace: str = "netai"

    # ── S3 / MinIO ──────────────────────────────────────────────────
    s3_endpoint: str = "http://minio:9000"
    s3_bucket: str = "warehouse2"
    s3_usd_prefix: str = "usd/world_prims/"
    aws_access_key_id: str = "admin"
    aws_secret_access_key: str = "admin1234"
    aws_region: str = "us-east-1"

    # ── Trino ───────────────────────────────────────────────────────
    trino_host: str = "trino"
    trino_port: int = 8080
    trino_user: str = "trino"
    trino_catalog: str = "polaris"
    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
