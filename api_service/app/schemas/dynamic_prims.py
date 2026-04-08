"""Pydantic schemas for DynamicPrim IoT streaming system (Task 4)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel


class DynamicTableRegisterRequest(BaseModel):
    """Register a new per-sensor dynamic table."""
    table_name: str          # e.g. "hum_temp_sensor1"
    description: str = ""   # optional description
    prim_path: str = ""      # e.g. "/World/Dynamic/hum-temp_sensor1"


class DynamicTableRegisterResponse(BaseModel):
    status: str = "ok"
    table_name: str = ""
    error: Optional[str] = None


class DynamicIngestRecord(BaseModel):
    """Single IoT data record."""
    capture_time: str           # ISO 8601
    temperature: float
    humidity: float
    device_id: str = ""
    quality_flag: str = "good"  # "good" | "suspect" | "bad"
    source_ip: str = ""
    unit_temp: str = "celsius"
    unit_humid: str = "percent"


class DynamicIngestRequest(BaseModel):
    """Batch ingest request."""
    table_name: str
    records: List[DynamicIngestRecord]


class DynamicIngestResponse(BaseModel):
    status: str = "ok"
    records_inserted: int = 0
    table_name: str = ""
    error: Optional[str] = None


class DynamicTableInfo(BaseModel):
    table_name: str
    prim_path: str = ""
    description: str = ""


class DynamicTablesListResponse(BaseModel):
    tables: List[DynamicTableInfo]


class DynamicQueryResponse(BaseModel):
    table_name: str
    columns: List[str] = []
    rows: List[dict] = []
    total: int = 0


class DynamicSeedDemoResponse(BaseModel):
    status: str = "ok"
    table_name: str = ""
    records_inserted: int = 0
    time_range: str = ""
    error: Optional[str] = None
