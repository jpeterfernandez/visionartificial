import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.logging import logger
from app.core.camera_source import is_network_camera_source
from app.db.session import SessionLocal
from app.repositories.camera_repository import CameraRepository
from app.repositories.setting_repository import SettingRepository
from app.services.camera_monitor import camera_access_lock, is_stream_active
from app.services.detection_service import DetectionService, associate_detections_with_chassis
from app.services.yolo_service import yolo_service
from app.services.vinyl_color_service import classify_vinyl_color


def _count_machines(
    camera_zone: str,
    detections: List[Dict[str, Any]],
    stage_map: Dict[str, str],
    zone_config: Dict[str, Any],
    frame: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Cuenta cuántas máquinas/objetos se detectan en la zona indicada.

    - ALMACÉN: cada detección filtrada es una unidad terminada. Si se pasa
      el frame original, clasifica además el color del vinilo (naranja/azul/rosado).
    - Otras zonas: agrupa componentes alrededor de chasis_base.
    - En ambos casos aplica el filtro allowed/blocked de zone_config.
    """
    zone_cfg = (zone_config.get("zones") or {}).get(camera_zone, {})
    allowed_raw = zone_cfg.get("allowed", [])
    blocked_raw = zone_cfg.get("blocked", [])

    def _norm(name: str) -> str:
        n = name.strip().lower()
        return n[len("chasis_"):] if n.startswith("chasis_") else n

    allowed_norm = {_norm(c) for c in allowed_raw}
    blocked_norm = {_norm(c) for c in blocked_raw}

    def _is_allowed(class_name: str) -> bool:
        n = _norm(class_name)
        if n in blocked_norm:
            return False
        if allowed_norm and n not in allowed_norm:
            return False
        return True

    filtered = [d for d in detections if _is_allowed(d.get("class_name", ""))]

    # ── ALMACÉN: contar por unidades + clasificar color de vinilo ────────────
    if camera_zone == "ALMACEN":
        count = len(filtered)
        color_counts: Dict[str, int] = {}

        if frame is not None and count > 0:
            for det in filtered:
                bbox = det.get("bbox", {})
                box = (
                    bbox.get("x1", 0), bbox.get("y1", 0),
                    bbox.get("x2", 0), bbox.get("y2", 0),
                )
                color = classify_vinyl_color(frame, box)
                if color:
                    color_counts[color] = color_counts.get(color, 0) + 1

        return {
            "machine_count": count,
            "stage_counts": {"ALMACEN": count} if count else {},
            "classification_counts": {},
            "vinyl_color_counts": color_counts,  # {"naranja": 2, "azul": 1, ...}
        }

    # ── Otras zonas: agrupar por chasis_base ─────────────────────────────────
    groups = associate_detections_with_chassis(
        filtered, stage_map, zone_config.get("classification_rules")
    )
    stage_counts: Dict[str, int] = {}
    classification_counts: Dict[str, int] = {}
    for group in groups:
        stage = group.get("stage")
        if stage:
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
        label = group["label"]
        classification_counts[label] = classification_counts.get(label, 0) + 1

    return {
        "machine_count": len(groups),
        "stage_counts": stage_counts,
        "classification_counts": classification_counts,
        "vinyl_color_counts": {},
    }


def _update_camera_status(camera_id: int, is_connected: bool, last_check_at: datetime) -> None:
    """
    Actualiza is_connected y last_check_at en una sesión propia y separada,
    evitando conflictos de StaleDataError con la sesión principal del ciclo.
    """
    db = SessionLocal()
    try:
        repo = CameraRepository(db)
        cam = repo.get_by_id(camera_id)
        if cam is None:
            return
        cam.is_connected = is_connected
        cam.last_check_at = last_check_at
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(f"No se pudo actualizar el estado de la cámara {camera_id}: {exc}")
    finally:
        db.close()


def process_active_camera_captures() -> int:
    if not yolo_service.is_loaded or yolo_service.model is None:
        return 0

    from app.api.v1.endpoints.cameras import open_video_capture

    # Sesión dedicada solo para leer la lista de cámaras y el snapshot.
    # Las actualizaciones de estado de cámara se hacen en sesiones separadas
    # para evitar StaleDataError cuando DetectionService modifica las mismas
    # filas en su propia sesión.
    db = SessionLocal()
    processed = 0
    try:
        repository = CameraRepository(db)
        setting_repository = SettingRepository(db)

        snapshot_setting = setting_repository.get_by_key("CAMERA_PRODUCTION_SNAPSHOT")
        try:
            snapshots = json.loads(snapshot_setting.value) if snapshot_setting else {}
        except json.JSONDecodeError:
            snapshots = {}

        from app.services.zone_config_service import ZoneConfigService
        zone_config = ZoneConfigService(db).get_config()

        # Leer la lista de cámaras y cerrar la sesión de lectura antes de
        # abrir capturas de video (evita mantener la sesión abierta durante
        # operaciones lentas de red/cámara).
        cameras = repository.get_all(only_active=True)
        camera_data = [
            {"id": cam.id, "zone": cam.zone, "source": cam.source,
             "confidence_threshold": cam.confidence_threshold}
            for cam in cameras
            if not is_stream_active(cam.id) and is_network_camera_source(cam.source)
        ]
    finally:
        db.close()

    for cam_info in camera_data:
        camera_id = cam_info["id"]
        camera_zone = cam_info["zone"]
        source_raw = cam_info["source"]
        conf_threshold = cam_info["confidence_threshold"]

        capture = None
        now = datetime.now(timezone.utc)
        try:
            with camera_access_lock(camera_id):
                if is_stream_active(camera_id):
                    continue
                capture = open_video_capture(source_raw)
                try:
                    if not capture.isOpened():
                        _update_camera_status(camera_id, False, now)
                        snapshots[str(camera_id)] = {
                            "zone": camera_zone,
                            "machine_count": 0,
                            "stage_counts": {},
                            "classification_counts": {},
                            "last_updated": now.isoformat(),
                            "warning": "Sin conexión con la cámara.",
                        }
                        continue

                    success, frame = capture.read()
                finally:
                    capture.release()
                    capture = None

            is_connected = bool(success and frame is not None)
            _update_camera_status(camera_id, is_connected, now)

            if not is_connected:
                snapshots[str(camera_id)] = {
                    "zone": camera_zone,
                    "machine_count": 0,
                    "stage_counts": {},
                    "classification_counts": {},
                    "last_updated": now.isoformat(),
                    "warning": "La cámara no entregó una imagen.",
                }
                continue

            # Reutiliza el frame BGR directamente; no hace falta codificarlo
            # a JPEG y volverlo a decodificar para la inferencia periódica.
            db_infer = SessionLocal()
            try:
                detection_service = DetectionService(db_infer)
                result = detection_service.process_image_upload(
                    frame=frame,
                    camera_id=camera_id,
                    conf_threshold=conf_threshold,
                    show_confidence=False,
                    return_annotated=False,
                )
            finally:
                db_infer.close()

            counts = _count_machines(
                camera_zone,
                result["detections"],
                result["stage_map"],
                zone_config,
                frame=frame,          # pasa el frame para análisis de color de vinilo
            )

            snapshots[str(camera_id)] = {
                "zone": camera_zone,
                "machine_count": counts["machine_count"],
                "stage_counts": counts["stage_counts"],
                "classification_counts": counts["classification_counts"],
                "vinyl_color_counts": counts.get("vinyl_color_counts", {}),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "warning": None,
            }
            processed += 1

        except Exception as error:
            logger.warning(f"No se pudo procesar la captura de la cámara {camera_id}: {error}")
            snapshots[str(camera_id)] = {
                "zone": camera_zone,
                "machine_count": 0,
                "stage_counts": {},
                "classification_counts": {},
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "warning": "No se pudo procesar la captura.",
            }
        finally:
            if capture is not None:
                capture.release()

    # Guardar snapshot actualizado en sesión propia
    db_snap = SessionLocal()
    try:
        SettingRepository(db_snap).set_value(
            "CAMERA_PRODUCTION_SNAPSHOT",
            json.dumps(snapshots),
            "Último conteo y estado de captura por cámara.",
        )
    finally:
        db_snap.close()

    return processed
