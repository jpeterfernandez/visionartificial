from datetime import datetime
from typing import Any, Dict, List, Optional
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.api.dependencies import require_role
from app.db.models.audit_log import AuditLog
from app.db.models.user import User
from app.db.session import get_db

router = APIRouter(prefix="/audit", tags=["Auditoría"])


class AuditLogResponse(BaseModel):
    id: int
    actor_user_id: Optional[int]
    actor_username: str
    action: str
    target_type: str
    target_id: Optional[str]
    details: Optional[Dict[str, Any]]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("", response_model=List[AuditLogResponse])
def list_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("ADMIN")),
):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/export.csv")
def export_audit_logs_csv(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("ADMIN")),
):
    entries = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10001).all()
    if len(entries) > 10000:
        entries = entries[:10000]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "fecha_utc", "usuario", "accion", "tipo_objetivo", "objetivo_id", "detalles"])
    writer.writerows([
        [entry.id, entry.created_at.isoformat(), entry.actor_username, entry.action,
         entry.target_type, entry.target_id, str(entry.details or {})]
        for entry in entries
    ])
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=auditoria.csv"},
    )
