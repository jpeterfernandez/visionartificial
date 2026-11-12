from typing import List, Optional, Dict, Any
import csv
import io
from fastapi import APIRouter, Depends, Query, Path, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.schemas.production import ProductionOrderResponse, ProductionOrderCreate, ProductionOrderUpdate
from app.services.production_service import ProductionService
from app.core.exceptions import BadRequestException, ForbiddenException
from app.core.zones import allowed_zones_for_user, user_can_access_zone
from app.repositories.audit_repository import record_audit
from app.repositories.production_repository import ProductionRepository

router = APIRouter(prefix="/production", tags=["Órdenes de Producción"])


@router.get("/orders/export.csv")
def export_orders_csv(
    state: Optional[str] = None,
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zones = allowed_zones_for_user(current_user)
    orders = ProductionService(db).get_orders(
        skip=0,
        limit=10001,
        state=state,
        stage=stage,
        zones=list(zones) if zones is not None else None,
    )
    if len(orders) > 10000:
        raise HTTPException(status_code=413, detail="Aplique filtros para exportar un máximo de 10.000 órdenes")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "referencia", "producto", "zona", "estado", "etapa", "producidas", "objetivo", "actualizada_utc"])
    writer.writerows([
        [order.id, order.name, order.product_name, order.zone, order.state, order.current_stage,
         order.produced_qty, order.target_qty, order.updated_at.isoformat()]
        for order in orders
    ])
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=ordenes-produccion.csv"},
    )


@router.get("/orders", response_model=List[ProductionOrderResponse])
def get_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    state: Optional[str] = None,
    stage: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = ProductionService(db)
    zones = allowed_zones_for_user(current_user)
    return service.get_orders(skip=skip, limit=limit, state=state, stage=stage, zones=list(zones) if zones is not None else None)


@router.get("/orders/{order_id}", response_model=ProductionOrderResponse)
def get_order(
    order_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = ProductionService(db)
    order = service.get_order_by_id(order_id)
    if not user_can_access_zone(current_user, order.zone):
        raise ForbiddenException("No tiene acceso a la zona de esta orden")
    return order


@router.post("/orders", response_model=ProductionOrderResponse)
def create_order(
    payload: ProductionOrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    service = ProductionService(db)
    if not user_can_access_zone(current_user, payload.zone):
        raise ForbiddenException("No tiene permiso para crear órdenes en esta zona")
    return service.create_order(
        name=payload.name,
        product_name=payload.product_name,
        target_qty=payload.target_qty,
        state=payload.state,
        zone=payload.zone,
        notes=payload.notes,
        odoo_order_id=payload.odoo_order_id
    )


@router.patch("/orders/{order_id}", response_model=ProductionOrderResponse)
def update_order(
    order_id: int,
    payload: ProductionOrderUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("ADMIN")),
):
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise BadRequestException("Indique al menos un campo para actualizar")
    service = ProductionService(db)
    service.get_order_by_id(order_id)
    record_audit(db, admin, "production_order.updated", "production_order", str(order_id), {"changed_fields": sorted(changes)})
    return service.update_order(order_id, changes)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("ADMIN")),
):
    order = ProductionService(db).get_order_by_id(order_id)
    record_audit(db, admin, "production_order.deleted", "production_order", str(order_id), {"name": order.name})
    ProductionRepository(db).delete(order)
    return None


@router.get("/orders/{order_id}/timeline")
def get_order_timeline(
    order_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    service = ProductionService(db)
    order = service.get_order_by_id(order_id)
    if not user_can_access_zone(current_user, order.zone):
        raise ForbiddenException("No tiene acceso a la zona de esta orden")
    return service.get_order_timeline(order_id)
