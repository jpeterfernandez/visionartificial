from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.schemas.odoo import OdooConfigResponse, OdooConfigUpdate, OdooConnectionTestResponse, OdooSyncResult
from app.services.odoo_service import OdooService
from app.repositories.audit_repository import record_audit

router = APIRouter(prefix="/odoo", tags=["Integración Odoo ERP"])


@router.get("/config", response_model=OdooConfigResponse)
def get_odoo_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    return OdooService(db).get_config()


@router.put("/config", response_model=OdooConfigResponse)
def update_odoo_config(
    payload: OdooConfigUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    public_fields = payload.model_dump(exclude={"api_key"})
    record_audit(
        db,
        current_user,
        "odoo.config_updated",
        "odoo_config",
        "integration",
        {"changed_fields": [key for key, value in public_fields.items() if value is not None]},
    )
    return OdooService(db).update_config(payload.model_dump())


@router.get("/status", response_model=OdooConnectionTestResponse)
def test_odoo_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = OdooService(db)
    return service.test_connection()


@router.post("/sync-orders", response_model=OdooSyncResult)
def sync_odoo_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    service = OdooService(db)
    return service.sync_orders_from_odoo()


@router.post("/sync-events")
def sync_odoo_events(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    service = OdooService(db)
    return service.sync_pending_events_to_odoo()
