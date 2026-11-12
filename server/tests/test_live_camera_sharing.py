from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import HTTPException


def test_warehouse_detection_is_counted_without_persisting_history(monkeypatch):
    from app.services import detection_service as detection_module
    from app.services.camera_capture import _count_machines
    from app.services.zone_config_service import DEFAULT_CLASSIFICATION_RULES

    camera = SimpleNamespace(
        id=72,
        zone="ALMACEN",
        confidence_threshold=0.6,
        last_check_at=None,
        last_detection_at=None,
    )
    detections = [{
        "class_name": "chasis_vinilado",
        "confidence": 0.95,
        "bbox": {"x1": 1, "y1": 2, "x2": 20, "y2": 30},
    }]
    zone_config = {
        "zones": {"ALMACEN": {"allowed": ["chasis_vinilado"], "blocked": []}},
        "classification_rules": DEFAULT_CLASSIFICATION_RULES,
    }

    class MemoryCameraRepository:
        def get_by_id(self, _camera_id):
            return camera

        def update(self, updated_camera):
            return updated_camera

    class EmptySettingRepository:
        def get_by_key(self, _key):
            return None

    class NoHistoryRepository:
        def create(self, _item):
            pytest.fail("ALMACEN no debe persistir detecciones ni eventos")

    service = detection_module.DetectionService.__new__(detection_module.DetectionService)
    service.db = None
    service.camera_repo = MemoryCameraRepository()
    service.setting_repo = EmptySettingRepository()
    service.detection_repo = NoHistoryRepository()
    service.event_repo = NoHistoryRepository()

    monkeypatch.setattr(
        detection_module.yolo_service,
        "predict_image",
        lambda **_kwargs: {
            "detections": detections,
            "total_detections": len(detections),
            "inference_time_ms": 4.2,
        },
    )
    monkeypatch.setattr(
        detection_module,
        "ZoneConfigService",
        lambda _db: SimpleNamespace(get_config=lambda: zone_config),
    )

    result = service.process_image_upload(image_bytes=b"test-image", camera_id=camera.id)
    counts = _count_machines(
        camera.zone,
        result["detections"],
        result["stage_map"],
        zone_config,
    )

    assert result["total_detections"] == 1
    assert result["saved_detections_count"] == 0
    assert result["confirmed_event_id"] is None
    assert counts["machine_count"] == 1


def test_camera_stream_viewers_share_one_capture(monkeypatch):
    from app.api.v1.endpoints import cameras

    camera_id = 987654
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    captures = []

    class FakeCapture:
        def __init__(self):
            self.read_count = 0
            self.released = Event()

        def isOpened(self):
            return True

        def read(self):
            self.read_count += 1
            if self.read_count > 1:
                self.released.wait(0.01)
                if self.released.is_set():
                    return False, None
            return True, frame

        def release(self):
            self.released.set()

    class FakeInference:
        latest_boxes = []

        def __init__(self, *_args, **_kwargs):
            pass

        def submit_frame(self, _frame):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    def fake_open_capture(_source):
        capture = FakeCapture()
        captures.append(capture)
        return capture

    monkeypatch.setattr(cameras, "open_video_capture", fake_open_capture)
    monkeypatch.setattr(cameras, "InferenceOverlayThread", FakeInference)

    with cameras._camera_stream_sessions_lock:
        stale_session = cameras._camera_stream_sessions.pop(camera_id, None)
    if stale_session:
        stale_session.stop()
    while cameras.is_stream_active(camera_id):
        cameras.mark_stream_stopped(camera_id)

    session = None
    try:
        cameras.mark_stream_started(camera_id)
        session = cameras.acquire_camera_stream(camera_id, "rtsp://camera/live", 0.6)
        cameras.mark_stream_started(camera_id)
        second_viewer_session = cameras.acquire_camera_stream(camera_id, "rtsp://camera/live", 0.6)

        assert second_viewer_session is session
        assert session.client_count == 2
        assert len(captures) == 1
        assert session.read_new_frame(0)[1].shape == frame.shape

        cameras.mark_stream_started(camera_id)
        with pytest.raises(HTTPException) as error:
            cameras.acquire_camera_stream(camera_id, "rtsp://camera/changed", 0.6)
        cameras.mark_stream_stopped(camera_id)
        assert error.value.status_code == 409
        assert len(captures) == 1

        cameras.release_camera_stream(camera_id, session)
        assert session.client_count == 1
        assert cameras.is_stream_active(camera_id)
        cameras.release_camera_stream(camera_id, session)
        assert not cameras.is_stream_active(camera_id)
        assert captures[0].released.is_set()
    finally:
        with cameras._camera_stream_sessions_lock:
            leftover = cameras._camera_stream_sessions.pop(camera_id, None)
        if leftover:
            leftover.stop()
        if session and session.client_count:
            session.stop()
        while cameras.is_stream_active(camera_id):
            cameras.mark_stream_stopped(camera_id)
