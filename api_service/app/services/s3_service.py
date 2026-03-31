"""
S3 / MinIO object storage operations.

Handles USD file uploads and general object management.
"""

from __future__ import annotations

import io

import boto3
from botocore.client import Config

from app.core.config import settings
from app.core.logging import logger

_client = None


def get_s3_client():
    """Lazy-load and return the boto3 S3 client configured for MinIO."""
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
        # Ensure bucket exists
        _ensure_bucket(settings.s3_bucket)
        logger.info("S3 client initialized: %s", settings.s3_endpoint)
    return _client


def _ensure_bucket(bucket: str) -> None:
    """Create the S3 bucket if it doesn't exist."""
    client = _client or get_s3_client()
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        try:
            client.create_bucket(Bucket=bucket)
            logger.info("Created S3 bucket: %s", bucket)
        except Exception as e:
            logger.warning("Bucket creation skipped (may already exist): %s", e)


def upload_usd_file(
    file_content: bytes,
    filename: str,
    prim_path: str = "",
    s3_key: str | None = None,
) -> dict:
    """Upload a USD file to S3 and return metadata.

    Args:
        s3_key: Custom S3 key. If None, uses default prefix + filename.
    """
    client = get_s3_client()
    s3_key = s3_key or f"{settings.s3_usd_prefix}{filename}"

    client.upload_fileobj(
        io.BytesIO(file_content),
        settings.s3_bucket,
        s3_key,
        ExtraArgs={"ContentType": "application/octet-stream"},
    )

    logger.info("Uploaded USD file: s3://%s/%s", settings.s3_bucket, s3_key)
    return {
        "filename": filename,
        "s3_key": s3_key,
        "bucket": settings.s3_bucket,
    }


def download_file(s3_key: str) -> bytes:
    """Download a file from S3 by key."""
    client = get_s3_client()
    obj = client.get_object(Bucket=settings.s3_bucket, Key=s3_key)
    return obj["Body"].read()
