"""Lakehouse API Middleware for Omniverse Isaac Sim Digital Twin.

Bridges NVIDIA Isaac Sim extensions to the Apache Iceberg Lakehouse
(Polaris REST Catalog + MinIO S3 + Trino SQL) for OpenUSD data management.

Modules:
    core     — Configuration and logging
    models   — Pydantic request/response schemas
    services — Iceberg, S3, and Trino service layers
    api      — FastAPI route handlers (v1)
"""

__version__ = "1.0.0"
