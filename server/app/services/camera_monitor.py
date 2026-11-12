import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Callable, Optional

import cv2
from sqlalchemy.orm import Session

from app.repositories.camera_repository import CameraRepository
from app.core.camera_source import is_network_camera_source


_stream_counts: Counter[int] = Counter()
_stream_lock = threading.Lock()
_camera_access_locks: dict[int, threading.Lock] = {}
_camera_access_locks_guard = threading.Lock()


def camera_access_lock(camera_id: int) -> threading.Lock:
    with _camera_access_locks_guard:
        lock = _camera_access_locks.get(camera_id)
        if lock is None:
            lock = threading.Lock()
            _camera_access_locks[camera_id] = lock
        return lock


def mark_stream_started(camera_id: int) -> None:
    with _stream_lock:
        _stream_counts[camera_id] += 1


def mark_stream_stopped(camera_id: int) -> None:
    with _stream_lock:
        if _stream_counts[camera_id] <= 1:
            _stream_counts.pop(camera_id, None)
        else:
            _stream_counts[camera_id] -= 1


def is_stream_active(camera_id: int) -> bool:
    with _stream_lock:
        return _stream_counts[camera_id] > 0


def _open_capture(source: str):
    if not is_network_camera_source(source):
        raise ValueError("La cámara debe usar una fuente de red RTSP, RTSPS, HTTP o HTTPS.")
    return cv2.VideoCapture(source)


def check_camera_connections(
    db: Session,
    capture_factory: Optional[Callable[[str], object]] = None,
) -> int:
    """
    Verifica el estado de conexión de cada cámara activa.
    Omite cámaras que ya tienen un stream activo O que están siendo procesadas
    por el ciclo de captura periódica (is_stream_active cubre ambos casos
    porque camera_capture también marca el stream mientras procesa).
    Si no puede abrir la cámara respeta el estado anterior en lugar de
    escribir False, para no causar el parpadeo "sin señal" momentáneo.
    """
    repository = CameraRepository(db)
    checked = 0
    for camera in repository.get_all(only_active=True):
        if is_stream_active(camera.id):
            continue
        if not is_network_camera_source(camera.source):
            continue
        capture = None
        try:
            with camera_access_lock(camera.id):
                if is_stream_active(camera.id):
                    continue
                capture = (capture_factory or _open_capture)(camera.source)
                try:
                    if not capture.isOpened():
                        # No pudo abrir: solo actualiza si antes estaba conectada
                        # para no invertir un estado correcto con un fallo transitorio.
                        if camera.is_connected:
                            camera.is_connected = False
                            camera.last_check_at = datetime.now(timezone.utc)
                            repository.update(camera)
                        continue

                    success, _frame = capture.read()
                finally:
                    capture.release()
                    capture = None
            is_connected = bool(success)

            # Solo escribir en DB si el estado cambia, para reducir escrituras
            if camera.is_connected != is_connected:
                camera.is_connected = is_connected
                camera.last_check_at = datetime.now(timezone.utc)
                repository.update(camera)
            elif not is_connected:
                # Actualizar timestamp aunque el estado no cambie (sigue sin señal)
                camera.last_check_at = datetime.now(timezone.utc)
                repository.update(camera)

        except Exception:
            pass  # fallo transitorio; no cambiar el estado guardado
        finally:
            if capture is not None:
                capture.release()
        checked += 1
    return checked
