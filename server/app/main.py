from contextlib import asynccontextmanager
import asyncio
import json
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.core.exceptions import CardinovaException
from app.api.router import api_router
from app.services.yolo_service import yolo_service
from app.db.session import SessionLocal
from app.repositories.setting_repository import SettingRepository
from app.schemas.detection import YoloRuntimeConfiguration
from app.services.odoo_service import OdooService
from app.services.camera_monitor import check_camera_connections
from app.services.camera_capture import process_active_camera_captures
from app.services.integration_health import update_odoo_status
from app.services.request_metrics import request_metrics


def _sync_pending_odoo_events():
    db = SessionLocal()
    try:
        OdooService(db).sync_pending_events_to_odoo()
    except Exception as error:
        logger.warning(f"No se pudo procesar la cola de eventos Odoo: {error}")
    finally:
        db.close()


def _check_cameras():
    db = SessionLocal()
    try:
        check_camera_connections(db)
    except Exception as error:
        logger.warning(f"No se pudo comprobar el estado de las cámaras: {error}")
    finally:
        db.close()


def _refresh_odoo_health():
    db = SessionLocal()
    try:
        service = OdooService(db)
        started_at = time.perf_counter()
        result = service.test_connection()
        update_odoo_status(result, (time.perf_counter() - started_at) * 1000)
    except Exception as error:
        update_odoo_status({"enabled": True, "connected": False, "authenticated": False, "error": str(error)}, 0)
    finally:
        db.close()


async def _odoo_event_sync_worker():
    while True:
        await asyncio.sleep(max(5, settings.ODOO_SYNC_INTERVAL_SECONDS))
        await asyncio.to_thread(_refresh_odoo_health)
        await asyncio.to_thread(_sync_pending_odoo_events)


async def _camera_health_worker():
    while True:
        await asyncio.sleep(max(5, settings.CAMERA_HEALTH_CHECK_INTERVAL_SECONDS))
        await asyncio.to_thread(_check_cameras)


async def _camera_capture_worker():
    while True:
        try:
            await asyncio.to_thread(process_active_camera_captures)
        except Exception as error:
            logger.error(f"Error al procesar capturas periódicas de cámaras: {error}", exc_info=True)
        await asyncio.sleep(max(1, settings.CAMERA_CAPTURE_INTERVAL_SECONDS))


def _load_saved_yolo_runtime_configuration():
    if settings.ENVIRONMENT.lower() != "development":
        return

    db = SessionLocal()
    try:
        saved = SettingRepository(db).get_by_key("YOLO_RUNTIME_CONFIGURATION")
        if saved:
            saved_configuration = json.loads(saved.value)
            saved_configuration.setdefault("img_size", yolo_service.img_size)
            saved_configuration.setdefault("stream_interval_ms", yolo_service.stream_interval_ms)
            configuration = YoloRuntimeConfiguration.model_validate(saved_configuration)
            yolo_service.configure_runtime(configuration.model_dump())
            logger.info("Configuración de recursos YOLO de desarrollo aplicada.")
    except Exception as error:
        logger.warning(f"No se pudo recuperar la configuración de recursos YOLO: {error}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    logger.info("==================================================")
    logger.info("Iniciando Sistema de Control de Producción Cardinova")
    logger.info(f"Ambiente: {settings.ENVIRONMENT}")
    _load_saved_yolo_runtime_configuration()
    logger.info(f"YOLO cargado: {yolo_service.is_loaded} (Clases: {list(yolo_service.classes.values())})")
    logger.info("==================================================")
    sync_task = asyncio.create_task(_odoo_event_sync_worker())
    camera_task = asyncio.create_task(_camera_health_worker())
    capture_task = asyncio.create_task(_camera_capture_worker())
    yield
    # Shutdown
    for task in (sync_task, camera_task, capture_task):
        task.cancel()
    await asyncio.gather(sync_task, camera_task, return_exceptions=True)
    logger.info("Deteniendo Sistema Cardinova...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description=(
        "API REST modular para el Sistema de Control de Procesos de Producción mediante "
        "Visión Artificial (YOLOv8) e Integración con Odoo ERP para la empresa Cardinova."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)


@app.middleware("http")
async def collect_request_metrics(request: Request, call_next):
    started_at = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response
    finally:
        if request.url.path != f"{settings.API_V1_STR}/health/metrics":
            request_metrics.record(
                request.url.path,
                status_code,
                (time.perf_counter() - started_at) * 1000,
            )

# CORS configuration
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# Exception handler for domain exceptions
@app.exception_handler(CardinovaException)
async def cardinova_exception_handler(request: Request, exc: CardinovaException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# Include API v1 Router
app.include_router(api_router, prefix=settings.API_V1_STR)

WEB_ROOT = Path(__file__).resolve().parent / "web"


@app.get("/")
def root():
    if (WEB_ROOT / "index.html").is_file():
        return FileResponse(WEB_ROOT / "index.html")
    return {
        "system": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "online",
        "documentation": "/docs"
    }


if WEB_ROOT.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def serve_frontend(path: str):
        api_prefix = settings.API_V1_STR.strip("/")
        if path == api_prefix or path.startswith(f"{api_prefix}/"):
            raise HTTPException(status_code=404)

        web_root = WEB_ROOT.resolve()
        requested_file = (web_root / path).resolve()
        try:
            requested_file.relative_to(web_root)
        except ValueError as error:
            raise HTTPException(status_code=404) from error

        if requested_file.is_file():
            return FileResponse(requested_file)
        if Path(path).suffix:
            raise HTTPException(status_code=404)
        return FileResponse(web_root / "index.html")
