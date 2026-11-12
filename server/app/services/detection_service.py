import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from numpy import ndarray
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import logger
from app.services.yolo_service import yolo_service
from app.services.zone_config_service import ZoneConfigService, DEFAULT_CLASSIFICATION_RULES
from app.repositories.detection_repository import DetectionRepository
from app.repositories.event_repository import EventRepository
from app.repositories.camera_repository import CameraRepository
from app.repositories.setting_repository import SettingRepository
from app.db.models.detection import Detection
from app.db.models.production_event import ProductionEvent


STAGE_ORDER = {
    "DOBLADO": 1,
    "ARMADO_ESTRUCTURAL": 2,
    "VINILADO": 3,
    "ALMACEN": 4,
}

STAGE_LABELS = {
    "DOBLADO": "Chasis doblado",
    "ARMADO_ESTRUCTURAL": "Chasis estructurado",
    "VINILADO": "Chasis vinilado",
    "ALMACEN": "Chasis terminado",
}


def associate_detections_with_chassis(
    detections: List[Dict[str, Any]],
    class_stage_map: Dict[str, str],
    classification_rules: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    rules = DEFAULT_CLASSIFICATION_RULES if classification_rules is None else classification_rules
    configured_anchors = {rule.get("anchor_class") for rule in rules}
    anchors = [
        detection for detection in detections
        if (
            str(detection.get("class_name", "")).startswith("chasis_")
            or detection.get("class_name") in configured_anchors
        )
    ]
    anchor_ids = {id(detection) for detection in anchors}
    groups = [
        {
            "anchor_class": detection["class_name"],
            "classes": {detection["class_name"]},
            "stages": [class_stage_map.get(detection["class_name"])],
        }
        for detection in anchors
    ]

    for detection in detections:
        if id(detection) in anchor_ids:
            continue

        bbox = detection.get("bbox", {})
        center_x = (bbox.get("x1", 0) + bbox.get("x2", 0)) / 2
        center_y = (bbox.get("y1", 0) + bbox.get("y2", 0)) / 2
        candidates = []
        for index, base in enumerate(anchors):
            base_bbox = base.get("bbox", {})
            if (
                base_bbox.get("x1", 0) <= center_x <= base_bbox.get("x2", 0)
                and base_bbox.get("y1", 0) <= center_y <= base_bbox.get("y2", 0)
            ):
                area = max(0, base_bbox.get("x2", 0) - base_bbox.get("x1", 0)) * max(
                    0, base_bbox.get("y2", 0) - base_bbox.get("y1", 0)
                )
                candidates.append((area, index))

        if candidates:
            _, group_index = min(candidates)
            groups[group_index]["classes"].add(detection["class_name"])
            groups[group_index]["stages"].append(class_stage_map.get(detection["class_name"]))

    associated = []
    for group in groups:
        matched_rule = next(
            (
                rule for rule in rules
                if rule.get("anchor_class") == group["anchor_class"]
                and set(rule.get("required_classes") or []).issubset(group["classes"])
                and (
                    not rule.get("one_of_classes")
                    or bool(set(rule["one_of_classes"]) & group["classes"])
                )
            ),
            None,
        )
        anchor_has_rules = any(
            rule.get("anchor_class") == group["anchor_class"] for rule in rules
        )
        stages = [stage for stage in group["stages"] if stage in STAGE_ORDER]
        if matched_rule:
            stage = matched_rule["stage"]
        elif anchor_has_rules:
            component_stages = [
                class_stage_map.get(class_name)
                for class_name in group["classes"]
                if class_name != group["anchor_class"]
                and class_stage_map.get(class_name) in STAGE_ORDER
            ]
            stage = max(component_stages, key=STAGE_ORDER.get) if component_stages else None
        else:
            stage = max(stages, key=STAGE_ORDER.get) if stages else None
        representative_class = group["anchor_class"]
        if not matched_rule and stage:
            representative_class = next(
                (
                    class_name for class_name in sorted(group["classes"])
                    if class_stage_map.get(class_name) == stage
                ),
                group["anchor_class"],
            )
        associated.append({
            "stage": stage,
            "label": (
                matched_rule["name"] if matched_rule
                else "Chasis sin clasificar" if anchor_has_rules and stage is None
                else STAGE_LABELS.get(stage or "", "No identificado")
            ),
            "anchor_class": group["anchor_class"],
            "representative_class": representative_class,
            "classes": sorted(group["classes"]),
        })
    return associated


class DetectionService:
    def __init__(self, db: Session):
        self.db = db
        self.detection_repo = DetectionRepository(db)
        self.event_repo = EventRepository(db)
        self.camera_repo = CameraRepository(db)
        self.setting_repo = SettingRepository(db)

    def get_class_stage_map(self) -> Dict[str, str]:
        """Mapeo conservador de clases YOLO a la línea productiva actual."""
        default_map = {
            "chasis_base": "DOBLADO",
            "chasis_vinilado": "VINILADO",
            "cavidad_hueca": "DOBLADO",
            "puerta_sup_panel": "ARMADO_ESTRUCTURAL",
            "puerta_sup_chapa": "ARMADO_ESTRUCTURAL",
            "puerta_inferior": "ARMADO_ESTRUCTURAL",
            "vinilo_frontal": "VINILADO",
            "vinilo_lateral": "VINILADO",
        }
        setting = self.setting_repo.get_by_key("class_stage_mapping")
        if setting:
            try:
                parsed = json.loads(setting.value)
                if isinstance(parsed, dict) and parsed:
                    return {str(k): str(v) for k, v in parsed.items()}
            except Exception:
                pass
        return default_map

    def process_image_upload(
        self,
        image_bytes: Optional[bytes] = None,
        camera_id: Optional[int] = None,
        conf_threshold: Optional[float] = None,
        show_confidence: bool = True,
        return_annotated: bool = True,
        frame: Optional[ndarray] = None,
    ) -> Dict[str, Any]:
        """
        Detects an encoded image or BGR frame, saves detections, and applies
        temporal confirmation logic if a camera is assigned.
        """
        if (image_bytes is None) == (frame is None):
            raise ValueError("Proporcione exactamente una imagen codificada o un frame BGR.")

        camera = None
        if camera_id:
            camera = self.camera_repo.get_by_id(camera_id)
            if camera and conf_threshold is None:
                conf_threshold = camera.confidence_threshold

        # Run inference
        result = yolo_service.predict_image(
            image_bytes=image_bytes,
            conf_threshold=conf_threshold,
            show_confidence=show_confidence,
            return_annotated=return_annotated,
            frame=frame,
        )

        class_stage_map = self.get_class_stage_map()
        classification_rules = ZoneConfigService(self.db).get_config()["classification_rules"]
        chassis_groups = associate_detections_with_chassis(
            result["detections"], class_stage_map, classification_rules
        )
        result["classifications"] = chassis_groups
        saved_detections = []
        now = datetime.now(timezone.utc)

        # Update camera status if camera_id is provided
        if camera:
            camera.last_check_at = now
            if result["total_detections"] > 0:
                camera.last_detection_at = now
            self.camera_repo.update(camera)

        # ALMACEN is a live stock count, not a production-event history.
        if not camera or camera.zone != "ALMACEN":
            for det in result["detections"]:
                stage = class_stage_map.get(det["class_name"], "NO_IDENTIFICADO")
                det["stage_name"] = stage

                db_det = Detection(
                    camera_id=camera_id,
                    zone=camera.zone if camera else None,
                    class_name=det["class_name"],
                    confidence=det["confidence"],
                    bbox_x1=det["bbox"]["x1"],
                    bbox_y1=det["bbox"]["y1"],
                    bbox_x2=det["bbox"]["x2"],
                    bbox_y2=det["bbox"]["y2"],
                    inference_time_ms=result["inference_time_ms"],
                    image_path=None,
                    created_at=now
                )
                saved_det = self.detection_repo.create(db_det)
                saved_detections.append(saved_det)

        # Evaluate confirmation & event generation if camera is known and detections found
        created_event = None
        if camera and camera.zone != "ALMACEN" and result["total_detections"] > 0:
            created_event = self._evaluate_and_create_event(
                camera=camera,
                detections=result["detections"],
                class_stage_map=class_stage_map,
                classification_rules=classification_rules,
                now=now
            )

        result["saved_detections_count"] = len(saved_detections)
        result["confirmed_event_id"] = created_event.id if created_event else None
        result["stage_map"] = class_stage_map

        return result

    def _evaluate_and_create_event(
        self,
        camera: Any,
        detections: List[Dict[str, Any]],
        class_stage_map: Dict[str, str],
        now: datetime,
        classification_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[ProductionEvent]:
        """
        Regla conservadora: solo se confirma una etapa si existe evidencia clara de una clase de esa zona.
        Se evita contar la misma pieza varias veces y no se avanza sin evidencia suficiente.
        """
        if camera.zone == "ALMACEN":
            return None

        chassis_groups = associate_detections_with_chassis(
            detections, class_stage_map, classification_rules
        )
        if not chassis_groups:
            logger.info(f"Cámara {camera.id}: no se detectó un chasis base para asociar componentes.")
            return None

        stage_counts: Dict[str, int] = {}
        for group in chassis_groups:
            if group["stage"]:
                stage_counts[group["stage"]] = stage_counts.get(group["stage"], 0) + 1
        if camera.zone == "ALMACEN":
            stage_counts = {"ALMACEN": len(chassis_groups)}
        if not stage_counts:
            logger.info(f"Cámara {camera.id}: no hay componentes asociados con etapa de producción.")
            return None

        stage = max(stage_counts, key=STAGE_ORDER.get)
        representative_class = next(
            (
                group["representative_class"]
                for group in chassis_groups
                if camera.zone == "ALMACEN" or group["stage"] == stage
            ),
            "chasis_base",
        )
        strongest = max(
            (detection for detection in detections if detection.get("class_name") == representative_class),
            key=lambda detection: detection["confidence"],
        )

        cooldown_seconds = settings.STAGE_MIN_TIME_BETWEEN_EVENTS_SECONDS
        latest_event = self.event_repo.get_latest_for_camera(camera.id)
        if latest_event:
            time_diff = (now - latest_event.event_timestamp).total_seconds()
            if latest_event.stage == stage and time_diff < cooldown_seconds:
                logger.info(
                    f"Detección en cámara {camera.id} ({stage}) ignorada por ventana anti-duplicados "
                    f"({time_diff:.1f}s < {cooldown_seconds}s)"
                )
                return None

        event = ProductionEvent(
            camera_id=camera.id,
            zone=camera.zone,
            order_id=None,
            stage=stage,
            event_type="DETECCION_CONFIRMADA",
            association_status="PENDIENTE",
            sync_status="PENDIENTE",
            confidence=strongest["confidence"],
            evidence_count=sum(len(group["classes"]) for group in chassis_groups),
            origin="VISION_ARTIFICIAL",
            event_metadata={
                "class_name": representative_class,
                "camera_zone": camera.zone,
                "total_detections_in_frame": len(detections),
                "chassis_count": len(chassis_groups),
                "production_status_by_stage": stage_counts,
                "chassis_groups": chassis_groups,
            },
            event_timestamp=now,
            created_at=now
        )
        return self.event_repo.create(event)
