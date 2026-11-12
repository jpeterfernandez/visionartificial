from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from app.integrations.odoo_client import OdooClient
from app.repositories.production_repository import ProductionRepository
from app.repositories.event_repository import EventRepository
from app.repositories.setting_repository import SettingRepository
from app.db.models.production_order import ProductionOrder
from app.core.config import settings
from app.core.logging import logger
from app.core.secrets import decrypt_secret, encrypt_secret


ODOO_ENABLED_KEY = "ODOO_INTEGRATION_ENABLED"
ODOO_CONFIG_KEYS = {
    "base_url": ("ODOO_BASE_URL", "URL del servidor Odoo"),
    "database": ("ODOO_DATABASE", "Base de datos Odoo"),
    "username": ("ODOO_USERNAME", "Usuario Odoo"),
    "timeout": ("ODOO_TIMEOUT", "Tiempo de espera Odoo (segundos)"),
}
ODOO_API_KEY = "ODOO_API_KEY"


class OdooService:
    def __init__(self, db: Session):
        self.db = db
        self.settings_repo = SettingRepository(db)
        self.client = self._create_client()
        self.production_repo = ProductionRepository(db)
        self.event_repo = EventRepository(db)

    def _setting_value(self, key: str, default: str) -> str:
        setting = self.settings_repo.get_by_key(key)
        return setting.value if setting else default

    def is_enabled(self) -> bool:
        value = self._setting_value(ODOO_ENABLED_KEY, "false").strip().lower()
        return value in {"true", "1", "si", "sí", "enabled"}

    def _create_client(self) -> OdooClient:
        timeout_value = self._setting_value("ODOO_TIMEOUT", str(settings.ODOO_TIMEOUT))
        try:
            timeout = max(1, int(timeout_value))
        except ValueError:
            timeout = settings.ODOO_TIMEOUT

        api_key_setting = self.settings_repo.get_by_key(ODOO_API_KEY)
        api_key = decrypt_secret(api_key_setting.value) if api_key_setting else settings.ODOO_API_KEY
        if api_key_setting and api_key and not api_key_setting.value.startswith("fernet:"):
            api_key_setting.value = encrypt_secret(api_key)
            self.db.commit()
        return OdooClient(
            base_url=self._setting_value("ODOO_BASE_URL", settings.ODOO_BASE_URL),
            database=self._setting_value("ODOO_DATABASE", settings.ODOO_DATABASE),
            username=self._setting_value("ODOO_USERNAME", settings.ODOO_USERNAME),
            api_key=api_key,
            timeout=timeout,
        )

    def get_config(self) -> Dict[str, Any]:
        return {
            "enabled": self.is_enabled(),
            "base_url": self.client.base_url,
            "database": self.client.database,
            "username": self.client.username,
            "api_key_configured": bool(self.client.api_key),
            "timeout": self.client.timeout,
        }

    def update_config(self, values: Dict[str, Any]) -> Dict[str, Any]:
        for field, (key, description) in ODOO_CONFIG_KEYS.items():
            value = values.get(field)
            if value is not None:
                self.settings_repo.set_value(key, str(value), description)

        if values.get("clear_api_key"):
            self.settings_repo.set_value(ODOO_API_KEY, "", "Clave API de Odoo")
        elif values.get("api_key"):
            self.settings_repo.set_value(
                ODOO_API_KEY,
                encrypt_secret(values["api_key"]),
                "Clave API de Odoo",
            )

        self.client = self._create_client()
        return self.get_config()

    def test_connection(self) -> Dict[str, Any]:
        """Performs live connectivity and credentials check with Odoo."""
        if not self.is_enabled():
            return {
                "enabled": False,
                "configured": self.client.is_configured(),
                "connected": False,
                "base_url": self.client.base_url,
                "database": self.client.database,
                "username": self.client.username,
                "server_version": None,
                "authenticated": False,
                "error": "Integración desactivada. Actívala en Configuración para probar la conexión.",
            }

        result = self.client.test_connection()
        result["enabled"] = True
        return result

    def sync_orders_from_odoo(self) -> Dict[str, Any]:
        """
        Idempotent pull of manufacturing orders from Odoo into local PostgreSQL.
        Does not destroy existing local annotations or stage history.
        """
        if not self.is_enabled():
            return {
                "synced_orders_count": 0,
                "new_orders": 0,
                "updated_orders": 0,
                "errors": ["Integración con Odoo desactivada"],
            }

        conn_status = self.client.test_connection()
        if not conn_status["connected"] or not conn_status["authenticated"]:
            return {
                "synced_orders_count": 0,
                "new_orders": 0,
                "updated_orders": 0,
                "errors": [conn_status.get("error") or "Odoo no disponible o no autenticado"]
            }

        batch_size = 100
        new_count = 0
        updated_count = 0
        synced_count = 0
        offset = 0
        try:
            while True:
                remote_orders = self.client.get_production_orders(limit=batch_size, offset=offset)
                now = datetime.now(timezone.utc)
                for ro in remote_orders:
                    odoo_id = ro["id"]
                    name = ro.get("name", f"MO-{odoo_id}")
                    product_raw = ro.get("product_id")
                    product_name = product_raw[1] if isinstance(product_raw, (list, tuple)) and len(product_raw) > 1 else "Producto Desconocido"
                    target_qty = int(ro.get("product_qty", 1))
                    state = ro.get("state", "draft")

                    order = self.production_repo.get_by_odoo_id(odoo_id) or self.production_repo.get_by_name(name)
                    if order:
                        order.odoo_order_id = odoo_id
                        order.state = state
                        order.product_name = product_name
                        order.target_qty = target_qty
                        order.last_sync_at = now
                        order.updated_at = now
                        self.production_repo.update(order)
                        updated_count += 1
                    else:
                        new_order = ProductionOrder(
                            odoo_order_id=odoo_id,
                            name=name,
                            product_name=product_name,
                            state=state,
                            target_qty=target_qty,
                            last_sync_at=now,
                            created_at=now,
                            updated_at=now
                        )
                        self.production_repo.create(new_order)
                        new_count += 1
                    synced_count += 1
                if len(remote_orders) < batch_size:
                    break
                offset += batch_size
        except Exception as error:
            return {
                "synced_orders_count": synced_count,
                "new_orders": new_count,
                "updated_orders": updated_count,
                "errors": [str(error)],
            }

        return {
            "synced_orders_count": synced_count,
            "new_orders": new_count,
            "updated_orders": updated_count,
            "errors": []
        }

    def sync_pending_events_to_odoo(self) -> Dict[str, Any]:
        """
        Attempts to push local confirmed production events that have order_id and sync_status == 'PENDIENTE'.
        If Odoo write operations are not confirmed or Odoo is offline, keeps events locally in 'PENDIENTE'.
        """
        pending_events = self.event_repo.get_pending_sync_for_update(limit=100)

        if not self.is_enabled():
            return {
                "total_pending": len(pending_events),
                "synced_count": 0,
                "status": "disabled_pending",
                "message": "La integración está desactivada. Los eventos permanecen pendientes localmente.",
            }

        conn_status = self.client.test_connection()

        if not conn_status["connected"] or not conn_status["authenticated"]:
            return {
                "total_pending": len(pending_events),
                "synced_count": 0,
                "status": "offline_pending",
                "message": "Eventos conservados localmente. Odoo no está conectado o autenticado."
            }

        synced_count = 0
        errors = []
        now = datetime.now(timezone.utc)
        for ev in pending_events:
            if ev.order_id and ev.association_status == "ASOCIADO":
                metadata = dict(ev.event_metadata or {})
                retry_at = metadata.get("odoo_retry_at")
                if retry_at:
                    try:
                        if datetime.fromisoformat(retry_at) > now:
                            continue
                    except ValueError:
                        pass

                attempts = int(metadata.get("odoo_sync_attempts", 0)) + 1
                order = self.production_repo.get_by_id(ev.order_id)
                try:
                    if not order or not order.odoo_order_id:
                        raise ValueError("La orden asociada no tiene referencia de Odoo")
                    self.client.post_production_event(
                        order.odoo_order_id,
                        ev.id,
                        {
                            "stage": ev.stage,
                            "event_type": ev.event_type,
                            "event_timestamp": ev.event_timestamp.isoformat(),
                            "confidence": ev.confidence,
                        },
                    )
                    metadata.update({
                        "odoo_sync_attempts": attempts,
                        "odoo_sync_timestamp": now.isoformat(),
                    })
                    metadata.pop("odoo_sync_error", None)
                    metadata.pop("odoo_retry_at", None)
                    ev.sync_status = "SINCRONIZADO"
                    synced_count += 1
                except Exception as error:
                    delay_seconds = min(3600, 30 * (2 ** min(attempts - 1, 7)))
                    metadata.update({
                        "odoo_sync_attempts": attempts,
                        "odoo_sync_error": str(error)[:500],
                        "odoo_retry_at": (now + timedelta(seconds=delay_seconds)).isoformat(),
                    })
                    errors.append(f"Evento #{ev.id}: {error}")
                    logger.warning(f"No se pudo sincronizar evento {ev.id} con Odoo: {error}")

                ev.event_metadata = metadata
                self.event_repo.update(ev)

        return {
            "total_pending": len(pending_events),
            "synced_count": synced_count,
            "status": "partial" if errors else "success",
            "errors": errors,
            "message": f"Se sincronizaron {synced_count} eventos; {len(errors)} quedarán pendientes de reintento."
        }
