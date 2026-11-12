import os
import time
import base64
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import cv2
import numpy as np
import psutil
from PIL import Image
import io

from app.core.config import (
    MAX_YOLO_STREAM_INTERVAL_MS,
    MIN_YOLO_STREAM_INTERVAL_MS,
    settings,
)
from app.core.logging import logger
from app.core.exceptions import ModelNotLoadedException


class YoloService:
    _instance: Optional["YoloService"] = None

    def __init__(self):
        self.model = None
        self.classes: Dict[int, str] = {}
        self.is_loaded: bool = False
        self.model_path: str = settings.YOLO_MODEL_PATH
        self.device_mode = settings.YOLO_DEVICE.lower()
        if self.device_mode in {"cuda", "cuda:0"}:
            self.device_mode = "gpu"
        if self.device_mode not in {"auto", "cpu", "gpu"}:
            self.device_mode = "auto"
        self.device = "cpu"
        self.device_reason = ""
        self.cpu_threads = 0
        self.gpu_memory_fraction = settings.YOLO_GPU_MEMORY_FRACTION
        self.img_size = settings.YOLO_IMG_SIZE
        self.stream_img_size = settings.YOLO_STREAM_IMG_SIZE
        self.stream_interval_ms = max(
            MIN_YOLO_STREAM_INTERVAL_MS,
            min(MAX_YOLO_STREAM_INTERVAL_MS, settings.YOLO_STREAM_INTERVAL_MS),
        )
        self._inference_lock = threading.RLock()
        self._inference_durations = deque(maxlen=60)
        self._process = psutil.Process(os.getpid())
        # Avoid oversubscribing low-core CPUs alongside PyTorch inference.
        cv2.setNumThreads(1)
        self._load_model()

    @classmethod
    def get_instance(cls) -> "YoloService":
        if cls._instance is None:
            cls._instance = YoloService()
        return cls._instance

    def _load_model(self):
        """Loads the YOLO model into memory once."""
        self.device = self._resolve_device(self.device_mode)
        if not os.path.exists(self.model_path):
            logger.warning(f"Archivo de modelo YOLO no encontrado en la ruta: {self.model_path}")
            self.is_loaded = False
            return

        try:
            import torch
            from ultralytics import YOLO

            if self.cpu_threads < 1:
                cpu_count = os.cpu_count() or 1
                self.cpu_threads = min(
                    cpu_count,
                    2,
                    torch.get_num_threads() + max(0, settings.YOLO_CPU_EXTRA_THREADS)
                )
            torch.set_num_threads(self.cpu_threads)
            if self.device.startswith("cuda"):
                torch.cuda.set_per_process_memory_fraction(self.gpu_memory_fraction, device=0)

            logger.info(f"Cargando modelo YOLO desde '{self.model_path}' en dispositivo '{self.device}'...")
            self.model = YOLO(self.model_path)
            self.model.model.to(self.device)
            logger.info(f"Hilos CPU de PyTorch configurados: {torch.get_num_threads()}")

            # Extract real classes from the loaded model
            if hasattr(self.model, "names") and isinstance(self.model.names, dict):
                self.classes = {int(k): str(v) for k, v in self.model.names.items()}
            self.is_loaded = True
            logger.info(f"Modelo YOLO cargado exitosamente. Clases detectadas: {self.classes}")
        except Exception as e:
            logger.error(f"Error cargando el modelo YOLO: {e}")
            self.is_loaded = False
            self.model = None

    def get_status(self) -> Dict[str, Any]:
        return {
            "loaded": self.is_loaded,
            "model_path": self.model_path,
            "device": self.device,
            "classes": self.classes,
            "conf_threshold": settings.YOLO_CONF_THRESHOLD,
            "iou_threshold": settings.YOLO_IOU_THRESHOLD,
            "img_size": self.img_size,
            "stream_img_size": self.stream_img_size
        }

    @staticmethod
    def get_hardware_info() -> Dict[str, Any]:
        cpu_count = os.cpu_count() or 1
        hardware: Dict[str, Any] = {
            "cpu_logical_cores": cpu_count,
            "cuda_available": False,
            "cuda_version": None,
            "gpus": [],
            "gpu_unavailable_reason": None
        }
        try:
            import torch

            hardware["cuda_version"] = torch.version.cuda
            hardware["cuda_available"] = torch.cuda.is_available()
            if hardware["cuda_available"]:
                for index in range(torch.cuda.device_count()):
                    properties = torch.cuda.get_device_properties(index)
                    free_bytes, total_bytes = torch.cuda.mem_get_info(index)
                    hardware["gpus"].append({
                        "index": index,
                        "name": properties.name,
                        "total_memory_mb": round(total_bytes / (1024 * 1024)),
                        "free_memory_mb": round(free_bytes / (1024 * 1024))
                    })
            elif torch.version.cuda is None:
                hardware["gpu_unavailable_reason"] = "PyTorch está instalado sin soporte CUDA."
            else:
                hardware["gpu_unavailable_reason"] = "No se detectó una GPU CUDA disponible."
        except Exception as error:
            hardware["gpu_unavailable_reason"] = f"No se pudo consultar CUDA: {error}"
        return hardware

    def _resolve_device(self, mode: str) -> str:
        hardware = self.get_hardware_info()
        gpus = hardware["gpus"]
        if mode == "cpu":
            self.device_reason = "CPU seleccionado manualmente."
            return "cpu"
        if mode == "gpu":
            if hardware["cuda_available"] and gpus:
                self.device_reason = f"GPU seleccionada: {gpus[0]['name']}."
                return f"cuda:{gpus[0]['index']}"
            self.device_reason = hardware["gpu_unavailable_reason"] or "GPU no disponible; se usa CPU."
            return "cpu"
        if gpus and gpus[0]["free_memory_mb"] >= 1024:
            self.device_reason = f"Auto eligió GPU: {gpus[0]['name']} tiene al menos 1 GB libre."
            return f"cuda:{gpus[0]['index']}"
        self.device_reason = "Auto eligió CPU: no hay GPU CUDA con al menos 1 GB libre."
        return "cpu"

    def get_runtime_configuration(self) -> Dict[str, Any]:
        return {
            "device_mode": self.device_mode,
            "device": self.device,
            "device_reason": self.device_reason,
            "cpu_threads": self.cpu_threads or min(os.cpu_count() or 1, 2),
            "gpu_memory_fraction": self.gpu_memory_fraction,
            "img_size": self.img_size,
            "stream_img_size": self.stream_img_size,
            "stream_interval_ms": self.stream_interval_ms,
        }

    def get_runtime_metrics(self) -> Dict[str, Any]:
        cpu_count = os.cpu_count() or 1
        process_memory = self._process.memory_info().rss
        total_memory = psutil.virtual_memory().total
        inference_durations = list(self._inference_durations)
        gpu_memory_allocated_mb = None
        gpu_memory_reserved_mb = None
        gpu_memory_total_mb = None

        if self.device.startswith("cuda"):
            try:
                import torch

                device_index = torch.device(self.device).index or 0
                gpu_memory_allocated_mb = round(torch.cuda.memory_allocated(device_index) / (1024 * 1024), 1)
                gpu_memory_reserved_mb = round(torch.cuda.memory_reserved(device_index) / (1024 * 1024), 1)
                gpu_memory_total_mb = round(
                    torch.cuda.get_device_properties(device_index).total_memory / (1024 * 1024), 1
                )
            except Exception:
                pass

        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "process_cpu_percent": round(self._process.cpu_percent(interval=None) / cpu_count, 1),
            "process_memory_mb": round(process_memory / (1024 * 1024), 1),
            "process_memory_percent": round(process_memory / total_memory * 100, 1) if total_memory else 0,
            "system_memory_total_mb": round(total_memory / (1024 * 1024), 1),
            "inference_last_ms": round(inference_durations[-1], 1) if inference_durations else None,
            "inference_average_ms": round(sum(inference_durations) / len(inference_durations), 1)
            if inference_durations else None,
            "inference_samples": len(inference_durations),
            "gpu_memory_allocated_mb": gpu_memory_allocated_mb,
            "gpu_memory_reserved_mb": gpu_memory_reserved_mb,
            "gpu_memory_total_mb": gpu_memory_total_mb,
        }

    def configure_runtime(self, configuration: Dict[str, Any]) -> None:
        mode = configuration["device_mode"]
        hardware = self.get_hardware_info()
        if mode == "gpu" and not hardware["cuda_available"]:
            raise ValueError(hardware["gpu_unavailable_reason"] or "No hay GPU CUDA disponible.")
        with self._inference_lock:
            previous_state = {
                "device_mode": self.device_mode,
                "device": self.device,
                "device_reason": self.device_reason,
                "cpu_threads": self.cpu_threads,
                "gpu_memory_fraction": self.gpu_memory_fraction,
                "img_size": self.img_size,
                "stream_img_size": self.stream_img_size,
                "stream_interval_ms": self.stream_interval_ms,
                "model": self.model,
                "classes": self.classes,
                "is_loaded": self.is_loaded,
            }
            try:
                self.device_mode = mode
                self.device = self._resolve_device(mode)
                self.cpu_threads = min(
                    configuration["cpu_threads"],
                    hardware["cpu_logical_cores"],
                    2,
                )
                self.gpu_memory_fraction = configuration["gpu_memory_fraction"]
                self.img_size = configuration.get("img_size", self.img_size)
                self.stream_img_size = configuration["stream_img_size"]
                self.stream_interval_ms = max(
                    MIN_YOLO_STREAM_INTERVAL_MS,
                    min(
                        MAX_YOLO_STREAM_INTERVAL_MS,
                        configuration.get("stream_interval_ms", self.stream_interval_ms),
                    ),
                )

                import torch

                torch.set_num_threads(self.cpu_threads)
                reload_model = (
                    not self.is_loaded
                    or self.device != previous_state["device"]
                    or (
                        self.device.startswith("cuda")
                        and self.gpu_memory_fraction != previous_state["gpu_memory_fraction"]
                    )
                )
                if reload_model:
                    self.model = None
                    self.classes = {}
                    self.is_loaded = False
                    self._load_model()
                    if not self.is_loaded:
                        raise RuntimeError("No se pudo cargar YOLO con la configuración solicitada.")
            except Exception as error:
                for name, value in previous_state.items():
                    setattr(self, name, value)
                try:
                    import torch
                    if self.cpu_threads > 0:
                        torch.set_num_threads(self.cpu_threads)
                except Exception:
                    pass
                raise RuntimeError(
                    "No se pudo aplicar la configuración; se conservó el modelo anterior."
                ) from error

    def predict_frame(self, frame, img_size: int, conf_threshold: float, iou_threshold: float):
        with self._inference_lock:
            if not self.is_loaded or self.model is None:
                raise ModelNotLoadedException("El modelo YOLO no está cargado. Verifique best.pt.")
            start_time = time.perf_counter()
            try:
                return self.model.predict(
                    source=frame,
                    imgsz=img_size,
                    conf=conf_threshold,
                    iou=iou_threshold,
                    device=self.device,
                    verbose=False
                )
            finally:
                self._inference_durations.append((time.perf_counter() - start_time) * 1000)

    def get_classes(self) -> Dict[int, str]:
        return self.classes

    def predict_image(
        self,
        image_bytes: Optional[bytes] = None,
        conf_threshold: Optional[float] = None,
        iou_threshold: Optional[float] = None,
        img_size: Optional[int] = None,
        return_annotated: bool = True,
        show_confidence: bool = True,
        frame: Optional[np.ndarray] = None,
    ) -> Dict[str, Any]:
        """Detect objects in encoded image bytes or an existing BGR frame."""
        if not self.is_loaded or self.model is None:
            raise ModelNotLoadedException("El modelo YOLO no está cargado. Verifique best.pt.")
        if (image_bytes is None) == (frame is None):
            raise ValueError("Proporcione exactamente una imagen codificada o un frame BGR.")

        conf = conf_threshold if conf_threshold is not None else settings.YOLO_CONF_THRESHOLD
        iou = iou_threshold if iou_threshold is not None else settings.YOLO_IOU_THRESHOLD
        size = img_size if img_size is not None else self.img_size

        if image_bytes is not None:
            np_arr = np.frombuffer(image_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                raise ValueError("No se pudo decodificar la imagen proporcionada.")
        elif (
            not isinstance(frame, np.ndarray)
            or frame.ndim != 3
            or frame.shape[2] != 3
            or frame.dtype != np.uint8
        ):
            raise ValueError("El frame debe ser una imagen BGR de 8 bits.")
        if frame is None:
            raise ValueError("No se pudo preparar la imagen para inferencia.")

        height, width = frame.shape[:2]

        start_time = time.perf_counter()
        results = self.predict_frame(frame, size, conf, iou)
        inference_time_ms = round((time.perf_counter() - start_time) * 1000, 2)

        detections: List[Dict[str, Any]] = []
        annotated_frame = frame.copy() if return_annotated else None

        if len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            for box in boxes:
                confidence = float(box.conf[0])
                if confidence < conf:
                    continue

                class_id = int(box.cls[0])
                class_name = self.classes.get(class_id, f"clase_{class_id}")
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                detections.append({
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": round(confidence, 4),
                    "bbox": {
                        "x1": x1,
                        "y1": y1,
                        "x2": x2,
                        "y2": y2
                    }
                })

                if return_annotated and annotated_frame is not None:
                    # Clean label
                    clean_name = class_name.replace("chasis_", "")
                    label = f"{clean_name} {confidence * 100:.1f}%" if show_confidence else clean_name
                    
                    # Box
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (16, 185, 129), 2)
                    
                    # Label background
                    (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(
                        annotated_frame,
                        (x1, max(0, y1 - th - baseline - 8)),
                        (x1 + tw + 8, y1),
                        (16, 185, 129),
                        -1
                    )
                    cv2.putText(
                        annotated_frame,
                        label,
                        (x1 + 4, max(th + 2, y1 - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA
                    )

        annotated_base64 = None
        if return_annotated and annotated_frame is not None:
            _, buffer = cv2.imencode(".jpg", annotated_frame)
            annotated_base64 = base64.b64encode(buffer).decode("utf-8")

        return {
            "model_status": "ready",
            "inference_time_ms": inference_time_ms,
            "total_detections": len(detections),
            "image_width": width,
            "image_height": height,
            "detections": detections,
            "annotated_image_base64": annotated_base64
        }


yolo_service = YoloService.get_instance()
