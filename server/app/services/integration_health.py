import threading
from datetime import datetime, timezone
from typing import Any, Dict


_lock = threading.Lock()
_status: Dict[str, Any] = {
    "enabled": False,
    "connected": False,
    "authenticated": False,
    "latency_ms": None,
    "checked_at": None,
    "error": "Sin comprobación todavía",
}


def update_odoo_status(result: Dict[str, Any], latency_ms: float) -> None:
    with _lock:
        _status.update({
            "enabled": bool(result.get("enabled")),
            "connected": bool(result.get("connected")),
            "authenticated": bool(result.get("authenticated")),
            "latency_ms": round(latency_ms, 2),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "error": result.get("error"),
        })


def get_odoo_status() -> Dict[str, Any]:
    with _lock:
        return dict(_status)
