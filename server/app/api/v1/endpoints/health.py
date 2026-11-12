from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db.session import get_db
from app.services.yolo_service import yolo_service
from app.schemas.dashboard import HealthResponse
from app.services.odoo_service import OdooService
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.services.request_metrics import request_metrics
from app.services.integration_health import get_odoo_status

router = APIRouter(prefix="/health", tags=["Salud y Diagnóstico"])


@router.get("/live")
def liveness_check():
    return {"status": "alive"}


@router.get("/ready")
def readiness_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as error:
        raise HTTPException(status_code=503, detail="Base de datos no disponible") from error
    if not yolo_service.is_loaded:
        raise HTTPException(status_code=503, detail="Modelo YOLO no cargado")
    return {"status": "ready", "database": "healthy", "yolo_model": "loaded"}


@router.get("/metrics")
def get_request_metrics(
    _user: User = Depends(require_role("ADMIN")),
):
    return request_metrics.snapshot()


@router.get("", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    # Check DB
    db_status = "healthy"
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    # Check YOLO
    yolo_status = "loaded" if yolo_service.is_loaded else "not_loaded"

    # Check Odoo
    odoo_status_cache = get_odoo_status()
    odoo_config = OdooService(db).get_config()
    odoo_status = "disabled" if not odoo_config["enabled"] else (
        "connected" if odoo_status_cache["connected"] else "unavailable"
    )

    return {
        "status": "online" if db_status == "healthy" else "degraded",
        "version": "1.0.0",
        "database": db_status,
        "yolo_model": yolo_status,
        "odoo": odoo_status
    }
