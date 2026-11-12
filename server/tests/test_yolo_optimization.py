from collections import deque
import sys
from queue import Empty
from threading import Event, Lock, RLock
from types import SimpleNamespace

import numpy as np
import pytest


def test_predict_image_reuses_bgr_frame_without_jpeg_round_trip(monkeypatch):
    from app.services.yolo_service import YoloService

    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    calls = {}

    class FakeModel:
        def predict(self, **kwargs):
            calls.update(kwargs)
            return [SimpleNamespace(boxes=None)]

    service = YoloService.__new__(YoloService)
    service.model = FakeModel()
    service.classes = {}
    service.is_loaded = True
    service.device = "cpu"
    service.img_size = 416
    service._inference_lock = RLock()
    service._inference_durations = deque(maxlen=60)

    monkeypatch.setattr(
        "app.services.yolo_service.cv2.imdecode",
        lambda *_: pytest.fail("No debe decodificar un frame BGR"),
    )
    monkeypatch.setattr(
        "app.services.yolo_service.cv2.imencode",
        lambda *_: pytest.fail("No debe codificar una imagen sin anotaciones"),
    )

    result = service.predict_image(frame=frame, return_annotated=False)

    assert calls["source"] is frame
    assert calls["imgsz"] == 416
    assert "half" not in calls
    assert result["total_detections"] == 0
    assert result["annotated_image_base64"] is None


def test_predict_image_rejects_missing_or_ambiguous_source():
    from app.services.yolo_service import YoloService

    service = YoloService.__new__(YoloService)
    service.model = object()
    service.is_loaded = True

    with pytest.raises(ValueError, match="exactamente una"):
        service.predict_image()
    with pytest.raises(ValueError, match="exactamente una"):
        service.predict_image(image_bytes=b"image", frame=np.zeros((2, 2, 3), dtype=np.uint8))


def test_runtime_resolution_and_cpu_threads_update_without_reloading(monkeypatch):
    from app.services.yolo_service import YoloService

    service = YoloService.__new__(YoloService)
    service.device_mode = "cpu"
    service.device = "cpu"
    service.device_reason = "CPU anterior"
    service.cpu_threads = 2
    service.gpu_memory_fraction = 0.85
    service.img_size = 416
    service.stream_img_size = 320
    service.stream_interval_ms = 80
    service.model = object()
    service.classes = {0: "pieza"}
    service.is_loaded = True
    service._inference_lock = RLock()
    applied_thread_counts = []
    hardware = {
        "cpu_logical_cores": 4,
        "cuda_available": False,
        "gpus": [],
        "gpu_unavailable_reason": "CUDA no disponible",
    }

    monkeypatch.setattr(YoloService, "get_hardware_info", staticmethod(lambda: hardware))
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(set_num_threads=applied_thread_counts.append),
    )
    monkeypatch.setattr(
        service,
        "_load_model",
        lambda: pytest.fail("Cambiar resolución no debe recargar el modelo"),
    )

    service.configure_runtime({
        "device_mode": "cpu",
        "cpu_threads": 2,
        "gpu_memory_fraction": 0.85,
        "img_size": 320,
        "stream_img_size": 320,
    })

    assert service.img_size == 320
    assert service.stream_img_size == 320
    assert service.model is not None
    assert service.is_loaded
    assert applied_thread_counts == [2]


def test_camera_stream_skips_frames_inside_configured_interval(monkeypatch):
    from app.api.v1.endpoints import cameras

    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    stop_event = Event()
    inference_calls = []

    class FakeQueue:
        def __init__(self):
            self.frames = [frame, frame]

        def get(self, timeout):
            assert timeout > 0
            if self.frames:
                return self.frames.pop(0)
            stop_event.set()
            raise Empty

    session = cameras.InferenceOverlayThread.__new__(cameras.InferenceOverlayThread)
    session._stop = stop_event
    session._frame_queue = FakeQueue()
    session.conf_threshold = 0.7
    session.show_confidence = False
    session._lock = RLock()
    session._latest_boxes = []

    monkeypatch.setattr(cameras.yolo_service, "is_loaded", True)
    monkeypatch.setattr(cameras.yolo_service, "model", object())
    monkeypatch.setattr(cameras.yolo_service, "stream_interval_ms", 80)
    def fake_predict_frame(**kwargs):
        inference_calls.append(kwargs)
        return [SimpleNamespace(boxes=None)]

    monkeypatch.setattr(cameras.yolo_service, "predict_frame", fake_predict_frame)
    monotonic_values = iter((1.0, 1.01))
    monkeypatch.setattr(cameras.time, "monotonic", lambda: next(monotonic_values))

    session._run()

    assert len(inference_calls) == 1


def test_stream_runtime_limits_fps_to_one_through_ten_and_cpu_threads_to_two():
    from app.schemas.detection import YoloRuntimeConfiguration

    configuration = YoloRuntimeConfiguration(
        device_mode="cpu",
        cpu_threads=8,
        gpu_memory_fraction=0.8,
        img_size=416,
        stream_img_size=256,
        stream_interval_ms=50,
    )
    assert configuration.cpu_threads == 2
    assert configuration.stream_interval_ms == 100

    configuration = YoloRuntimeConfiguration(
        **(configuration.model_dump() | {"stream_interval_ms": 2000})
    )
    assert configuration.stream_interval_ms == 1000


def test_mjpeg_stream_respects_configured_maximum_fps(monkeypatch):
    from app.api.v1.endpoints import cameras

    clock = [0.0]
    wait_intervals = []
    encoded_fps = []

    class FakeStopEvent:
        def is_set(self):
            return False

        def wait(self, seconds):
            wait_intervals.append(seconds)
            clock[0] += seconds
            return False

    class FakeStream:
        stop_event = FakeStopEvent()
        finished = False

        def __init__(self):
            self.frame_id = 0

        def read_new_frame(self, _after_frame_id):
            self.frame_id += 1
            if self.frame_id > 3:
                self.finished = True
                return None
            return self.frame_id, np.zeros((8, 8, 3), dtype=np.uint8)

        def encode_frame(self, _frame_id, _frame, _show_confidence, fps):
            encoded_fps.append(fps)
            return b"jpeg"

    monkeypatch.setattr(cameras.yolo_service, "stream_interval_ms", 200)
    monkeypatch.setattr(cameras.time, "monotonic", lambda: clock[0])

    stream = cameras.generate_live_mjpeg_stream(FakeStream(), camera_id=None)
    chunks = [next(stream) for _ in range(3)]
    with pytest.raises(StopIteration):
        next(stream)

    assert all(b"jpeg" in chunk for chunk in chunks)
    assert encoded_fps == [5.0, 5.0, 5.0]
    assert wait_intervals == pytest.approx([0.2, 0.2, 0.2])


def test_shared_stream_encodes_a_frame_once_and_resizes_large_output(monkeypatch):
    from app.api.v1.endpoints import cameras

    stream = cameras.SharedCameraStream.__new__(cameras.SharedCameraStream)
    stream._encoded_frame_lock = Lock()
    stream._encoded_frames = {}
    stream.overlay = SimpleNamespace(latest_boxes=[])
    encoded_shapes = []

    class FakeBuffer:
        def tobytes(self):
            return b"jpeg"

    def fake_imencode(_extension, frame, options):
        encoded_shapes.append((frame.shape, options))
        return True, FakeBuffer()

    monkeypatch.setattr(cameras.cv2, "imencode", fake_imencode)
    frame = np.zeros((600, 1200, 3), dtype=np.uint8)

    first = stream.encode_frame(10, frame, True, 5.0)
    second = stream.encode_frame(10, frame, True, 5.0)

    assert first == second == b"jpeg"
    assert len(encoded_shapes) == 1
    assert encoded_shapes[0][0][:2] == (480, 960)
    assert encoded_shapes[0][1] == [cameras.cv2.IMWRITE_JPEG_QUALITY, 65]
