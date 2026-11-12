import json
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.db.models.user import User
from app.services.yolo_service import yolo_service
from app.schemas.detection import ModelStatusResponse, YoloRuntimeConfiguration
from app.api.dependencies import require_role
from app.repositories.setting_repository import SettingRepository

router = APIRouter(prefix="/models", tags=["Modelo YOLO"])


@router.get("/status", response_model=ModelStatusResponse)
def get_model_status():
    return yolo_service.get_status()


@router.get("/classes")
def get_model_classes():
    return {
        "classes": yolo_service.get_classes()
    }


@router.get("/metrics")
def get_yolo_runtime_metrics(
    current_user: User = Depends(require_role("ADMIN"))
):
    if settings.ENVIRONMENT.lower() != "development":
        return {"enabled": False, "environment": settings.ENVIRONMENT}

    return {
        "enabled": True,
        "environment": settings.ENVIRONMENT,
        **yolo_service.get_runtime_metrics(),
    }


def _runtime_configuration_response(configuration: YoloRuntimeConfiguration):
    return {
        "enabled": True,
        "environment": settings.ENVIRONMENT,
        "configuration": configuration.model_dump(),
        "active": yolo_service.get_runtime_configuration(),
        "hardware": yolo_service.get_hardware_info(),
    }


@router.get("/runtime")
def get_yolo_runtime_configuration(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    if settings.ENVIRONMENT.lower() != "development":
        return {"enabled": False, "environment": settings.ENVIRONMENT}

    saved = SettingRepository(db).get_by_key("YOLO_RUNTIME_CONFIGURATION")
    if saved:
        try:
            saved_configuration = json.loads(saved.value)
            saved_configuration.setdefault("img_size", yolo_service.img_size)
            saved_configuration.setdefault("stream_interval_ms", yolo_service.stream_interval_ms)
            configuration = YoloRuntimeConfiguration.model_validate(saved_configuration)
        except Exception:
            configuration = YoloRuntimeConfiguration(**yolo_service.get_runtime_configuration())
    else:
        configuration = YoloRuntimeConfiguration(**yolo_service.get_runtime_configuration())
    return _runtime_configuration_response(configuration)


@router.put("/runtime")
def update_yolo_runtime_configuration(
    configuration: YoloRuntimeConfiguration,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    if settings.ENVIRONMENT.lower() != "development":
        raise HTTPException(status_code=404, detail="Esta configuración solo está disponible en desarrollo.")

    try:
        yolo_service.configure_runtime(configuration.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    SettingRepository(db).set_value(
        key="YOLO_RUNTIME_CONFIGURATION",
        value=json.dumps(yolo_service.get_runtime_configuration() | {"device_mode": configuration.device_mode}),
        description="Perfil de procesamiento YOLO de uso exclusivo para desarrollo."
    )
    return _runtime_configuration_response(
        YoloRuntimeConfiguration(**yolo_service.get_runtime_configuration())
    )
