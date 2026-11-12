import xmlrpc.client
import html
from typing import Dict, Any, List, Optional, Tuple
from app.core.config import settings
from app.core.logging import logger


class OdooClient:
    """
    Decoupled Odoo External API client using standard XML-RPC.
    Handles connectivity testing, authentication, and safe read-only queries
    to manufacturing models (mrp.production, mrp.workorder).
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        database: Optional[str] = None,
        username: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None
    ):
        self.base_url = (base_url or settings.ODOO_BASE_URL).rstrip("/")
        self.database = database or settings.ODOO_DATABASE
        self.username = username or settings.ODOO_USERNAME
        self.api_key = api_key if api_key is not None else settings.ODOO_API_KEY
        self.timeout = timeout or settings.ODOO_TIMEOUT
        self._uid: Optional[int] = None

    def _transport(self):
        transport_type = (
            xmlrpc.client.SafeTransport
            if self.base_url.startswith("https://")
            else xmlrpc.client.Transport
        )
        timeout = self.timeout

        class BoundedTransport(transport_type):
            def make_connection(self, host):
                connection = super().make_connection(host)
                connection.timeout = timeout
                return connection

        return BoundedTransport()

    def is_configured(self) -> bool:
        """Returns True if minimum connection settings are provided."""
        return bool(self.base_url and self.database and self.username and self.api_key)

    def test_connection(self) -> Dict[str, Any]:
        """
        Tests connectivity to Odoo server, checks server version,
        and verifies user credentials if configured.
        """
        result = {
            "configured": self.is_configured(),
            "connected": False,
            "base_url": self.base_url,
            "database": self.database,
            "username": self.username,
            "server_version": None,
            "authenticated": False,
            "error": None
        }

        if not self.base_url:
            result["error"] = "ODOO_BASE_URL no está configurada"
            return result

        try:
            common = xmlrpc.client.ServerProxy(
                f"{self.base_url}/xmlrpc/2/common",
                transport=self._transport(),
                allow_none=True,
                use_builtin_types=True
            )
            # Check version
            version_info = common.version()
            result["connected"] = True
            result["server_version"] = version_info.get("server_version", "Desconocida")

            # Check authentication if API key or password is provided
            if self.is_configured():
                uid = common.authenticate(
                    self.database,
                    self.username,
                    self.api_key,
                    {}
                )
                if uid:
                    self._uid = uid
                    result["authenticated"] = True
                else:
                    result["authenticated"] = False
                    result["error"] = "Credenciales incorrectas en Odoo (usuario o API Key inválidos)"
            else:
                result["error"] = "Faltan ODOO_API_KEY o parámetros de autenticación para validar credenciales"

        except Exception as e:
            result["connected"] = False
            result["authenticated"] = False
            result["error"] = f"No se pudo conectar con el servidor Odoo: {str(e)}"
            logger.warning(f"Error comprobando conexión con Odoo: {e}")

        return result

    def get_uid(self) -> Optional[int]:
        """Authenticates and caches the user ID."""
        if self._uid:
            return self._uid

        if not self.is_configured():
            return None

        try:
            common = xmlrpc.client.ServerProxy(
                f"{self.base_url}/xmlrpc/2/common",
                transport=self._transport(),
                allow_none=True,
                use_builtin_types=True
            )
            uid = common.authenticate(self.database, self.username, self.api_key, {})
            if uid:
                self._uid = uid
                return uid
        except Exception as e:
            logger.error(f"Fallo al autenticar contra Odoo: {e}")
        return None

    def get_production_orders(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """
        Safely retrieves manufacturing orders from 'mrp.production' model.
        Returns an empty list if Odoo is unreachable or not authenticated.
        """
        uid = self.get_uid()
        if not uid:
            logger.info("Odoo no autenticado o no disponible; omitiendo consulta remota de órdenes.")
            return []

        try:
            models = xmlrpc.client.ServerProxy(
                f"{self.base_url}/xmlrpc/2/object",
                transport=self._transport(),
                allow_none=True,
                use_builtin_types=True
            )
            # Read standard manufacturing fields
            fields = [
                "id", "name", "product_id", "product_qty",
                "state", "date_planned_start", "date_planned_finished"
            ]
            orders = models.execute_kw(
                self.database,
                uid,
                self.api_key,
                "mrp.production",
                "search_read",
                [[["state", "!=", "cancel"]]],
                {"fields": fields, "limit": limit, "offset": offset, "order": "id asc"}
            )
            return orders or []
        except Exception as e:
            logger.warning(f"Error consultando 'mrp.production' en Odoo: {e}")
            raise RuntimeError("No se pudo consultar la página de órdenes en Odoo") from e

    def post_production_event(self, odoo_order_id: int, event_id: int, event: Dict[str, Any]) -> bool:
        """Posts an event note once, using its stable local ID as the idempotency key."""
        uid = self.get_uid()
        if not uid:
            raise RuntimeError("Odoo no autenticado")

        models = xmlrpc.client.ServerProxy(
            f"{self.base_url}/xmlrpc/2/object",
            transport=self._transport(),
            allow_none=True,
            use_builtin_types=True,
        )
        marker = f"CARDINOVA-EVENT:{event_id}"
        existing = models.execute_kw(
            self.database,
            uid,
            self.api_key,
            "mail.message",
            "search_read",
            [[
                ["model", "=", "mrp.production"],
                ["res_id", "=", odoo_order_id],
                ["body", "ilike", marker],
            ]],
            {"fields": ["id"], "limit": 1},
        )
        if existing:
            return False

        note = (
            f"{marker}<br/>Etapa: {html.escape(str(event['stage']))}"
            f"<br/>Tipo: {html.escape(str(event['event_type']))}"
            f"<br/>Fecha: {html.escape(str(event['event_timestamp']))}"
            f"<br/>Confianza: {float(event['confidence']):.4f}"
        )
        models.execute_kw(
            self.database,
            uid,
            self.api_key,
            "mrp.production",
            "message_post",
            [[odoo_order_id]],
            {"body": note, "message_type": "comment", "subtype_xmlid": "mail.mt_note"},
        )
        return True
