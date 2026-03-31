"""
USD file upload/download endpoints.

Upload: Receives USD files from Isaac Sim or nucleus_pipeline and stores in MinIO/S3.
Download: Retrieves USD files from MinIO/S3 by S3 key.
"""

import io
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.core.logging import logger
from app.models.schemas import UsdUploadResponse
from app.services import s3_service

router = APIRouter(tags=["USD Upload"])


@router.post("/upload-usd", response_model=UsdUploadResponse)
async def upload_usd(
    file: UploadFile = File(...),
    prim_path: str = Form(""),
    s3_key: str = Form(""),
):
    """
    Upload a USD file to S3 storage.

    Args:
        file: USD file to upload
        prim_path: (legacy) Prim path metadata
        s3_key: Custom S3 key for the file. If empty, uses default prefix + filename.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        content = await file.read()
        result = s3_service.upload_usd_file(
            file_content=content,
            filename=file.filename,
            prim_path=prim_path,
            s3_key=s3_key or None,
        )
        return UsdUploadResponse(**result)
    except Exception as e:
        logger.error("Failed to upload USD file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download-usd")
async def download_usd(s3_key: str = Query(..., description="S3 key of the file to download")):
    """Download a USD file from MinIO/S3 by S3 key."""
    try:
        content = s3_service.download_file(s3_key)
        filename = Path(s3_key).name
        return StreamingResponse(
            io.BytesIO(content),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.error("Failed to download file: %s", e, exc_info=True)
        raise HTTPException(status_code=404, detail=f"File not found: {s3_key}")
