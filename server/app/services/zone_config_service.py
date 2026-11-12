"""
Servicio de configuración de reglas de detección por zona.

Las reglas se persisten en la tabla system_settings con la clave
ZONE_DETECTION_CONFIG como un JSON.  Si la clave no existe se usan
los defaults (mismas reglas que prueba_v3.py).
"""

import copy
import json
from typing import Any, Dict

from app.repositories.setting_repository import SettingRepository

SETTING_KEY = "ZONE_DETECTION_CONFIG"

# Defaults alineados con las reglas de prueba_v3.py
DEFAULT_ZONE_CONFIG: Dict[str, Any] = {
    "zones": {
        "DOBLADO": {
            "description": "Chasis base y cavidad hueca; etapa de conformado.",
            "allowed": ["chasis_base", "cavidad_hueca"],
            "blocked": [],
        },
        "ARMADO_ESTRUCTURAL": {
            "description": "Puertas y paneles estructurales.",
            "allowed": [
                "chasis_base",
                "puerta_inferior",
                "puerta_sup_chapa",
                "puerta_sup_panel",
            ],
            "blocked": [],
        },
        "VINILADO": {
            "description": "Solo piezas viniladas.",
            "allowed": ["chasis_vinilado"],
            "blocked": [],
        },
        "ALMACEN": {
            "description": "Piezas terminadas en stock listas para salida.",
            "allowed": ["chasis_vinilado"],
            "blocked": [],
        },
    }
}

DEFAULT_CLASSIFICATION_RULES = [
    {
        "id": "chasis-estructurado",
        "name": "Chasis estructurado",
        "stage": "ARMADO_ESTRUCTURAL",
        "anchor_class": "chasis_base",
        "required_classes": [],
        "one_of_classes": ["puerta_inferior", "puerta_sup_chapa", "puerta_sup_panel"],
    },
    {
        "id": "chasis-doblado",
        "name": "Chasis doblado",
        "stage": "DOBLADO",
        "anchor_class": "chasis_base",
        "required_classes": ["cavidad_hueca"],
        "one_of_classes": [],
    },
    {
        "id": "chasis-vinilado",
        "name": "Chasis vinilado",
        "stage": "VINILADO",
        "anchor_class": "chasis_vinilado",
        "required_classes": [],
        "one_of_classes": [],
    },
]


def _norm(name: str) -> str:
    """Normaliza un nombre de clase quitando el prefijo 'chasis_'."""
    n = str(name).strip().lower()
    return n[len("chasis_"):] if n.startswith("chasis_") else n


class ZoneConfigService:
    def __init__(self, db):
        self.db = db
        self.repo = SettingRepository(db)

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    def get_config(self) -> Dict[str, Any]:
        """
        Devuelve la config activa.  Las zonas guardadas en DB sobreescriben
        los defaults; las zonas que solo están en los defaults se añaden.
        """
        setting = self.repo.get_by_key(SETTING_KEY)
        config = copy.deepcopy(DEFAULT_ZONE_CONFIG)
        config["classification_rules"] = copy.deepcopy(DEFAULT_CLASSIFICATION_RULES)

        if setting:
            try:
                saved = json.loads(setting.value)
                for zname, zdata in (saved.get("zones") or {}).items():
                    if isinstance(zdata, dict):
                        config["zones"][zname] = {
                            "description": zdata.get("description", ""),
                            "allowed": list(zdata.get("allowed") or []),
                            "blocked": list(zdata.get("blocked") or []),
                        }
                if isinstance(saved.get("classification_rules"), list):
                    config["classification_rules"] = saved["classification_rules"]
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass  # mantiene defaults ante JSON corrupto

        return config

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------

    def save_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Valida y persiste la config en system_settings."""
        # Asegurar estructura mínima
        if "zones" not in config or not isinstance(config["zones"], dict):
            raise ValueError("La configuración debe contener un dict 'zones'.")

        clean: Dict[str, Any] = {"zones": {}}
        for zname, zdata in config["zones"].items():
            if not isinstance(zdata, dict):
                continue
            clean["zones"][str(zname)] = {
                "description": str(zdata.get("description", "")),
                "allowed": [str(c) for c in (zdata.get("allowed") or [])],
                "blocked": [str(c) for c in (zdata.get("blocked") or [])],
            }

        if "classification_rules" in config:
            clean["classification_rules"] = [
                {
                    "id": str(rule["id"]),
                    "name": str(rule["name"]),
                    "stage": str(rule["stage"]),
                    "anchor_class": str(rule["anchor_class"]),
                    "required_classes": [str(c) for c in rule.get("required_classes", [])],
                    "one_of_classes": [str(c) for c in rule.get("one_of_classes", [])],
                }
                for rule in config["classification_rules"]
            ]

        self.repo.set_value(
            SETTING_KEY,
            json.dumps(clean, ensure_ascii=False),
            "Reglas de detección por zona (clases permitidas y bloqueadas).",
        )
        return clean

    # ------------------------------------------------------------------
    # Lógica de filtro (usada por camera_capture y detection_service)
    # ------------------------------------------------------------------

    @staticmethod
    def is_class_allowed(class_name: str, zone: str, config: Dict[str, Any]) -> bool:
        """
        Devuelve True si class_name está permitida en la zona según config.
        Si la zona no tiene config propia, permite todo.
        """
        zone_cfg = (config.get("zones") or {}).get(zone)
        if not zone_cfg:
            return True

        name = _norm(class_name)
        blocked = [_norm(c) for c in (zone_cfg.get("blocked") or [])]
        allowed = [_norm(c) for c in (zone_cfg.get("allowed") or [])]

        if name in blocked:
            return False
        if allowed and name not in allowed:
            return False
        return True
