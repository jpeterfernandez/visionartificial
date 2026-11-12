from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    health,
    dashboard,
    models,
    detections,
    events,
    production,
    cameras,
    odoo,
    settings,
    users,
    audit,
    detection_zones,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(dashboard.router)
api_router.include_router(models.router)
api_router.include_router(detections.router)
api_router.include_router(events.router)
api_router.include_router(production.router)
api_router.include_router(cameras.router)
api_router.include_router(odoo.router)
api_router.include_router(settings.router)
api_router.include_router(users.router)
api_router.include_router(audit.router)
api_router.include_router(detection_zones.router)
