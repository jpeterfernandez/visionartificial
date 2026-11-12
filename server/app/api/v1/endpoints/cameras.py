from typing import List, Optional
from datetime import datetime, timedelta, timezone
import os
import time
import threading
from queue import Empty, Full, Queue
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import jwt
import cv2
import numpy as np

from app.db.session import get_db
from app.db.session import SessionLocal
from app.db.models.user import User
from app.db.models.camera import Camera
from app.api.dependencies import get_current_user, require_role
from app.core.config import (
    MAX_YOLO_STREAM_INTERVAL_MS,
    MIN_YOLO_STREAM_INTERVAL_MS,
    settings,
)
from app.core.logging import logger
from app.core.camera_source import is_network_camera_source
from app.schemas.camera import CameraResponse, CameraCreate, CameraUpdate
from app.repositories.camera_repository import CameraRepository
from app.repositories.user_repository import UserRepository
from app.repositories.audit_repository import record_audit
from app.core.exceptions import NotFoundException, UnauthorizedException, ForbiddenException
from app.core.security import decode_access_token
from app.core.zones import allowed_zones_for_user, user_can_access_zone
from app.services.yolo_service import yolo_service
from app.services.camera_monitor import (
    camera_access_lock,
    is_stream_active,
    mark_stream_started,
    mark_stream_stopped,
)

router = APIRouter(prefix="/cameras", tags=["Cámaras y Zonas de Producción"])
_camera_stream_sessions: dict[int, "SharedCameraStream"] = {}
_camera_stream_sessions_lock = threading.RLock()


def _load_snapshots(db: Session) -> dict:
    """Carga el snapshot de conteo de cámaras desde system_settings."""
    from app.repositories.setting_repository import SettingRepository
    import json as _json
    setting = SettingRepository(db).get_by_key("CAMERA_PRODUCTION_SNAPSHOT")
    if not setting:
        return {}
    try:
        return _json.loads(setting.value)
    except Exception:
        return {}


def _enrich_camera_response(response: CameraResponse, snapshots: dict) -> CameraResponse:
    """Añade los conteos de máquina y última captura desde el snapshot."""
    snap = snapshots.get(str(response.id))
    if snap:
        response.machine_count = int(snap.get("machine_count", 0))
        response.classification_counts = snap.get("classification_counts") or {}
        response.vinyl_color_counts = snap.get("vinyl_color_counts") or {}
        raw_ts = snap.get("last_updated")
        if raw_ts:
            from datetime import datetime, timezone
            try:
                ts = datetime.fromisoformat(raw_ts)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                response.last_snapshot_at = ts
            except ValueError:
                pass
    return response


def camera_response_for_user(camera: Camera, user: User, snapshots: dict | None = None) -> CameraResponse:
    response = CameraResponse.model_validate(camera)
    if user.role.upper() != "ADMIN":
        response.source = "Fuente protegida"
    if snapshots is not None:
        _enrich_camera_response(response, snapshots)
    return response


class LatestFrameReader:
    """Reads camera frames in the background and keeps only the newest one."""

    def __init__(self, cap: cv2.VideoCapture, first_frame):
        self.cap = cap
        self.frames: Queue = Queue(maxsize=1)
        self.stop_event = threading.Event()
        self.finished_event = threading.Event()
        self.thread = threading.Thread(target=self._capture_frames, daemon=True)
        self._publish(first_frame)

    @property
    def finished(self) -> bool:
        return self.finished_event.is_set()

    def _publish(self, frame) -> None:
        try:
            self.frames.put_nowait(frame)
        except Full:
            try:
                self.frames.get_nowait()
            except Empty:
                pass
            try:
                self.frames.put_nowait(frame)
            except Full:
                pass

    def _capture_frames(self) -> None:
        consecutive_failures = 0
        try:
            while not self.stop_event.is_set():
                success, frame = self.cap.read()
                if success:
                    consecutive_failures = 0
                    self._publish(frame)
                    continue

                consecutive_failures += 1
                if consecutive_failures >= 10:
                    break
                self.stop_event.wait(0.1)
        finally:
            self.finished_event.set()
            self.cap.release()

    def start(self) -> None:
        self.thread.start()

    def read(self, timeout: float = 0.5):
        try:
            return self.frames.get(timeout=timeout)
        except Empty:
            return None

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            self.cap.release()


def open_video_capture(source_val):
    source = str(source_val)
    if not is_network_camera_source(source):
        raise ValueError("La cámara debe usar una fuente de red RTSP, RTSPS, HTTP o HTTPS.")
    if source.lower().startswith(("rtsp://", "rtsps://")):
        # Configurar FFmpeg para RTSP en TCP por defecto para evitar paquetes perdidos por UDP
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|analyzeduration;1000000|probesize;1000000|stimeout;5000000"
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(source)
    else:
        cap = cv2.VideoCapture(source)

    if cap.isOpened():
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


@router.get("", response_model=List[CameraResponse])
def get_cameras(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    repo = CameraRepository(db)
    cameras = repo.get_all()
    zones = allowed_zones_for_user(current_user)
    if zones is not None:
        cameras = [camera for camera in cameras if camera.zone in zones]
    snapshots = _load_snapshots(db)
    return [camera_response_for_user(camera, current_user, snapshots) for camera in cameras]


@router.post("", response_model=CameraResponse)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    """Permite registrar nuevas cámaras (cámaras USB locales, cámaras IP/celular o RTSP)."""
    repo = CameraRepository(db)
    camera = Camera(
        name=payload.name,
        zone=payload.zone,
        source=payload.source,
        confidence_threshold=payload.confidence_threshold,
        is_active=payload.is_active,
        is_connected=False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(camera)
    db.flush()
    record_audit(db, current_user, "camera.created", "camera", str(camera.id), {"name": camera.name, "zone": camera.zone})
    created = repo.create(camera)
    return camera_response_for_user(created, current_user)


@router.get("/{camera_id}", response_model=CameraResponse)
def get_camera(
    camera_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    repo = CameraRepository(db)
    cam = repo.get_by_id(camera_id)
    if not cam:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")
    if not user_can_access_zone(current_user, cam.zone):
        raise ForbiddenException("No tiene acceso a la zona de esta cámara")
    snapshots = _load_snapshots(db)
    return camera_response_for_user(cam, current_user, snapshots)


@router.put("/{camera_id}", response_model=CameraResponse)
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    repo = CameraRepository(db)
    cam = repo.get_by_id(camera_id)
    if not cam:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")

    if payload.name is not None:
        cam.name = payload.name
    if payload.zone is not None:
        cam.zone = payload.zone
    if payload.source is not None:
        cam.source = payload.source
    if payload.is_active is not None:
        cam.is_active = payload.is_active
    if payload.confidence_threshold is not None:
        cam.confidence_threshold = payload.confidence_threshold
    if payload.is_connected is not None:
        cam.is_connected = payload.is_connected

    cam.updated_at = datetime.now(timezone.utc)
    record_audit(
        db,
        current_user,
        "camera.updated",
        "camera",
        str(cam.id),
        {"changed_fields": sorted(payload.model_dump(exclude_unset=True).keys())},
    )
    return camera_response_for_user(repo.update(cam), current_user)


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN"))
):
    repo = CameraRepository(db)
    cam = repo.get_by_id(camera_id)
    if not cam:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")
    record_audit(db, current_user, "camera.deleted", "camera", str(cam.id), {"name": cam.name})
    repo.delete(cam)
    return {"message": f"Cámara #{camera_id} eliminada correctamente"}


@router.post("/{camera_id}/test", response_model=CameraResponse)
def test_camera_connection(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("OPERATOR"))
):
    """Safely attempts to probe the camera source without keeping the capture stream open."""
    repo = CameraRepository(db)
    cam = repo.get_by_id(camera_id)
    if not cam:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")
    if not user_can_access_zone(current_user, cam.zone):
        raise ForbiddenException("No tiene permiso para probar cámaras de esta zona")

    source_val = cam.source
    is_ok = False
    cap = None
    try:
        if is_stream_active(cam.id):
            is_ok = cam.is_connected
        else:
            with camera_access_lock(cam.id):
                if is_stream_active(cam.id):
                    is_ok = cam.is_connected
                else:
                    cap = open_video_capture(source_val)
                    try:
                        if cap.isOpened():
                            ret, _ = cap.read()
                            is_ok = bool(ret)
                    finally:
                        cap.release()
                        cap = None
    except Exception:
        is_ok = False
    finally:
        if cap is not None:
            cap.release()

    cam.is_connected = is_ok
    cam.last_check_at = datetime.now(timezone.utc)
    return camera_response_for_user(repo.update(cam), current_user)


@router.post("/{camera_id}/stream-ticket", deprecated=True)
def create_camera_stream_ticket(
    camera_id: int = Path(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    camera = CameraRepository(db).get_by_id(camera_id)
    if not camera:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")
    if not user_can_access_zone(current_user, camera.zone):
        raise ForbiddenException("No tiene acceso a la zona de esta cámara")
    if not camera.is_active:
        raise HTTPException(status_code=409, detail="La cámara está desactivada")

    now = datetime.now(timezone.utc)
    ticket = jwt.encode(
        {
            "sub": current_user.username,
            "purpose": "camera_stream",
            "camera_id": camera_id,
            "iat": now,
            "exp": now + timedelta(minutes=2),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return {"ticket": ticket}


class InferenceOverlayThread:
    """
    Runs YOLO in the background and exposes its latest result without blocking
    frame delivery.
    """

    def __init__(self, conf_threshold: float, show_confidence: bool):
        self.conf_threshold = conf_threshold
        self.show_confidence = show_confidence
        self._lock = threading.Lock()
        self._latest_boxes: list = []   # (x1, y1, x2, y2, class_name, confidence)
        self._frame_queue: Queue = Queue(maxsize=1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def submit_frame(self, frame) -> None:
        """Envía un frame para inferencia; descarta el anterior si YOLO no llegó a procesarlo."""
        try:
            self._frame_queue.put_nowait(frame)
        except Full:
            try:
                self._frame_queue.get_nowait()
            except Empty:
                pass
            try:
                self._frame_queue.put_nowait(frame)
            except Full:
                pass

    @property
    def latest_boxes(self) -> list:
        with self._lock:
            return list(self._latest_boxes)

    def _run(self) -> None:
        last_inference_at = 0.0
        while not self._stop.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.5)
            except Empty:
                continue

            now = time.monotonic()
            min_interval = max(
                MIN_YOLO_STREAM_INTERVAL_MS,
                min(MAX_YOLO_STREAM_INTERVAL_MS, yolo_service.stream_interval_ms),
            ) / 1000.0
            if now - last_inference_at < min_interval:
                continue
            last_inference_at = now

            if not yolo_service.is_loaded or yolo_service.model is None:
                continue

            try:
                results = yolo_service.predict_frame(
                    frame=frame,
                    img_size=yolo_service.stream_img_size,
                    conf_threshold=self.conf_threshold,
                    iou_threshold=settings.YOLO_IOU_THRESHOLD,
                )
                boxes = []
                if len(results) > 0 and results[0].boxes is not None:
                    for box in results[0].boxes:
                        conf = float(box.conf[0])
                        if conf < self.conf_threshold:
                            continue
                        cls_id = int(box.cls[0])
                        cls_name = yolo_service.classes.get(cls_id, f"clase_{cls_id}").replace("chasis_", "")
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        boxes.append((x1, y1, x2, y2, cls_name, conf))
                with self._lock:
                    self._latest_boxes = boxes
            except Exception as error:
                logger.warning("Falló la inferencia de video de cámara: %s", error)


class SharedCameraStream:
    """Shares one physical capture and one inference worker between viewers."""

    def __init__(self, camera_id: int, source: str, cap, first_frame, conf_threshold: float):
        self.camera_id = camera_id
        self.source = source
        self.cap = cap
        self.condition = threading.Condition()
        self.latest_frame = first_frame.copy()
        self.frame_id = 1
        self.stop_event = threading.Event()
        self.finished_event = threading.Event()
        self.client_count = 1
        self._encoded_frame_lock = threading.Lock()
        self._encoded_frames: dict[tuple[int, bool], bytes] = {}
        self.overlay = InferenceOverlayThread(conf_threshold, show_confidence=True)
        self.overlay.submit_frame(self.latest_frame.copy())
        self.overlay.start()
        self.thread = threading.Thread(
            target=self._capture_frames,
            name=f"camera-stream-{camera_id}",
            daemon=True,
        )
        self.thread.start()

    @property
    def finished(self) -> bool:
        return self.finished_event.is_set()

    def _capture_frames(self) -> None:
        consecutive_failures = 0
        last_inference_submission_at = 0.0
        try:
            while not self.stop_event.is_set():
                success, frame = self.cap.read()
                if success and frame is not None:
                    consecutive_failures = 0
                    with self.condition:
                        self.latest_frame = frame
                        self.frame_id += 1
                        self.condition.notify_all()
                    now = time.monotonic()
                    interval = max(
                        MIN_YOLO_STREAM_INTERVAL_MS,
                        min(MAX_YOLO_STREAM_INTERVAL_MS, yolo_service.stream_interval_ms),
                    ) / 1000.0
                    if now - last_inference_submission_at >= interval:
                        self.overlay.submit_frame(frame.copy())
                        last_inference_submission_at = now
                    continue

                consecutive_failures += 1
                if consecutive_failures >= 10:
                    break
                self.stop_event.wait(0.1)
        finally:
            self.cap.release()
            self.finished_event.set()
            with self.condition:
                self.condition.notify_all()

    def read_new_frame(self, after_frame_id: int, timeout: float = 0.5):
        with self.condition:
            self.condition.wait_for(
                lambda: self.frame_id > after_frame_id or self.finished,
                timeout=timeout,
            )
            if self.frame_id <= after_frame_id:
                return None
            return self.frame_id, self.latest_frame.copy()

    def encode_frame(self, frame_id: int, frame, show_confidence: bool, fps: float) -> Optional[bytes]:
        cache_key = (frame_id, show_confidence)
        with self._encoded_frame_lock:
            cached = self._encoded_frames.get(cache_key)
            if cached is not None:
                return cached

            rendered = frame.copy()
            _draw_boxes(rendered, self.overlay.latest_boxes, show_confidence)
            height, width = rendered.shape[:2]
            if width > 960:
                resized_height = max(1, round(height * 960 / width))
                rendered = cv2.resize(
                    rendered,
                    (960, resized_height),
                    interpolation=cv2.INTER_AREA,
                )
            cv2.putText(
                rendered,
                f"Cardinova AI  FPS: {fps:.1f}",
                (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
            )
            ret, buffer = cv2.imencode(
                ".jpg",
                rendered,
                [cv2.IMWRITE_JPEG_QUALITY, 65],
            )
            if not ret:
                return None

            encoded = buffer.tobytes()
            self._encoded_frames[cache_key] = encoded
            for old_key in list(self._encoded_frames):
                if old_key[0] < frame_id - 1:
                    del self._encoded_frames[old_key]
            return encoded

    def stop(self) -> None:
        self.stop_event.set()
        self.cap.release()
        self.thread.join(timeout=2)
        self.overlay.stop()


def acquire_camera_stream(camera_id: int, source: str, conf_threshold: float) -> SharedCameraStream:
    with _camera_stream_sessions_lock:
        existing = _camera_stream_sessions.get(camera_id)
        if existing and not existing.finished:
            if existing.source != source:
                raise HTTPException(
                    status_code=409,
                    detail="La fuente de esta cámara cambió. Cierra las transmisiones existentes e inténtalo de nuevo.",
                )
            existing.client_count += 1
            return existing
        if existing:
            existing.stop()
            _camera_stream_sessions.pop(camera_id, None)

        cap = None
        try:
            with camera_access_lock(camera_id):
                cap = open_video_capture(source)
                if not cap.isOpened():
                    raise HTTPException(
                        status_code=503,
                        detail="No se pudo abrir la fuente de video de la cámara",
                    )

                success, first_frame = cap.read()
                if not success or first_frame is None:
                    raise HTTPException(
                        status_code=503,
                        detail="La cámara no está entregando video",
                    )

            session = SharedCameraStream(camera_id, source, cap, first_frame, conf_threshold)
            _camera_stream_sessions[camera_id] = session
            return session
        except HTTPException:
            if cap is not None:
                cap.release()
            raise
        except Exception as exc:
            if cap is not None:
                cap.release()
            raise HTTPException(
                status_code=503,
                detail=f"Error inesperado al conectar con el dispositivo de video: {str(exc)}",
            ) from exc


def release_camera_stream(camera_id: int, session: SharedCameraStream) -> None:
    should_stop = False
    with _camera_stream_sessions_lock:
        session.client_count = max(0, session.client_count - 1)
        if session.client_count == 0:
            if _camera_stream_sessions.get(camera_id) is session:
                _camera_stream_sessions.pop(camera_id, None)
            should_stop = True
            session.stop()
    mark_stream_stopped(camera_id)


def _draw_boxes(frame, boxes: list, show_confidence: bool = True) -> None:
    """Dibuja las cajas de detección sobre el frame (in-place)."""
    for x1, y1, x2, y2, class_name, confidence in boxes:
        label = f"{class_name} {confidence * 100:.1f}%" if show_confidence else class_name
        cv2.rectangle(frame, (x1, y1), (x2, y2), (16, 185, 129), 2)
        (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(
            frame,
            (x1, max(0, y1 - th - baseline - 8)),
            (x1 + tw + 8, y1),
            (16, 185, 129),
            -1,
        )
        cv2.putText(
            frame, label, (x1 + 4, max(th + 2, y1 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA,
        )


def generate_live_mjpeg_stream(
    session: SharedCameraStream,
    show_confidence: bool = True,
    camera_id: Optional[int] = None,
):
    """
    Generador de frames MJPEG con inferencia YOLO desacoplada.

    All viewers reuse the same capture thread and the same inference result.
    """
    frame_id = 0
    next_frame_at = 0.0
    source_failed = False
    try:
        while True:
            interval_ms = max(
                MIN_YOLO_STREAM_INTERVAL_MS,
                min(MAX_YOLO_STREAM_INTERVAL_MS, yolo_service.stream_interval_ms),
            )
            interval = interval_ms / 1000.0
            wait_seconds = next_frame_at - time.monotonic()
            if wait_seconds > 0:
                session.stop_event.wait(wait_seconds)
            if session.stop_event.is_set():
                break

            frame_packet = session.read_new_frame(frame_id)
            if frame_packet is None:
                if session.finished:
                    source_failed = True
                    break
                continue

            frame_id, frame = frame_packet
            fps = 1000.0 / interval_ms
            encoded = session.encode_frame(frame_id, frame, show_confidence, fps)
            frame = None
            if encoded is None:
                continue

            next_frame_at = time.monotonic() + interval
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + encoded + b"\r\n")
    finally:
        if camera_id is not None:
            release_camera_stream(camera_id, session)
        if source_failed and camera_id is not None:
            db = SessionLocal()
            try:
                camera = CameraRepository(db).get_by_id(camera_id)
                if camera:
                    camera.is_connected = False
                    camera.last_check_at = datetime.now(timezone.utc)
                    CameraRepository(db).update(camera)
            finally:
                db.close()


@router.get("/{camera_id}/stream", deprecated=True)
def stream_camera(
    camera_id: int = Path(...),
    ticket: Optional[str] = Query(None),
    show_confidence: bool = Query(True),
    db: Session = Depends(get_db)
):
    """
    Transmisión en tiempo real MJPEG con inferencia YOLO en vivo para visualización web.
    Permite visualizar directamente en el frontend usando una etiqueta <img src="/stream" />.
    """
    payload = decode_access_token(ticket) if ticket else None
    if (
        not payload
        or payload.get("purpose") != "camera_stream"
        or payload.get("camera_id") != camera_id
    ):
        raise UnauthorizedException("Ticket de video no válido o expirado")

    username = payload.get("sub")
    user = UserRepository(db).get_by_username(username) if username else None
    if not user or not user.is_active:
        raise UnauthorizedException("Usuario no autorizado para ver este video")
    
    repo = CameraRepository(db)
    cam = repo.get_by_id(camera_id)
    if not cam:
        raise NotFoundException(f"Cámara #{camera_id} no encontrada")
    if not user_can_access_zone(user, cam.zone):
        raise ForbiddenException("El permiso de zona fue revocado")

    source_val = cam.source
    session = None
    mark_stream_started(camera_id)
    try:
        session = acquire_camera_stream(camera_id, source_val, cam.confidence_threshold)
        cam.is_connected = True
        cam.last_check_at = datetime.now(timezone.utc)
        repo.update(cam)
    except Exception:
        if session is not None:
            release_camera_stream(camera_id, session)
        else:
            mark_stream_stopped(camera_id)
        raise
    return StreamingResponse(
        generate_live_mjpeg_stream(session, show_confidence, camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
