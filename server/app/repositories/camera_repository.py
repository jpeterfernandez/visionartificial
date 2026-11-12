from typing import Optional, List
from sqlalchemy.orm import Session
from app.db.models.camera import Camera


class CameraRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, camera_id: int) -> Optional[Camera]:
        return self.db.query(Camera).filter(Camera.id == camera_id).first()

    def get_by_zone(self, zone: str) -> Optional[Camera]:
        return self.db.query(Camera).filter(Camera.zone == zone).first()

    def get_all(self, only_active: bool = False) -> List[Camera]:
        query = self.db.query(Camera)
        if only_active:
            query = query.filter(Camera.is_active == True)
        return query.order_by(Camera.id).all()

    def create(self, camera: Camera) -> Camera:
        self.db.add(camera)
        self.db.commit()
        self.db.refresh(camera)
        return camera

    def update(self, camera: Camera) -> Camera:
        self.db.commit()
        self.db.refresh(camera)
        return camera

    def delete(self, camera: Camera) -> None:
        self.db.delete(camera)
        self.db.commit()

