from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.db.models.detection import Detection


class DetectionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, detection_id: int) -> Optional[Detection]:
        return self.db.query(Detection).filter(Detection.id == detection_id).first()

    def get_all(
        self,
        skip: int = 0,
        limit: int = 50,
        camera_id: Optional[int] = None,
        class_name: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        camera_zones: Optional[List[str]] = None,
    ) -> List[Detection]:
        query = self.db.query(Detection)
        if camera_id:
            query = query.filter(Detection.camera_id == camera_id)
        if class_name:
            query = query.filter(Detection.class_name == class_name)
        if date_from:
            query = query.filter(Detection.created_at >= date_from)
        if date_to:
            query = query.filter(Detection.created_at <= date_to)
        if camera_zones is not None:
            if not camera_zones:
                return []
            query = query.filter(Detection.zone.in_(camera_zones))
        return query.order_by(desc(Detection.created_at)).offset(skip).limit(limit).all()

    def count_today(self, start_of_day: datetime, camera_zones: Optional[List[str]] = None) -> int:
        query = self.db.query(Detection).filter(Detection.created_at >= start_of_day)
        if camera_zones is not None:
            if not camera_zones:
                return 0
            query = query.filter(Detection.zone.in_(camera_zones))
        return query.count()

    def create(self, detection: Detection) -> Detection:
        self.db.add(detection)
        self.db.commit()
        self.db.refresh(detection)
        return detection
