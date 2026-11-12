from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.core.config import MAX_YOLO_STREAM_INTERVAL_MS, MIN_YOLO_STREAM_INTERVAL_MS


class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class DetectionItem(BaseModel):
    class_id: int
    class_name: str
    stage_name: Optional[str] = None
    confidence: float
    bbox: BoundingBox


class MachineClassification(BaseModel):
    stage: Optional[str] = None
    label: str
    anchor_class: str
    representative_class: str
    classes: List[str]


class DetectionImageResponse(BaseModel):
    model_status: str
    inference_time_ms: float
    total_detections: int
    image_width: int
    image_height: int
    detections: List[DetectionItem]
    classifications: List[MachineClassification] = Field(default_factory=list)
    annotated_image_base64: Optional[str] = None


class DetectionResponse(BaseModel):
    id: int
    camera_id: Optional[int] = None
    zone: Optional[str] = None
    class_name: str
    confidence: float
    bbox_x1: int
    bbox_y1: int
    bbox_x2: int
    bbox_y2: int
    inference_time_ms: float
    image_path: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelStatusResponse(BaseModel):
    loaded: bool
    model_path: str
    device: str
    classes: dict
    conf_threshold: float
    iou_threshold: float
    img_size: int


class YoloRuntimeConfiguration(BaseModel):
    device_mode: Literal["auto", "cpu", "gpu"] = "auto"
    cpu_threads: int = Field(ge=1, le=2)
    gpu_memory_fraction: float = Field(ge=0.5, le=1.0)
    img_size: int = Field(default=416, ge=320, le=1280, multiple_of=32)
    stream_img_size: int = Field(default=224, ge=224, le=1280, multiple_of=32)
    stream_interval_ms: int = Field(
        default=200,
        ge=MIN_YOLO_STREAM_INTERVAL_MS,
        le=MAX_YOLO_STREAM_INTERVAL_MS,
    )

    @field_validator("cpu_threads", mode="before")
    @classmethod
    def limit_cpu_threads(cls, value):
        return max(1, min(2, int(value)))

    @field_validator("stream_interval_ms", mode="before")
    @classmethod
    def limit_stream_fps(cls, value):
        interval = int(value)
        return max(
            MIN_YOLO_STREAM_INTERVAL_MS,
            min(MAX_YOLO_STREAM_INTERVAL_MS, interval),
        )
