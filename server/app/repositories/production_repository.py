from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.db.models.production_order import ProductionOrder


class ProductionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, order_id: int) -> Optional[ProductionOrder]:
        return self.db.query(ProductionOrder).filter(ProductionOrder.id == order_id).first()

    def get_by_name(self, name: str) -> Optional[ProductionOrder]:
        return self.db.query(ProductionOrder).filter(ProductionOrder.name == name).first()

    def get_by_odoo_id(self, odoo_id: int) -> Optional[ProductionOrder]:
        return self.db.query(ProductionOrder).filter(ProductionOrder.odoo_order_id == odoo_id).first()

    def get_all(
        self,
        skip: int = 0,
        limit: int = 50,
        state: Optional[str] = None,
        stage: Optional[str] = None,
        zones: Optional[List[str]] = None,
    ) -> List[ProductionOrder]:
        query = self.db.query(ProductionOrder)
        if state:
            query = query.filter(ProductionOrder.state == state)
        if stage:
            query = query.filter(ProductionOrder.current_stage == stage)
        if zones is not None:
            if not zones:
                return []
            query = query.filter(ProductionOrder.zone.in_(zones))
        return query.order_by(desc(ProductionOrder.updated_at)).offset(skip).limit(limit).all()

    def count(self, state: Optional[str] = None, zones: Optional[List[str]] = None) -> int:
        query = self.db.query(ProductionOrder)
        if state:
            query = query.filter(ProductionOrder.state == state)
        if zones is not None:
            if not zones:
                return 0
            query = query.filter(ProductionOrder.zone.in_(zones))
        return query.count()

    def create(self, order: ProductionOrder) -> ProductionOrder:
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    def update(self, order: ProductionOrder) -> ProductionOrder:
        self.db.commit()
        self.db.refresh(order)
        return order

    def delete(self, order: ProductionOrder) -> None:
        self.db.delete(order)
        self.db.commit()
