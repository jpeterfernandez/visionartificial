from typing import List, Optional
from datetime import datetime, timedelta, timezone
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.schemas.event import ProductionEventResponse, ProductionEventAssociate, ProductionEventUpdate
from app.repositories.event_repository import EventRepository
from app.services.production_service import ProductionService
from app.core.exceptions import NotFoundException, ForbiddenException, BadRequestException
from app.core.config import settings
from app.repositories.audit_repository import record_audit
from app.core.zones import allowed_zones_for_user, user_can_access_zone

router = APIRouter(prefix="/events", tags=["Eventos de Producción"])


def _validate_date_range(date_from: Optional[datetime], date_to: Optional[datetime]):
    if date_from and date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    if date_from and date_to and date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to debe ser posterior o igual a date_from")
    if date_from and date_to and date_to - date_from > timedelta(days=90):
        raise HTTPException(status_code=422, detail="El rango máximo para eventos es de 90 días")
    return date_from, date_to


def _ensure_event_zone_access(event, user: User) -> None:
    if not user_can_access_zone(user, event.zone):
        raise ForbiddenException("No tiene acceso a la zona de este evento")


@router.get("", response_model=List[ProductionEventResponse])
def get_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    stage: Optional[str] = None,
    camera_id: Optional[int] = None,
    order_id: Optional[int] = None,
    association_status: Optional[str] = None,
    sync_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    date_from, date_to = _validate_date_range(date_from, date_to)
    repo = EventRepository(db)
    events = repo.get_all(
        skip=skip,
        limit=limit,
        stage=stage,
        camera_id=camera_id,
        order_id=order_id,
        association_status=association_status,
        sync_status=sync_status,
        date_from=date_from,
        date_to=date_to,
        camera_zones=(list(allowed_zones_for_user(current_user)) if allowed_zones_for_user(current_user) is not None else None),
    )
    
    # Map relation names for response
    result = []
    for ev in events:
        resp = ProductionEventResponse.model_validate(ev)
        if ev.order:
            resp.order_name = ev.order.name
        if ev.camera:
            resp.camera_name = ev.camera.name
        result.append(resp)
    return result


@router.get("/export.csv")
def export_events_csv(
    stage: Optional[str] = None,
    camera_id: Optional[int] = None,
    order_id: Optional[int] = None,
    association_status: Optional[str] = None,
    sync_status: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    date_from, date_to = _validate_date_range(date_from, date_to)
    events = EventRepository(db).get_all(
        limit=10001,
        stage=stage,
        camera_id=camera_id,
        order_id=order_id,
        association_status=association_status,
        sync_status=sync_status,
        date_from=date_from,
        date_to=date_to,
        camera_zones=(list(allowed_zones_for_user(current_user)) if allowed_zones_for_user(current_user) is not None else None),
    )
    if len(events) > 10000:
        raise HTTPException(status_code=413, detail="Aplique filtros para exportar un máximo de 10.000 eventos por archivo")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "fecha_utc", "zona", "etapa", "camara", "orden", "asociacion", "sincronizacion", "confianza"])
    for event in events:
        writer.writerow([
            event.id,
            event.event_timestamp.isoformat(),
            event.zone,
            event.stage,
            event.camera.name if event.camera else event.camera_id,
            event.order.name if event.order else event.order_id,
            event.association_status,
            event.sync_status,
            event.confidence,
        ])
    output.seek(0)
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=eventos-produccion.csv"},
    )


@router.get("/{event_id}", response_model=ProductionEventResponse)
def get_event(
    event_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    repo = EventRepository(db)
    ev = repo.get_by_id(event_id)
    if not ev:
        raise NotFoundException(f"Evento #{event_id} no encontrado")
    _ensure_event_zone_access(ev, current_user)

    resp = ProductionEventResponse.model_validate(ev)
    if ev.order:
        resp.order_name = ev.order.name
    if ev.camera:
        resp.camera_name = ev.camera.name
    return resp


@router.post("/{event_id}/associate", response_model=ProductionEventResponse)
def associate_event(
    event_id: int,
    payload: ProductionEventAssociate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    event = EventRepository(db).get_by_id(event_id)
    if not event:
        raise NotFoundException(f"Evento #{event_id} no encontrado")
    _ensure_event_zone_access(event, current_user)
    record_audit(db, current_user, "event.associated", "production_event", str(event_id), {"order_id": payload.order_id})
    service = ProductionService(db)
    ev = service.associate_event_to_order(event_id=event_id, order_id=payload.order_id)
    resp = ProductionEventResponse.model_validate(ev)
    if ev.order:
        resp.order_name = ev.order.name
    if ev.camera:
        resp.camera_name = ev.camera.name
    return resp


@router.patch("/{event_id}", response_model=ProductionEventResponse)
def update_event(
    event_id: int,
    payload: ProductionEventUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("ADMIN")),
):
    repo = EventRepository(db)
    event = repo.get_by_id(event_id)
    if not event:
        raise NotFoundException(f"Evento #{event_id} no encontrado")
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Indique al menos un campo para actualizar")
    if (
        event.event_metadata
        and event.event_metadata.get("unit_completed")
        and changes.get("stage", settings.FINAL_PRODUCTION_STAGE) != settings.FINAL_PRODUCTION_STAGE
    ):
        raise BadRequestException("No se puede cambiar la etapa de un evento que ya contabilizó una unidad")
    for field, value in changes.items():
        setattr(event, field, value)
    record_audit(db, admin, "event.updated", "production_event", str(event_id), {"changed_fields": sorted(changes)})
    event = repo.update(event)
    response = ProductionEventResponse.model_validate(event)
    if event.order:
        response.order_name = event.order.name
    if event.camera:
        response.camera_name = event.camera.name
    return response


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("ADMIN")),
):
    event = EventRepository(db).get_by_id(event_id)
    if not event:
        raise NotFoundException(f"Evento #{event_id} no encontrado")
    record_audit(db, admin, "event.deleted", "production_event", str(event_id), {"stage": event.stage})
    ProductionService(db).delete_event(event_id)
    return None


@router.post("/{event_id}/complete-unit", response_model=ProductionEventResponse)
def complete_production_unit(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR")),
):
    event = EventRepository(db).get_by_id(event_id)
    if not event:
        raise NotFoundException(f"Evento #{event_id} no encontrado")
    _ensure_event_zone_access(event, current_user)
    record_audit(db, current_user, "production.unit_completed", "production_event", str(event_id))
    event = ProductionService(db).complete_unit_from_event(event_id, current_user.username)
    response = ProductionEventResponse.model_validate(event)
    if event.order:
        response.order_name = event.order.name
    if event.camera:
        response.camera_name = event.camera.name
    return response
