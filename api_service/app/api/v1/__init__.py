"""v1 API — Lakehouse data management endpoints.

Routes:
    /api/v1/health            — Lightweight health check
    /api/v1/upload-usd        — USD file upload to S3
    /api/v1/query             — Ad-hoc Trino SQL execution
    /api/v1/entities/*        — Entity backup/restore/diff
    /api/v1/simulation/*      — Simulation sessions/deltas/keyframes
    /api/v1/raw-backup/*      — Raw file backup
    /api/v1/realtime/flush    — Delta batch flush
"""
