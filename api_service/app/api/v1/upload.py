"""
USD file upload endpoint.

Receives USD files from Isaac Sim and stores them in MinIO/S3.
"""

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.logging import logger
from app.models.schemas import UsdUploadResponse
from app.services import s3_service

router = APIRouter(tags=["USD Upload"])


@router.post("/upload-usd", response_model=UsdUploadResponse)
async def upload_usd(
    file: UploadFile = File(...),
    prim_path: str = Form(""),
):
    """
    Upload a USD file to S3 storage.

    Called by the Isaac Sim lakehouse.proto extension (Task 2).
    Each /World direct child Prim is exported as a separate USD file.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        content = await file.read()
        result = s3_service.upload_usd_file(
            file_content=content,
            filename=file.filename,
            prim_path=prim_path,
        )
        return UsdUploadResponse(**result)
    except Exception as e:
        logger.error("Failed to upload USD file: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
