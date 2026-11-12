from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class ProductionEventBase(BaseModel):
    camera_id: Optional[int] = None
    order_id: Optional[int] = None
    zone: Optional[str] = None
    stage: str = Field(..., description="DOBLADO, ARMADO_ESTRUCTURAL, VINILADO, ALMACEN, NO_IDENTIFICADO")
    event_type: str = Field("DETECCION_CONFIRMADA", description="DETECCION_CONFIRMADA, INICIO_ETAPA, FIN_ETAPA")
    association_status: str = Field("PENDIENTE", description="PENDIENTE, ASOCIADO, RECHAZADO")
    sync_status: str = Field("PENDIENTE", description="PENDIENTE, SINCRONIZADO, ERROR")
    confidence: float
    evidence_count: int = 1
    origin: str = "VISION_ARTIFICIAL"
    event_metadata: Optional[Dict[str, Any]] = None
    event_timestamp: Optional[datetime] = None


class ProductionEventCreate(ProductionEventBase):
    pass


class ProductionEventAssociate(BaseModel):
    order_id: int


class ProductionEventUpdate(BaseModel):
    stage: Optional[str] = Field(default=None, min_length=1, max_length=50)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence_count: Optional[int] = Field(default=None, ge=1)
    event_timestamp: Optional[datetime] = None


class ProductionEventResponse(ProductionEventBase):
    id: int
    event_timestamp: datetime
    created_at: datetime
    order_name: Optional[str] = None
    camera_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
