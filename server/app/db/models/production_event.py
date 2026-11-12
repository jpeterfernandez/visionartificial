from datetime import datetime, timezone
from typing import Optional, Dict, Any
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class ProductionEvent(Base):
    __tablename__ = "production_events"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True, index=True)
    order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("production_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    zone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    
    stage: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # DOBLADO, ARMADO_ESTRUCTURAL, VINILADO, ALMACEN, NO_IDENTIFICADO
    event_type: Mapped[str] = mapped_column(String(50), default="DETECCION_CONFIRMADA", nullable=False)  # DETECCION_CONFIRMADA, INICIO_ETAPA, FIN_ETAPA
    
    association_status: Mapped[str] = mapped_column(String(30), default="PENDIENTE", nullable=False, index=True)  # PENDIENTE, ASOCIADO, RECHAZADO
    sync_status: Mapped[str] = mapped_column(String(30), default="PENDIENTE", nullable=False, index=True)  # PENDIENTE, SINCRONIZADO, ERROR
    
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    origin: Mapped[str] = mapped_column(String(50), default="VISION_ARTIFICIAL", nullable=False)  # VISION_ARTIFICIAL, MANUAL, SISTEMA
    
    event_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    camera: Mapped[Optional["Camera"]] = relationship("Camera", back_populates="events")
    order: Mapped[Optional["ProductionOrder"]] = relationship("ProductionOrder", back_populates="events")
