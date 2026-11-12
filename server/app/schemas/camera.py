from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.core.camera_source import normalize_camera_source


ProductionZone = Literal["DOBLADO", "ARMADO_ESTRUCTURAL", "VINILADO", "ALMACEN"]


class CameraFields(BaseModel):
    name: str = Field(..., max_length=100)
    zone: ProductionZone
    source: str = Field(..., min_length=1, max_length=255)
    is_active: bool = True
    confidence_threshold: float = Field(0.60, ge=0.1, le=1.0)


class CameraBase(CameraFields):
    @field_validator("source")
    @classmethod
    def validate_source(cls, source: str) -> str:
        try:
            return normalize_camera_source(source)
        except ValueError as error:
            raise ValueError(str(error)) from error


class CameraCreate(CameraBase):
    pass


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    zone: Optional[ProductionZone] = None
    source: Optional[str] = None
    is_active: Optional[bool] = None
    confidence_threshold: Optional[float] = Field(None, ge=0.1, le=1.0)
    is_connected: Optional[bool] = None

    @field_validator("source")
    @classmethod
    def validate_source(cls, source: Optional[str]) -> Optional[str]:
        if source is None:
            return None
        try:
            return normalize_camera_source(source)
        except ValueError as error:
            raise ValueError(str(error)) from error


class CameraResponse(CameraFields):
    id: int
    zone: str
    is_connected: bool
    last_detection_at: Optional[datetime] = None
    last_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    # Campos enriquecidos desde el snapshot de captura periódica
    machine_count: Optional[int] = None
    last_snapshot_at: Optional[datetime] = None
    classification_counts: Optional[dict] = None
    vinyl_color_counts: Optional[dict] = None  # solo ALMACÉN: {"naranja": 2, ...}

    model_config = ConfigDict(from_attributes=True)
