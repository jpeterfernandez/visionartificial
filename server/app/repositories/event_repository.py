from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from app.db.models.production_event import ProductionEvent


class EventRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, event_id: int) -> Optional[ProductionEvent]:
        return self.db.query(ProductionEvent).filter(ProductionEvent.id == event_id).first()

    def get_latest_for_camera(self, camera_id: int) -> Optional[ProductionEvent]:
        return (
            self.db.query(ProductionEvent)
            .filter(ProductionEvent.camera_id == camera_id)
            .order_by(desc(ProductionEvent.event_timestamp))
            .first()
        )

    def get_all(
        self,
        skip: int = 0,
        limit: int = 50,
        stage: Optional[str] = None,
        camera_id: Optional[int] = None,
        order_id: Optional[int] = None,
        association_status: Optional[str] = None,
        sync_status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        camera_zones: Optional[List[str]] = None,
    ) -> List[ProductionEvent]:
        query = self.db.query(ProductionEvent)
        if stage:
            query = query.filter(ProductionEvent.stage == stage)
        if camera_id:
            query = query.filter(ProductionEvent.camera_id == camera_id)
        if order_id:
            query = query.filter(ProductionEvent.order_id == order_id)
        if association_status:
            query = query.filter(ProductionEvent.association_status == association_status)
        if sync_status:
            query = query.filter(ProductionEvent.sync_status == sync_status)
        if date_from:
            query = query.filter(ProductionEvent.event_timestamp >= date_from)
        if date_to:
            query = query.filter(ProductionEvent.event_timestamp <= date_to)
        if camera_zones is not None:
            if not camera_zones:
                return []
            query = query.filter(ProductionEvent.zone.in_(camera_zones))
        return query.order_by(desc(ProductionEvent.event_timestamp)).offset(skip).limit(limit).all()

    def get_pending_sync_for_update(self, limit: int = 100) -> List[ProductionEvent]:
        return (
            self.db.query(ProductionEvent)
            .filter(
                ProductionEvent.sync_status == "PENDIENTE",
                ProductionEvent.association_status == "ASOCIADO",
            )
            .order_by(ProductionEvent.event_timestamp)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )

    def _zone_query(self, camera_zones: Optional[List[str]]):
        query = self.db.query(ProductionEvent)
        if camera_zones is not None:
            if not camera_zones:
                return None
            query = query.filter(ProductionEvent.zone.in_(camera_zones))
        return query

    def count_pending_association(self, camera_zones: Optional[List[str]] = None) -> int:
        query = self._zone_query(camera_zones)
        return query.filter(ProductionEvent.association_status == "PENDIENTE").count() if query is not None else 0

    def count_pending_sync(self, camera_zones: Optional[List[str]] = None) -> int:
        query = self._zone_query(camera_zones)
        return query.filter(ProductionEvent.sync_status == "PENDIENTE").count() if query is not None else 0

    def count_today(self, start_of_day: datetime, camera_zones: Optional[List[str]] = None) -> int:
        query = self._zone_query(camera_zones)
        return query.filter(ProductionEvent.event_timestamp >= start_of_day).count() if query is not None else 0

    def get_stage_distribution(self, camera_zones: Optional[List[str]] = None) -> List[dict]:
        query = self._zone_query(camera_zones)
        if query is None:
            return []
        results = (
            query.with_entities(ProductionEvent.stage, func.count(ProductionEvent.id))
            .group_by(ProductionEvent.stage)
            .all()
        )
        return [{"stage": r[0], "count": r[1]} for r in results]

    def create(self, event: ProductionEvent) -> ProductionEvent:
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def update(self, event: ProductionEvent) -> ProductionEvent:
        self.db.commit()
        self.db.refresh(event)
        return event

    def delete(self, event: ProductionEvent) -> None:
        self.db.delete(event)
        self.db.commit()
