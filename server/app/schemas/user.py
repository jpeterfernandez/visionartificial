from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


ProductionZone = Literal["DOBLADO", "ARMADO_ESTRUCTURAL", "VINILADO", "ALMACEN"]


def _validate_bcrypt_password_size(password: Optional[str]) -> Optional[str]:
    if password is not None and len(password.encode("utf-8")) > 72:
        raise ValueError("La contraseña supera el límite de 72 bytes de bcrypt")
    return password


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    full_name: str = Field(..., min_length=2, max_length=100)
    role: Literal["ADMIN", "OPERATOR", "VIEWER"] = "OPERATOR"
    allowed_zones: list[ProductionZone] = Field(default_factory=list, max_length=4)
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(..., min_length=12, max_length=128)

    _password_size = field_validator("password")(_validate_bcrypt_password_size)


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    role: Optional[Literal["ADMIN", "OPERATOR", "VIEWER"]] = None
    allowed_zones: Optional[list[ProductionZone]] = Field(None, max_length=4)
    is_active: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=12, max_length=128)

    _password_size = field_validator("password")(_validate_bcrypt_password_size)


class UserResponse(UserBase):
    id: int
    allowed_zones: list[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenPayload(BaseModel):
    sub: str
    role: str
    exp: int
