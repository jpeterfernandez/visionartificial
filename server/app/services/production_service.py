from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.repositories.production_repository import ProductionRepository
from app.repositories.event_repository import EventRepository
from app.db.models.production_order import ProductionOrder
from app.db.models.production_event import ProductionEvent
from app.core.exceptions import NotFoundException, BadRequestException
from app.core.config import settings


class ProductionService:
    def __init__(self, db: Session):
        self.db = db
        self.production_repo = ProductionRepository(db)
        self.event_repo = EventRepository(db)

    def get_orders(
        self,
        skip: int = 0,
        limit: int = 50,
        state: Optional[str] = None,
        stage: Optional[str] = None,
        zones: Optional[List[str]] = None,
    ) -> List[ProductionOrder]:
        return self.production_repo.get_all(skip=skip, limit=limit, state=state, stage=stage, zones=zones)

    def get_order_by_id(self, order_id: int) -> ProductionOrder:
        order = self.production_repo.get_by_id(order_id)
        if not order:
            raise NotFoundException(f"Orden de producción #{order_id} no encontrada")
        return order

    def update_order(self, order_id: int, changes: Dict[str, Any]) -> ProductionOrder:
        order = self.get_order_by_id(order_id)
        if "name" in changes and changes["name"] != order.name:
            existing = self.production_repo.get_by_name(changes["name"])
            if existing:
                raise BadRequestException(f"Ya existe una orden con la referencia '{changes['name']}'")
        for field, value in changes.items():
            if value is None and field in {"name", "product_name", "target_qty", "state", "produced_qty"}:
                raise BadRequestException(f"El campo {field} no puede estar vacío")
            setattr(order, field, value)
        order.updated_at = datetime.now(timezone.utc)
        return self.production_repo.update(order)

    def delete_event(self, event_id: int) -> None:
        event = self.event_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException(f"Evento #{event_id} no encontrado")
        order = event.order
        if order and event.event_metadata and event.event_metadata.get("unit_completed"):
            order.produced_qty = max(0, order.produced_qty - 1)
            if order.state == "done" and order.produced_qty < order.target_qty:
                order.state = "progress"
            order.updated_at = datetime.now(timezone.utc)
        self.db.delete(event)
        self.db.commit()

    def create_order(
        self,
        name: str,
        product_name: str,
        target_qty: int = 1,
        state: str = "draft",
        notes: Optional[str] = None,
        odoo_order_id: Optional[int] = None,
        zone: Optional[str] = None,
    ) -> ProductionOrder:
        existing = self.production_repo.get_by_name(name)
        if existing:
            raise BadRequestException(f"Ya existe una orden con la referencia '{name}'")
        
        order = ProductionOrder(
            name=name,
            product_name=product_name,
            target_qty=target_qty,
            state=state,
            zone=zone,
            notes=notes,
            odoo_order_id=odoo_order_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        return self.production_repo.create(order)

    def associate_event_to_order(self, event_id: int, order_id: int) -> ProductionEvent:
        """
        Controlled association of an event to a production order.
        Updates the order's current_stage and advances state if appropriate.
        """
        event = self.event_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException(f"Evento #{event_id} no encontrado")

        order = self.get_order_by_id(order_id)
        event_zone = event.zone
        if not event_zone:
            raise BadRequestException("El evento no tiene una zona de cámara asociada")
        if order.zone and order.zone != event_zone:
            raise BadRequestException("La orden y el evento pertenecen a zonas diferentes")
        if not order.zone:
            order.zone = event_zone

        # Associate
        event.order_id = order.id
        event.association_status = "ASOCIADO"
        self.event_repo.update(event)

        # Update order current stage and state
        order.current_stage = event.stage
        if order.state == "draft":
            order.state = "progress"
        order.updated_at = datetime.now(timezone.utc)
        self.production_repo.update(order)

        return event

    def complete_unit_from_event(self, event_id: int, actor_username: str) -> ProductionEvent:
        event = self.event_repo.get_by_id(event_id)
        if not event:
            raise NotFoundException(f"Evento #{event_id} no encontrado")
        if event.event_metadata and event.event_metadata.get("unit_completed"):
            return event
        if event.association_status != "ASOCIADO" or not event.order_id:
            raise BadRequestException("Asocie el evento a una orden antes de confirmar la unidad")
        if event.stage != settings.FINAL_PRODUCTION_STAGE:
            raise BadRequestException(
                f"Solo se puede finalizar una unidad en la etapa {settings.FINAL_PRODUCTION_STAGE}"
            )

        order = self.get_order_by_id(event.order_id)
        if order.produced_qty >= order.target_qty:
            raise BadRequestException("La orden ya alcanzó la cantidad objetivo")

        now = datetime.now(timezone.utc)
        order.produced_qty += 1
        order.state = "done" if order.produced_qty >= order.target_qty else "progress"
        order.current_stage = event.stage
        order.updated_at = now
        event.event_type = "FIN_PRODUCTO"
        event.event_metadata = {
            **(event.event_metadata or {}),
            "unit_completed": True,
            "unit_completed_at": now.isoformat(),
            "unit_completed_by": actor_username,
        }
        self.db.commit()
        self.db.refresh(order)
        self.db.refresh(event)
        return event

    def get_order_timeline(self, order_id: int) -> Dict[str, Any]:
        """Calculates stage timeline and durations for an order based on real confirmed events."""
        order = self.get_order_by_id(order_id)
        events = self.event_repo.get_all(order_id=order.id, limit=100)
        
        # Sort chronologically
        sorted_events = sorted(events, key=lambda e: e.event_timestamp)

        stage_timelines = []
        for i, ev in enumerate(sorted_events):
            duration_minutes = None
            if i + 1 < len(sorted_events):
                next_ev = sorted_events[i + 1]
                duration_seconds = (next_ev.event_timestamp - ev.event_timestamp).total_seconds()
                duration_minutes = round(duration_seconds / 60.0, 1)

            stage_timelines.append({
                "event_id": ev.id,
                "stage": ev.stage,
                "event_type": ev.event_type,
                "timestamp": ev.event_timestamp.isoformat(),
                "duration_minutes": duration_minutes,
                "confidence": ev.confidence,
                "camera_id": ev.camera_id
            })

        return {
            "order_id": order.id,
            "order_name": order.name,
            "product_name": order.product_name,
            "current_stage": order.current_stage,
            "state": order.state,
            "total_events": len(sorted_events),
            "timeline": stage_timelines
        }
