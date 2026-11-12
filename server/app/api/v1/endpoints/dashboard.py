import json
from datetime import datetime, timezone, time, timedelta
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user
from app.schemas.dashboard import DashboardStatsResponse, SystemStatusSummary, StageCount, ZoneMachineCount, ProductionTrendPoint
from app.schemas.event import ProductionEventResponse
from app.db.models.production_event import ProductionEvent
from app.repositories.production_repository import ProductionRepository
from app.repositories.event_repository import EventRepository
from app.repositories.detection_repository import DetectionRepository
from app.repositories.camera_repository import CameraRepository
from app.repositories.setting_repository import SettingRepository
from app.services.yolo_service import yolo_service
from app.services.integration_health import get_odoo_status
from app.services.request_metrics import request_metrics
from app.api.v1.endpoints.cameras import camera_response_for_user
from app.core.zones import PRODUCTION_ZONES, allowed_zones_for_user

router = APIRouter(prefix="/dashboard", tags=["Panel de Control y Métricas"])


@router.get("/production-trends", response_model=List[ProductionTrendPoint])
def get_production_trends(
    start: datetime = Query(...),
    end: datetime = Query(...),
    interval_minutes: int = Query(1, ge=1, le=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(status_code=422, detail="end debe ser posterior a start")
    if end - start > timedelta(days=7):
        raise HTTPException(status_code=422, detail="El rango máximo permitido es de 7 días")

    interval_seconds = interval_minutes * 60
    allowed_zones = allowed_zones_for_user(current_user)
    bucket_timestamp = func.to_timestamp(
        func.floor(func.extract("epoch", ProductionEvent.event_timestamp) / interval_seconds) * interval_seconds
    )
    trend_query = db.query(
        bucket_timestamp.label("timestamp"),
        ProductionEvent.stage,
        func.count(ProductionEvent.id).label("count"),
    ).filter(
        ProductionEvent.event_timestamp >= start,
        ProductionEvent.event_timestamp < end,
    )
    if allowed_zones is not None:
        if not allowed_zones:
            return []
        trend_query = trend_query.filter(ProductionEvent.zone.in_(allowed_zones))
    rows = (
        trend_query.group_by(bucket_timestamp, ProductionEvent.stage)
        .order_by(bucket_timestamp, ProductionEvent.stage)
        .all()
    )

    return [
        ProductionTrendPoint(timestamp=row.timestamp, stage=row.stage, count=row.count)
        for row in rows
    ]


@router.get("/stats", response_model=DashboardStatsResponse)
def get_dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prod_repo = ProductionRepository(db)
    event_repo = EventRepository(db)
    det_repo = DetectionRepository(db)
    cam_repo = CameraRepository(db)
    allowed_zones = allowed_zones_for_user(current_user)
    camera_zones = list(allowed_zones) if allowed_zones is not None else None

    # Database connectivity check
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    odoo_ok = get_odoo_status()["connected"]

    # Cameras
    cameras = cam_repo.get_all()
    if allowed_zones is not None:
        cameras = [camera for camera in cameras if camera.zone in allowed_zones]
    active_cameras = [c for c in cameras if c.is_active]
    connected_cameras = [c for c in cameras if c.is_connected]

    # Orders stats
    total_orders = prod_repo.count(zones=camera_zones)
    in_progress = prod_repo.count(state="progress", zones=camera_zones)
    completed = prod_repo.count(state="done", zones=camera_zones)

    # Today's boundaries
    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    detections_today = det_repo.count_today(today_start, camera_zones)
    events_today = event_repo.count_today(today_start, camera_zones)

    # Pending items
    pending_association = event_repo.count_pending_association(camera_zones)
    pending_sync = event_repo.count_pending_sync(camera_zones)

    # Stage distribution
    raw_dist = event_repo.get_stage_distribution(camera_zones)
    stage_dist = [StageCount(stage=d["stage"], count=d["count"]) for d in raw_dist]

    snapshot_setting = SettingRepository(db).get_by_key("CAMERA_PRODUCTION_SNAPSHOT")
    try:
        camera_snapshots = json.loads(snapshot_setting.value) if snapshot_setting else {}
    except (TypeError, json.JSONDecodeError):
        camera_snapshots = {}

    zone_machine_counts = []
    visible_zones = sorted(allowed_zones if allowed_zones is not None else PRODUCTION_ZONES)
    for zone in visible_zones:
        zone_cameras = [camera for camera in active_cameras if camera.zone == zone]
        zone_snapshots = [(camera, camera_snapshots.get(str(camera.id))) for camera in zone_cameras]
        stage_counts = {}
        classification_counts = {}
        vinyl_color_counts: dict = {}
        warnings = [] if zone_cameras else ["No hay cámaras activas asignadas a esta zona."]
        update_times = []
        machine_count = 0
        for camera, snapshot in zone_snapshots:
            if not snapshot:
                warnings.append(f"{camera.name}: sin capturas procesadas.")
                continue
            if snapshot.get("last_updated"):
                update_times.append(datetime.fromisoformat(snapshot["last_updated"]))
            if snapshot.get("warning"):
                warnings.append(f"{camera.name}: {snapshot['warning']}")
            elif not camera.is_connected:
                warnings.append(f"{camera.name}: sin conexión con la cámara.")
            if camera.is_connected:
                machine_count += int(snapshot.get("machine_count", 0))
                for stage, count in snapshot.get("stage_counts", {}).items():
                    stage_counts[stage] = stage_counts.get(stage, 0) + int(count)
                for label, count in snapshot.get("classification_counts", {}).items():
                    classification_counts[label] = classification_counts.get(label, 0) + int(count)
                for color, count in snapshot.get("vinyl_color_counts", {}).items():
                    vinyl_color_counts[color] = vinyl_color_counts.get(color, 0) + int(count)

        updated_at = max(update_times) if update_times else None
        zone_machine_counts.append(ZoneMachineCount(
            zone=zone,
            machine_count=machine_count,
            stage_counts=stage_counts,
            classification_counts=classification_counts,
            vinyl_color_counts=vinyl_color_counts,
            last_updated=updated_at,
            warnings=warnings,
        ))

    # Recent events
    recent_events_db = event_repo.get_all(limit=10, camera_zones=camera_zones)
    recent_events = []
    for ev in recent_events_db:
        ev_dto = ProductionEventResponse.model_validate(ev)
        if ev.order:
            ev_dto.order_name = ev.order.name
        if ev.camera:
            ev_dto.camera_name = ev.camera.name
        recent_events.append(ev_dto)

    status_summary = SystemStatusSummary(
        postgres_connected=db_ok,
        yolo_loaded=yolo_service.is_loaded,
        odoo_connected=odoo_ok,
        active_cameras_count=len(active_cameras),
        connected_cameras_count=len(connected_cameras)
    )

    status_summary.api_latency_ms = request_metrics.snapshot()["p95_latency_ms"]
    return DashboardStatsResponse(
        status=status_summary,
        total_orders=total_orders,
        in_progress_orders=in_progress,
        completed_orders=completed,
        total_detections_today=detections_today,
        total_events_today=events_today,
        pending_association_events_count=pending_association,
        pending_sync_events_count=pending_sync,
        stage_distribution=stage_dist,
        zone_machine_counts=zone_machine_counts,
        recent_events=recent_events,
        cameras=[camera_response_for_user(camera, current_user, camera_snapshots) for camera in cameras]
    )
