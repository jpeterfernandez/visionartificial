from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class SystemSettingResponse(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemSettingUpdate(BaseModel):
    value: str
    description: Optional[str] = None
