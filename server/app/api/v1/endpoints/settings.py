from typing import List
from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.schemas.setting import SystemSettingResponse, SystemSettingUpdate
from app.repositories.setting_repository import SettingRepository
from app.repositories.audit_repository import record_audit
from app.core.exceptions import BadRequestException

router = APIRouter(prefix="/settings", tags=["Configuración del Sistema"])


def _is_secret_odoo_setting(key: str) -> bool:
    normalized = key.upper()
    return normalized.startswith("ODOO_") and any(secret in normalized for secret in ("API_KEY", "PASSWORD", "SECRET", "TOKEN"))


def _is_internal_setting(key: str) -> bool:
    return key.upper().startswith("YOLO_RUNTIME_")


@router.get("", response_model=List[SystemSettingResponse])
def get_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    repo = SettingRepository(db)
    return [
        setting for setting in repo.get_all()
        if not _is_secret_odoo_setting(setting.key) and not _is_internal_setting(setting.key)
    ]


@router.put("/{key}", response_model=SystemSettingResponse)
def update_setting(
    key: str = Path(...),
    payload: SystemSettingUpdate = ...,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    if _is_secret_odoo_setting(key):
        raise BadRequestException("Las credenciales Odoo se administran en /odoo/config")
    if _is_internal_setting(key):
        raise BadRequestException("La configuración YOLO se administra en /models/runtime")
    record_audit(db, current_user, "setting.updated", "system_setting", key)
    repo = SettingRepository(db)
    setting = repo.set_value(key=key, value=payload.value, description=payload.description)
    return setting
