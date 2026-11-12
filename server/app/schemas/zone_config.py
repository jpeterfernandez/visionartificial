from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ClassificationRule(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=100)
    stage: Literal["DOBLADO", "ARMADO_ESTRUCTURAL", "VINILADO", "ALMACEN"]
    anchor_class: str = Field(..., min_length=1, max_length=100)
    required_classes: List[str] = Field(default_factory=list)
    one_of_classes: List[str] = Field(default_factory=list)

    @field_validator("id", "name", "anchor_class", mode="before")
    @classmethod
    def trim_rule_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("required_classes", "one_of_classes", mode="before")
    @classmethod
    def ensure_class_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            value = value.split(",")
        if not isinstance(value, (list, tuple)):
            raise ValueError("Las clases deben enviarse como una lista.")
        return list(dict.fromkeys(
            class_name
            for item in value
            if (class_name := str(item).strip())
        ))


class ZoneRule(BaseModel):
    description: str = ""
    allowed: List[str] = Field(default_factory=list)
    blocked: List[str] = Field(default_factory=list)

    @field_validator("allowed", "blocked", mode="before")
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        return [str(c) for c in v]


class ZoneConfigPayload(BaseModel):
    zones: Dict[str, ZoneRule]
    classification_rules: Optional[List[ClassificationRule]] = None


class ZoneConfigResponse(BaseModel):
    zones: Dict[str, ZoneRule]
    classification_rules: List[ClassificationRule] = Field(default_factory=list)
    available_classes: List[str]
    updated_at: Optional[datetime] = None
