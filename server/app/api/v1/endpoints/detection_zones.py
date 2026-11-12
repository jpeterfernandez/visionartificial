"""
Endpoints para leer y editar la configuración de reglas de detección por zona.

GET  /detection-zones          → devuelve la config completa + clases disponibles del modelo
PUT  /detection-zones          → guarda la config (solo ADMIN)
POST /detection-zones/reset    → restaura los valores por defecto (solo ADMIN)
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_role
from app.db.session import get_db
from app.db.models.user import User
from app.repositories.setting_repository import SettingRepository
from app.schemas.zone_config import ClassificationRule, ZoneConfigPayload, ZoneConfigResponse, ZoneRule
from app.services.zone_config_service import ZoneConfigService, DEFAULT_ZONE_CONFIG, DEFAULT_CLASSIFICATION_RULES, SETTING_KEY
from app.services.yolo_service import yolo_service
from app.core.exceptions import BadRequestException

router = APIRouter(prefix="/detection-zones", tags=["Configuración de Zonas de Detección"])


def _available_classes() -> list[str]:
    """Devuelve la lista de nombres de clase del modelo YOLO cargado."""
    if yolo_service.is_loaded and yolo_service.classes:
        return sorted(yolo_service.classes.values())
    return []


def _updated_at(db: Session):
    setting = SettingRepository(db).get_by_key(SETTING_KEY)
    return setting.updated_at if setting else None


@router.get("", response_model=ZoneConfigResponse)
def get_detection_zones(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Devuelve la configuración activa de reglas por zona y las clases disponibles del modelo."""
    service = ZoneConfigService(db)
    config = service.get_config()
    return ZoneConfigResponse(
        zones={name: ZoneRule(**data) for name, data in config["zones"].items()},
        classification_rules=[ClassificationRule(**rule) for rule in config["classification_rules"]],
        available_classes=_available_classes(),
        updated_at=_updated_at(db),
    )


@router.put("", response_model=ZoneConfigResponse)
def update_detection_zones(
    payload: ZoneConfigPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """
    Actualiza las reglas de detección por zona.
    Valida que las clases referenciadas existan en el modelo YOLO.
    """
    available = set(_available_classes())
    # Normalizar: quitar prefijo chasis_ para la validación
    def _norm(name: str) -> str:
        n = name.strip().lower()
        return n[len("chasis_"):] if n.startswith("chasis_") else n

    available_norm = {_norm(c) for c in available}

    unknown: list[str] = []
    for zone_name, rule in payload.zones.items():
        for cls in rule.allowed + rule.blocked:
            if available_norm and _norm(cls) not in available_norm:
                unknown.append(f"{cls} (zona {zone_name})")

    classification_rules = payload.classification_rules
    if classification_rules is None:
        classification_rules = [
            ClassificationRule(**rule)
            for rule in ZoneConfigService(db).get_config()["classification_rules"]
        ]
    rule_ids = [rule.id for rule in classification_rules]
    if len(rule_ids) != len(set(rule_ids)):
        raise BadRequestException("Cada regla de clasificación debe tener un identificador único.")
    for rule in classification_rules:
        for cls in [rule.anchor_class, *rule.required_classes, *rule.one_of_classes]:
            if available_norm and _norm(cls) not in available_norm:
                unknown.append(f"{cls} (regla {rule.name})")

    if unknown:
        raise BadRequestException(
            f"Las siguientes clases no existen en el modelo: {', '.join(unknown)}. "
            f"Clases disponibles: {', '.join(sorted(available))}"
        )

    service = ZoneConfigService(db)
    saved = service.save_config({
        "zones": {k: v.model_dump() for k, v in payload.zones.items()},
        "classification_rules": [rule.model_dump() for rule in classification_rules],
    })

    return ZoneConfigResponse(
        zones={name: ZoneRule(**data) for name, data in saved["zones"].items()},
        classification_rules=[ClassificationRule(**rule) for rule in saved["classification_rules"]],
        available_classes=_available_classes(),
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/reset", response_model=ZoneConfigResponse)
def reset_detection_zones(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """Restaura la configuración de zonas a los valores por defecto."""
    service = ZoneConfigService(db)
    saved = service.save_config({
        **DEFAULT_ZONE_CONFIG,
        "classification_rules": DEFAULT_CLASSIFICATION_RULES,
    })
    return ZoneConfigResponse(
        zones={name: ZoneRule(**data) for name, data in saved["zones"].items()},
        classification_rules=[ClassificationRule(**rule) for rule in DEFAULT_CLASSIFICATION_RULES],
        available_classes=_available_classes(),
        updated_at=datetime.now(timezone.utc),
    )
