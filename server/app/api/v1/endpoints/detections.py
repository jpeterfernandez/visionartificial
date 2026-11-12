from typing import List, Optional
from datetime import datetime, timedelta, timezone
import csv
import io
from fastapi import APIRouter, Depends, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from PIL import Image, UnidentifiedImageError

from app.db.session import get_db
from app.db.models.user import User
from app.api.dependencies import get_current_user, require_role
from app.schemas.detection import DetectionImageResponse, DetectionResponse
from app.services.detection_service import DetectionService
from app.repositories.detection_repository import DetectionRepository
from app.repositories.camera_repository import CameraRepository
from app.core.exceptions import BadRequestException, NotFoundException, ForbiddenException
from app.core.zones import allowed_zones_for_user, user_can_access_zone

router = APIRouter(prefix="/detections", tags=["Detecciones e Inferencia"])


@router.get("/export.csv")
def export_detections_csv(
    camera_id: Optional[int] = None,
    class_name: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if date_from and date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    if date_from and date_to and (date_to < date_from or date_to - date_from > timedelta(days=90)):
        raise BadRequestException("El rango debe ser válido y no superar 90 días")
    zones = allowed_zones_for_user(current_user)
    if camera_id is not None:
        camera = CameraRepository(db).get_by_id(camera_id)
        if not camera:
            raise NotFoundException(f"Cámara #{camera_id} no encontrada")
        if not user_can_access_zone(current_user, camera.zone):
            raise ForbiddenException("No tiene acceso a la zona de esta cámara")
    detections = DetectionRepository(db).get_all(
        limit=10001,
        camera_id=camera_id,
        class_name=class_name,
        date_from=date_from,
        date_to=date_to,
        camera_zones=list(zones) if zones is not None else None,
    )
    if len(detections) > 10000:
        raise BadRequestException("Aplique filtros para exportar un máximo de 10.000 detecciones")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "fecha_utc", "zona", "camara_id", "clase", "confianza", "x1", "y1", "x2", "y2", "inferencia_ms"])
    writer.writerows([
        [item.id, item.created_at.isoformat(), item.zone, item.camera_id, item.class_name,
         item.confidence, item.bbox_x1, item.bbox_y1, item.bbox_x2, item.bbox_y2, item.inference_time_ms]
        for item in detections
    ])
    return StreamingResponse(
        iter(["\ufeff" + output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=detecciones.csv"},
    )


@router.post("/image", response_model=DetectionImageResponse)
async def detect_image(
    file: UploadFile = File(...),
    camera_id: Optional[int] = Form(None),
    conf_threshold: Optional[float] = Form(None),
    show_confidence: bool = Form(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    if camera_id is None and current_user.role.upper() != "ADMIN":
        raise ForbiddenException("Seleccione una cámara de su zona para registrar la inferencia")
    if camera_id is not None:
        camera = CameraRepository(db).get_by_id(camera_id)
        if not camera:
            raise NotFoundException(f"Cámara #{camera_id} no encontrada")
        if not user_can_access_zone(current_user, camera.zone):
            raise ForbiddenException("No tiene permiso para procesar imágenes de esta zona")
    max_bytes = 15 * 1024 * 1024
    content_parts = []
    total_bytes = 0
    while chunk := await file.read(1024 * 1024):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise BadRequestException("La imagen excede el límite máximo permitido de 15MB")
        content_parts.append(chunk)
    content = b"".join(content_parts)

    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise BadRequestException("Formato de imagen no admitido; use JPEG, PNG o WEBP")
            if image.width * image.height > 40_000_000:
                raise BadRequestException("La imagen supera el máximo de 40 megapíxeles")
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise BadRequestException("El archivo no contiene una imagen válida") from error

    service = DetectionService(db)
    result = service.process_image_upload(
        image_bytes=content,
        camera_id=camera_id,
        conf_threshold=conf_threshold,
        show_confidence=show_confidence
    )
    return result


@router.get("", response_model=List[DetectionResponse])
def get_detections(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    camera_id: Optional[int] = None,
    class_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    repo = DetectionRepository(db)
    zones = allowed_zones_for_user(current_user)
    if camera_id is not None:
        camera = CameraRepository(db).get_by_id(camera_id)
        if not camera:
            raise NotFoundException(f"Cámara #{camera_id} no encontrada")
        if not user_can_access_zone(current_user, camera.zone):
            raise ForbiddenException("No tiene acceso a la zona de esta cámara")
    return repo.get_all(
        skip=skip,
        limit=limit,
        camera_id=camera_id,
        class_name=class_name,
        camera_zones=list(zones) if zones is not None else None,
    )


@router.get("/{detection_id}", response_model=DetectionResponse)
def get_detection(
    detection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    repo = DetectionRepository(db)
    det = repo.get_by_id(detection_id)
    if not det:
        raise NotFoundException(f"Detección #{detection_id} no encontrada")
    if not user_can_access_zone(current_user, det.zone):
        raise ForbiddenException("No tiene acceso a la zona de esta detección")
    return det
