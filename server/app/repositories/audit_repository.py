from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db.models.audit_log import AuditLog
from app.db.models.user import User


def record_audit(
    db: Session,
    actor: User,
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    entry = AuditLog(
        actor_user_id=actor.id,
        actor_username=actor.username,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    db.add(entry)
    return entry
