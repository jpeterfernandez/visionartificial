from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class OdooConfigResponse(BaseModel):
    enabled: bool
    base_url: str
    database: str
    username: str
    api_key_configured: bool
    timeout: int


class OdooConfigUpdate(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    database: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    timeout: int = Field(ge=1, le=120)
    api_key: str | None = None
    clear_api_key: bool = False


class OdooConnectionTestResponse(BaseModel):
    enabled: bool
    configured: bool
    connected: bool
    base_url: str
    database: str
    username: str
    server_version: Optional[str] = None
    authenticated: bool
    error: Optional[str] = None


class OdooProductionOrderDTO(BaseModel):
    id: int
    name: str
    product_id: List[int | str]
    product_qty: float
    state: str
    date_planned_start: Optional[str] = None
    date_planned_finished: Optional[str] = None


class OdooSyncResult(BaseModel):
    synced_orders_count: int
    new_orders: int
    updated_orders: int
    errors: List[str] = []
