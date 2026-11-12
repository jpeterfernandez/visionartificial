from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict


class ProductionOrderBase(BaseModel):
    name: str = Field(..., max_length=100)
    product_name: str = Field(..., max_length=200)
    target_qty: int = Field(1, ge=1)
    state: str = Field("draft")
    current_stage: Optional[str] = None
    zone: Optional[str] = None
    notes: Optional[str] = None


class ProductionOrderCreate(ProductionOrderBase):
    zone: str = Field(..., min_length=1, max_length=50)
    odoo_order_id: Optional[int] = None


class ProductionOrderUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    product_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    target_qty: Optional[int] = Field(default=None, ge=1)
    state: Optional[str] = None
    current_stage: Optional[str] = None
    zone: Optional[str] = Field(default=None, max_length=50)
    produced_qty: Optional[int] = Field(default=None, ge=0)
    notes: Optional[str] = None


class ProductionOrderResponse(ProductionOrderBase):
    id: int
    odoo_order_id: Optional[int] = None
    produced_qty: int
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
