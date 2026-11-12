import io
import pytest
import numpy as np
import cv2
from PIL import Image
from app.api.v1.endpoints.cameras import LatestFrameReader


def test_root_and_docs(client):
    """1 & 2: FastAPI starts and docs are accessible."""
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert "online" in res_root.json()["status"]

    res_docs = client.get("/docs")
    assert res_docs.status_code == 200

    res_openapi = client.get("/openapi.json")
    assert res_openapi.status_code == 200


def test_health_check(client):
    """3 & 5: PostgreSQL responds and YOLO status is reported."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()
    assert data["database"] == "healthy"
    assert data["yolo_model"] in ["loaded", "not_loaded"]


def test_camera_reader_keeps_only_the_latest_frame():
    import threading

    class FastCapture:
        def __init__(self):
            self.frame_number = 0
            self.finished = threading.Event()

        def read(self):
            self.frame_number += 1
            if self.frame_number > 20:
                self.finished.set()
                return False, None
            return True, np.full((1, 1, 3), self.frame_number, dtype=np.uint8)

        def release(self):
            pass

    cap = FastCapture()
    reader = LatestFrameReader(cap, np.zeros((1, 1, 3), dtype=np.uint8))
    reader.start()
    try:
        assert reader.finished_event.wait(timeout=2)
        latest_frame = reader.read(timeout=0.1)
        assert latest_frame is not None
        assert int(latest_frame[0, 0, 0]) == 20
    finally:
        reader.stop()


def test_camera_stream_rejects_requests_without_a_ticket(client):
    from app.core.security import create_access_token

    response = client.get("/api/v1/cameras/1/stream")
    session_token = create_access_token(subject="admin", role="ADMIN")
    session_response = client.get(
        "/api/v1/cameras/1/stream",
        params={"ticket": session_token},
    )

    assert response.status_code == 401
    assert session_response.status_code == 401


def test_camera_source_is_hidden_from_non_admin_users():
    from datetime import datetime, timezone
    from app.api.v1.endpoints.cameras import camera_response_for_user
    from app.db.models.camera import Camera
    from app.db.models.user import User

    now = datetime.now(timezone.utc)
    camera = Camera(
        id=7,
        name="Camera",
        zone="VINILADO",
        source="rtsp://operator:secret@10.0.0.4/live?token=private",
        is_active=True,
        confidence_threshold=0.6,
        is_connected=True,
        created_at=now,
        updated_at=now,
    )

    assert camera_response_for_user(camera, User(role="OPERATOR")).source == "Fuente protegida"
    assert camera_response_for_user(camera, User(role="ADMIN")).source == camera.source


def test_camera_monitor_skips_active_stream_and_updates_disconnected_camera(monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services import camera_monitor

    active_camera = SimpleNamespace(id=4, source="rtsp://127.0.0.1/active", is_connected=True, last_check_at=None)
    idle_camera = SimpleNamespace(id=5, source="rtsp://127.0.0.1/idle", is_connected=True, last_check_at=None)

    class MemoryRepository:
        def __init__(self, _db):
            self.cameras = [active_camera, idle_camera]

        def get_all(self, only_active=False):
            return self.cameras

        def update(self, camera):
            return camera

    class FailedCapture:
        def isOpened(self):
            return True

        def read(self):
            return False, None

        def release(self):
            pass

    opened_sources = []
    monkeypatch.setattr(camera_monitor, "CameraRepository", MemoryRepository)
    monkeypatch.setattr(camera_monitor, "_stream_counts", camera_monitor.Counter())
    camera_monitor.mark_stream_started(active_camera.id)
    try:
        checked = camera_monitor.check_camera_connections(
            None,
            lambda source: (opened_sources.append(source) or FailedCapture()),
        )
    finally:
        camera_monitor.mark_stream_stopped(active_camera.id)

    assert checked == 1
    assert opened_sources == ["rtsp://127.0.0.1/idle"]
    assert active_camera.is_connected is True
    assert idle_camera.is_connected is False
    assert isinstance(idle_camera.last_check_at, datetime)
    assert idle_camera.last_check_at.tzinfo == timezone.utc


def test_user_administration_requires_authentication(client):
    response = client.get("/api/v1/users")

    assert response.status_code == 401


def test_user_password_rejects_values_over_bcrypt_byte_limit():
    from pydantic import ValidationError
    from app.schemas.user import UserCreate

    with pytest.raises(ValidationError):
        UserCreate(
            username="long-password",
            full_name="Long Password",
            password="é" * 37,
        )


def test_health_metrics_are_protected_and_include_latency(client, admin_headers):
    client.get("/")
    assert client.get("/api/v1/health/metrics").status_code == 401
    response = client.get("/api/v1/health/metrics", headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["sample_count"] >= 1
    assert "p95_latency_ms" in response.json()


def test_event_csv_export_uses_csv_content_type(client, admin_headers):
    response = client.get("/api/v1/events/export.csv", headers=admin_headers)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "fecha_utc" in response.text

def test_audit_csv_export_is_admin_protected(client, admin_headers):
    assert client.get("/api/v1/audit/export.csv").status_code == 401
    response = client.get("/api/v1/audit/export.csv", headers=admin_headers)

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "accion" in response.text


def test_production_settings_reject_example_secret():
    from pydantic import ValidationError
    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY=Settings.EXAMPLE_SECRET_KEY,
            DATABASE_URL="postgresql+psycopg://service:secret@db.example.test/cardinova",
            ODOO_ENCRYPTION_KEY="e" * 40,
        )


def test_auth_flow(client):
    """9: Protected endpoints require auth; valid login issues token."""
    # Unauthorized access
    res_unauth = client.get("/api/v1/production/orders")
    assert res_unauth.status_code == 401

    # Valid login
    res_login = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "admin123"}
    )
    assert res_login.status_code == 200
    token_data = res_login.json()
    assert "access_token" in token_data
    assert token_data["user"]["username"] == "admin"

    # Invalid login
    res_fail = client.post(
        "/api/v1/auth/login",
        data={"username": "admin", "password": "wrongpassword"}
    )
    assert res_fail.status_code == 401


def test_admin_can_create_update_and_deactivate_users(client, admin_headers):
    username = f"test-user-{__import__('time').time_ns()}"
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "full_name": "Usuario de prueba",
            "role": "OPERATOR",
            "allowed_zones": ["VINILADO"],
            "is_active": True,
            "password": "Initial!Password2026",
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]

    updated = client.patch(
        f"/api/v1/users/{user_id}",
        headers=admin_headers,
        json={"role": "VIEWER", "password": "Changed!Password2026"},
    )
    assert updated.status_code == 200
    assert updated.json()["role"] == "VIEWER"

    viewer_login = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "Changed!Password2026"},
    )
    assert viewer_login.status_code == 200
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}
    assert client.get("/api/v1/users", headers=viewer_headers).status_code == 403

    deactivated = client.patch(
        f"/api/v1/users/{user_id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200
    assert client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "Changed!Password2026"},
    ).status_code == 401


def test_admin_can_delete_users_but_not_self(client, admin_headers):
    username = f"delete-user-{__import__('time').time_ns()}"
    created = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "full_name": "Usuario para borrar",
            "role": "OPERATOR",
            "allowed_zones": ["VINILADO"],
            "is_active": True,
            "password": "Initial!Password2026",
        },
    )
    assert created.status_code == 201

    deleted = client.delete(f"/api/v1/users/{created.json()['id']}", headers=admin_headers)
    assert deleted.status_code == 204
    assert client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": "Initial!Password2026"},
    ).status_code == 401

    admin_id = client.get("/api/v1/auth/me", headers=admin_headers).json()["id"]
    self_delete = client.delete(f"/api/v1/users/{admin_id}", headers=admin_headers)
    assert self_delete.status_code == 400


def test_user_zone_scope_is_enforced_across_cameras_events_and_exports(
    client, admin_headers, db_session, cleanup_zone_scope_test_cameras
):
    import json
    import time
    from datetime import datetime, timedelta, timezone
    from app.db.models.detection import Detection
    from app.db.models.production_event import ProductionEvent

    suffix = str(time.time_ns())
    allowed_camera = client.post(
        "/api/v1/cameras",
        headers=admin_headers,
        json={"name": f"zone-a-{suffix}", "zone": "VINILADO", "source": "rtsp://127.0.0.1:1/test-a", "confidence_threshold": 0.6},
    ).json()
    restricted_camera = client.post(
        "/api/v1/cameras",
        headers=admin_headers,
        json={"name": f"zone-b-{suffix}", "zone": "DOBLADO", "source": "rtsp://127.0.0.1:1/test-b", "confidence_threshold": 0.6},
    ).json()
    username = f"zone-user-{suffix}"
    created_user = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "full_name": "Operador Vinilado",
            "role": "OPERATOR",
            "allowed_zones": ["VINILADO"],
            "is_active": True,
            "password": "Zone!Password2026",
        },
    )
    assert created_user.status_code == 201
    login = client.post("/api/v1/auth/login", data={"username": username, "password": "Zone!Password2026"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    from app.db.models.camera import Camera
    from app.repositories.setting_repository import SettingRepository
    allowed_camera_record = db_session.query(Camera).filter(Camera.id == allowed_camera["id"]).first()
    allowed_camera_record.is_connected = True
    db_session.commit()
    SettingRepository(db_session).set_value("CAMERA_PRODUCTION_SNAPSHOT", json.dumps({
        str(allowed_camera["id"]): {
            "zone": "VINILADO",
            "machine_count": 4,
            "stage_counts": {"VINILADO": 2, "ARMADO_ESTRUCTURAL": 2},
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "warning": None,
        },
        str(restricted_camera["id"]): {
            "zone": "DOBLADO",
            "machine_count": 7,
            "stage_counts": {"DOBLADO": 7},
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "warning": None,
        },
    }))

    allowed_event = ProductionEvent(
        camera_id=allowed_camera["id"], zone="VINILADO", stage="VINILADO", event_type="DETECCION_CONFIRMADA",
        association_status="PENDIENTE", sync_status="PENDIENTE", confidence=0.9,
        evidence_count=1, origin="TEST", event_timestamp=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    restricted_event = ProductionEvent(
        camera_id=restricted_camera["id"], zone="DOBLADO", stage="DOBLADO", event_type="DETECCION_CONFIRMADA",
        association_status="PENDIENTE", sync_status="PENDIENTE", confidence=0.9,
        evidence_count=1, origin="TEST", event_timestamp=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    allowed_detection = Detection(
        camera_id=allowed_camera["id"], zone="VINILADO", class_name="allowed", confidence=0.9,
        bbox_x1=1, bbox_y1=1, bbox_x2=2, bbox_y2=2, inference_time_ms=10, created_at=datetime.now(timezone.utc),
    )
    restricted_detection = Detection(
        camera_id=restricted_camera["id"], zone="DOBLADO", class_name="restricted", confidence=0.9,
        bbox_x1=1, bbox_y1=1, bbox_x2=2, bbox_y2=2, inference_time_ms=10, created_at=datetime.now(timezone.utc),
    )
    db_session.add_all([allowed_event, restricted_event, allowed_detection, restricted_detection])
    db_session.commit()
    allowed_event_id, restricted_event_id = allowed_event.id, restricted_event.id

    allowed_order = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={"name": f"zone-order-a-{suffix}", "product_name": "Producto A", "target_qty": 1, "zone": "VINILADO"},
    ).json()
    restricted_order = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={"name": f"zone-order-b-{suffix}", "product_name": "Producto B", "target_qty": 1, "zone": "DOBLADO_LAMINA"},
    ).json()

    camera_ids = {camera["id"] for camera in client.get("/api/v1/cameras", headers=headers).json()}
    event_ids = {event["id"] for event in client.get("/api/v1/events", headers=headers).json()}
    order_ids = {order["id"] for order in client.get("/api/v1/production/orders", headers=headers).json()}
    dashboard = client.get("/api/v1/dashboard/stats", headers=headers)
    assert dashboard.status_code == 200
    zone_count = dashboard.json()["zone_machine_counts"]
    assert {item["zone"] for item in zone_count} == {"VINILADO"}
    assert zone_count[0]["machine_count"] == 4
    assert zone_count[0]["stage_counts"] == {"VINILADO": 2, "ARMADO_ESTRUCTURAL": 2}
    csv_response = client.get("/api/v1/events/export.csv", headers=headers)
    exported_event_ids = {int(row.split(",", 1)[0].lstrip("\ufeff")) for row in csv_response.text.splitlines()[1:]}
    order_csv = client.get("/api/v1/production/orders/export.csv", headers=headers)
    detection_csv = client.get("/api/v1/detections/export.csv", headers=headers)
    exported_order_ids = {int(row.split(",", 1)[0].lstrip("\ufeff")) for row in order_csv.text.splitlines()[1:]}
    exported_detection_classes = {row.split(",")[4] for row in detection_csv.text.splitlines()[1:]}

    assert allowed_camera["id"] in camera_ids
    assert restricted_camera["id"] not in camera_ids
    assert client.get(f"/api/v1/cameras/{restricted_camera['id']}", headers=headers).status_code == 403
    assert client.post(f"/api/v1/cameras/{restricted_camera['id']}/test", headers=headers).status_code == 403
    assert client.post(f"/api/v1/cameras/{restricted_camera['id']}/stream-ticket", headers=headers).status_code == 403
    assert allowed_order["id"] in order_ids
    assert restricted_order["id"] not in order_ids
    assert allowed_order["id"] in exported_order_ids
    assert restricted_order["id"] not in exported_order_ids
    assert client.get(f"/api/v1/production/orders/{restricted_order['id']}", headers=headers).status_code == 403
    assert allowed_event_id in event_ids
    assert restricted_event_id not in event_ids
    assert client.get(f"/api/v1/events/{restricted_event_id}", headers=headers).status_code == 403
    assert allowed_event_id in exported_event_ids
    assert restricted_event_id not in exported_event_ids
    assert "allowed" in exported_detection_classes
    assert "restricted" not in exported_detection_classes
    cross_zone_association = client.post(
        f"/api/v1/events/{allowed_event_id}/associate",
        headers=headers,
        json={"order_id": restricted_order["id"]},
    )
    assert cross_zone_association.status_code == 400

    moved_camera = client.put(
        f"/api/v1/cameras/{allowed_camera['id']}",
        headers=admin_headers,
        json={"zone": "ARMADO_ESTRUCTURAL"},
    )
    assert moved_camera.status_code == 200
    historical_event_ids = {event["id"] for event in client.get("/api/v1/events", headers=headers).json()}
    assert allowed_event_id in historical_event_ids
    now = datetime.now(timezone.utc)
    trend_response = client.get(
        "/api/v1/dashboard/production-trends",
        headers=headers,
        params={"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(minutes=1)).isoformat()},
    )
    assert trend_response.status_code == 200
    assert all(point["stage"] == "VINILADO" for point in trend_response.json())
    denied_order = client.post(
        "/api/v1/production/orders",
        headers=headers,
        json={"name": f"zone-order-denied-{suffix}", "product_name": "No permitido", "target_qty": 1, "zone": "DOBLADO_LAMINA"},
    )
    assert denied_order.status_code == 403


def test_model_classes_and_status(client, admin_headers):
    """5: Model classes match real trained weights."""
    res_status = client.get("/api/v1/models/status", headers=admin_headers)
    assert res_status.status_code == 200
    data = res_status.json()
    assert data["loaded"] is True
    assert "classes" in data
    assert 0 in data["classes"] or "0" in data["classes"]

    res_classes = client.get("/api/v1/models/classes", headers=admin_headers)
    assert res_classes.status_code == 200


def test_detection_image_inference(client, admin_headers):
    """6 & 7: Sending an image returns structured detections without crashing."""
    # Create a synthetic image (640x640 rgb)
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    img[100:400, 100:400] = [180, 180, 180]  # metallic sheet rectangle
    _, buffer = cv2.imencode(".jpg", img)

    file_payload = {
        "file": ("test_chasis.jpg", io.BytesIO(buffer.tobytes()), "image/jpeg")
    }
    data_payload = {
        "conf_threshold": 0.25,
        "show_confidence": "false"
    }

    res = client.post(
        "/api/v1/detections/image",
        headers=admin_headers,
        files=file_payload,
        data=data_payload
    )
    assert res.status_code == 200
    data = res.json()
    assert "total_detections" in data
    assert "inference_time_ms" in data
    assert "detections" in data
    assert data["image_width"] == 640
    assert data["image_height"] == 640
    assert data["annotated_image_base64"]


def test_detection_rejects_spoofed_image_content_type(client, admin_headers):
    response = client.post(
        "/api/v1/detections/image",
        headers=admin_headers,
        files={"file": ("fake.jpg", io.BytesIO(b"not an image"), "image/jpeg")},
    )

    assert response.status_code == 400


def test_production_orders_and_events(client, admin_headers):
    """7 & 8: Orders and events listing and association."""
    # Get cameras
    res_cam = client.get("/api/v1/cameras", headers=admin_headers)
    assert res_cam.status_code == 200
    cameras = res_cam.json()
    assert isinstance(cameras, list)

    # Create test order
    import time
    unique_name = f"MO-TEST-{int(time.time())}"
    res_order = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={
            "name": unique_name,
            "product_name": "Lavadora Cardinova Pro 500",
            "target_qty": 5,
            "zone": "VINILADO",
            "state": "draft"
        }
    )
    assert res_order.status_code == 200
    order_data = res_order.json()
    assert order_data["name"] == unique_name

    # List orders
    res_orders = client.get("/api/v1/production/orders", headers=admin_headers)
    assert res_orders.status_code == 200
    assert len(res_orders.json()) > 0


def test_finishing_event_counts_a_production_unit_only_once(client, admin_headers, db_session):
    import time
    from datetime import datetime, timezone
    from app.db.models.production_event import ProductionEvent

    order_response = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={
            "name": f"MO-COMPLETE-{time.time_ns()}",
            "product_name": "Producto de prueba",
            "target_qty": 1,
            "zone": "ALMACEN",
        },
    )
    assert order_response.status_code == 200
    order = order_response.json()
    event = ProductionEvent(
        order_id=order["id"],
        stage="ALMACEN",
        event_type="DETECCION_CONFIRMADA",
        association_status="ASOCIADO",
        sync_status="PENDIENTE",
        confidence=0.95,
        evidence_count=1,
        origin="TEST",
        event_metadata={},
        event_timestamp=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()
    event_id = event.id

    first = client.post(f"/api/v1/events/{event_id}/complete-unit", headers=admin_headers)
    second = client.post(f"/api/v1/events/{event_id}/complete-unit", headers=admin_headers)
    updated_order = client.get(f"/api/v1/production/orders/{order['id']}", headers=admin_headers).json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["event_type"] == "FIN_PRODUCTO"
    assert updated_order["produced_qty"] == 1
    assert updated_order["state"] == "done"


def test_odoo_graceful_handling(client, admin_headers):
    """10: API responds safely when Odoo is not available."""
    res = client.get("/api/v1/odoo/status", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    # It should cleanly report configured or connected status without raising a 500
    assert "connected" in data
    assert "configured" in data


def test_odoo_disabled_status_does_not_connect(client, admin_headers, monkeypatch):
    from types import SimpleNamespace
    from app.integrations.odoo_client import OdooClient
    from app.repositories.setting_repository import SettingRepository

    original_get_by_key = SettingRepository.get_by_key

    def get_disabled_setting(repository, key):
        if key == "ODOO_INTEGRATION_ENABLED":
            return SimpleNamespace(value="false")
        return original_get_by_key(repository, key)

    def fail_if_connection_is_attempted(_client):
        pytest.fail("No debe intentarse conectar con Odoo cuando la integración está desactivada")

    monkeypatch.setattr(SettingRepository, "get_by_key", get_disabled_setting)
    monkeypatch.setattr(OdooClient, "test_connection", fail_if_connection_is_attempted)

    status_response = client.get("/api/v1/odoo/status", headers=admin_headers)
    dashboard_response = client.get("/api/v1/dashboard/stats", headers=admin_headers)
    health_response = client.get("/api/v1/health")
    orders_response = client.post("/api/v1/odoo/sync-orders", headers=admin_headers)
    events_response = client.post("/api/v1/odoo/sync-events", headers=admin_headers)

    assert status_response.status_code == 200
    assert status_response.json()["enabled"] is False
    assert status_response.json()["connected"] is False
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["status"]["odoo_connected"] is False
    assert health_response.status_code == 200
    assert orders_response.status_code == 200
    assert orders_response.json()["errors"] == ["Integración con Odoo desactivada"]
    assert events_response.status_code == 200
    assert events_response.json()["status"] == "disabled_pending"


def test_odoo_config_is_persisted_without_returning_api_key(monkeypatch):
    from types import SimpleNamespace
    from app.services import odoo_service
    from app.core.secrets import decrypt_secret

    class MemorySettings:
        def __init__(self):
            self.values = {}

        def get_by_key(self, key):
            return self.values.get(key)

        def set_value(self, key, value, description=None):
            setting = SimpleNamespace(key=key, value=value, description=description)
            self.values[key] = setting
            return setting

    stored_settings = MemorySettings()
    monkeypatch.setattr(odoo_service, "SettingRepository", lambda _db: stored_settings)
    monkeypatch.setattr(odoo_service, "ProductionRepository", lambda _db: object())
    monkeypatch.setattr(odoo_service, "EventRepository", lambda _db: object())
    service = odoo_service.OdooService(None)

    config = service.update_config({
        "base_url": "https://odoo.example.test",
        "database": "factory",
        "username": "vision-service",
        "timeout": 12,
        "api_key": "test-secret",
        "clear_api_key": False,
    })

    assert stored_settings.values["ODOO_BASE_URL"].value == "https://odoo.example.test"
    encrypted_key = stored_settings.values["ODOO_API_KEY"].value
    assert encrypted_key.startswith("fernet:")
    assert decrypt_secret(encrypted_key) == "test-secret"
    assert config["api_key_configured"] is True
    assert "api_key" not in config

    cleared_config = service.update_config({
        "base_url": "https://odoo.example.test",
        "database": "factory",
        "username": "vision-service",
        "timeout": 12,
        "clear_api_key": True,
    })

    assert stored_settings.values["ODOO_API_KEY"].value == ""
    assert cleared_config["api_key_configured"] is False


def test_odoo_event_post_uses_idempotency_marker(monkeypatch):
    from app.integrations import odoo_client

    class FakeModels:
        posted = False
        post_calls = 0

        def execute_kw(self, _database, _uid, _api_key, model, method, args, kwargs):
            if model == "mail.message" and method == "search_read":
                return [{"id": 42}] if self.posted else []
            if model == "mrp.production" and method == "message_post":
                self.posted = True
                self.post_calls += 1
                assert "CARDINOVA-EVENT:17" in kwargs["body"]
                return 42
            raise AssertionError(f"Llamada Odoo inesperada: {model}.{method}")

    fake_models = FakeModels()
    monkeypatch.setattr(odoo_client.xmlrpc.client, "ServerProxy", lambda *_args, **_kwargs: fake_models)
    client = odoo_client.OdooClient("https://odoo.example.test", "factory", "vision", "secret")
    monkeypatch.setattr(client, "get_uid", lambda: 5)
    event = {
        "stage": "VINILADO",
        "event_type": "DETECCION_CONFIRMADA",
        "event_timestamp": "2026-10-13T10:00:00+00:00",
        "confidence": 0.95,
    }

    assert client.post_production_event(23, 17, event) is True
    assert client.post_production_event(23, 17, event) is False
    assert fake_models.post_calls == 1


def test_odoo_order_query_honors_pagination_offset(monkeypatch):
    from app.integrations import odoo_client

    class FakeModels:
        def execute_kw(self, _database, _uid, _api_key, _model, _method, _args, kwargs):
            assert kwargs["limit"] == 25
            assert kwargs["offset"] == 50
            return []

    monkeypatch.setattr(odoo_client.xmlrpc.client, "ServerProxy", lambda *_args, **_kwargs: FakeModels())
    client = odoo_client.OdooClient("https://odoo.example.test", "factory", "vision", "secret")
    monkeypatch.setattr(client, "get_uid", lambda: 5)

    assert client.get_production_orders(limit=25, offset=50) == []


def test_odoo_sync_failure_keeps_event_pending_and_schedules_retry():
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from app.services.odoo_service import OdooService

    event = SimpleNamespace(
        id=81,
        order_id=23,
        association_status="ASOCIADO",
        sync_status="PENDIENTE",
        event_metadata={},
        stage="VINILADO",
        event_type="DETECCION_CONFIRMADA",
        event_timestamp=datetime.now(timezone.utc),
        confidence=0.91,
    )

    class MemoryRepository:
        def get_pending_sync_for_update(self, limit):
            assert limit == 100
            return [event]

        def update(self, updated_event):
            return updated_event

    class FailingClient:
        def test_connection(self):
            return {"connected": True, "authenticated": True}

        def post_production_event(self, *_args):
            raise TimeoutError("Odoo timeout")

    service = OdooService.__new__(OdooService)
    service.settings_repo = SimpleNamespace(get_by_key=lambda _key: SimpleNamespace(value="true"))
    service.event_repo = MemoryRepository()
    service.production_repo = SimpleNamespace(get_by_id=lambda _order_id: SimpleNamespace(odoo_order_id=42))
    service.client = FailingClient()

    result = service.sync_pending_events_to_odoo()

    assert result["status"] == "partial"
    assert event.sync_status == "PENDIENTE"
    assert event.event_metadata["odoo_sync_attempts"] == 1
    assert event.event_metadata["odoo_sync_error"] == "Odoo timeout"
    assert datetime.fromisoformat(event.event_metadata["odoo_retry_at"]) > datetime.now(timezone.utc)


def test_dashboard_stats(client, admin_headers):
    """Dashboard aggregates real statistics."""
    res = client.get("/api/v1/dashboard/stats", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"]["postgres_connected"] is True
    assert "total_orders" in data
    assert "stage_distribution" in data


def test_dashboard_production_trends(client, admin_headers):
    from datetime import datetime, timedelta, timezone

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    res = client.get(
        "/api/v1/dashboard/production-trends",
        headers=admin_headers,
        params={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "interval_minutes": 5,
        },
    )
    assert res.status_code == 200
    assert isinstance(res.json(), list)
    assert all({"timestamp", "stage", "count"}.issubset(point) for point in res.json())


def test_events_reject_an_inverted_date_range(client, admin_headers):
    response = client.get(
        "/api/v1/events",
        headers=admin_headers,
        params={
            "date_from": "2026-10-13T12:00:00+00:00",
            "date_to": "2026-10-13T11:00:00+00:00",
        },
    )

    assert response.status_code == 422


def test_admin_can_edit_events_and_orders_and_preserve_event_history(client, admin_headers, db_session):
    import time
    from datetime import datetime, timezone
    from app.db.models.production_event import ProductionEvent
    from app.db.models.production_order import ProductionOrder

    order_response = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={
            "name": f"MO-ADMIN-EDIT-{time.time_ns()}",
            "product_name": "Producto inicial",
            "target_qty": 1,
            "zone": "VINILADO",
        },
    )
    assert order_response.status_code == 200
    order = order_response.json()
    db_order = db_session.get(ProductionOrder, order["id"])
    db_order.produced_qty = 1
    db_order.state = "done"

    now = datetime.now(timezone.utc)
    completed_event = ProductionEvent(
        order_id=order["id"], stage="VINILADO", event_type="FIN_PRODUCTO",
        association_status="ASOCIADO", sync_status="PENDIENTE", confidence=0.95,
        evidence_count=1, origin="TEST", event_metadata={"unit_completed": True},
        event_timestamp=now, created_at=now,
    )
    preserved_event = ProductionEvent(
        order_id=order["id"], stage="VINILADO", event_type="DETECCION_CONFIRMADA",
        association_status="ASOCIADO", sync_status="PENDIENTE", confidence=0.9,
        evidence_count=1, origin="TEST", event_metadata={},
        event_timestamp=now, created_at=now,
    )
    db_session.add_all([completed_event, preserved_event])
    db_session.commit()
    completed_event_id = completed_event.id
    preserved_event_id = preserved_event.id

    event_update = client.patch(
        f"/api/v1/events/{preserved_event_id}",
        headers=admin_headers,
        json={"confidence": 0.82, "evidence_count": 2},
    )
    order_update = client.patch(
        f"/api/v1/production/orders/{order['id']}",
        headers=admin_headers,
        json={"product_name": "Producto corregido", "target_qty": 3},
    )
    assert event_update.status_code == 200
    assert event_update.json()["confidence"] == 0.82
    assert order_update.status_code == 200
    assert order_update.json()["product_name"] == "Producto corregido"
    assert order_update.json()["target_qty"] == 3

    delete_completed = client.delete(f"/api/v1/events/{completed_event_id}", headers=admin_headers)
    order_after_delete = client.get(f"/api/v1/production/orders/{order['id']}", headers=admin_headers).json()
    assert delete_completed.status_code == 204
    assert order_after_delete["produced_qty"] == 0
    assert order_after_delete["state"] == "progress"

    delete_order = client.delete(f"/api/v1/production/orders/{order['id']}", headers=admin_headers)
    preserved_event_response = client.get(f"/api/v1/events/{preserved_event_id}", headers=admin_headers)
    assert delete_order.status_code == 204
    assert preserved_event_response.status_code == 200
    assert preserved_event_response.json()["order_id"] is None


def test_event_and_order_mutations_are_admin_only(client, admin_headers, db_session):
    import time
    from app.core.security import create_access_token
    from app.db.models.production_event import ProductionEvent
    from datetime import datetime, timezone

    username = f"operator-{time.time_ns()}"
    user_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "full_name": "Operador de prueba",
            "password": "TestPassword123!",
            "role": "OPERATOR",
            "allowed_zones": ["VINILADO"],
            "is_active": True,
        },
    )
    assert user_response.status_code == 201
    operator_headers = {"Authorization": f"Bearer {create_access_token(subject=username, role="OPERATOR")}"}
    order_response = client.post(
        "/api/v1/production/orders",
        headers=admin_headers,
        json={"name": f"MO-ADMIN-ONLY-{time.time_ns()}", "product_name": "Producto", "target_qty": 1, "zone": "VINILADO"},
    )
    assert order_response.status_code == 200
    event = ProductionEvent(
        order_id=order_response.json()["id"], stage="VINILADO", event_type="DETECCION_CONFIRMADA",
        association_status="ASOCIADO", sync_status="PENDIENTE", confidence=0.9,
        evidence_count=1, origin="TEST", event_metadata={},
        event_timestamp=datetime.now(timezone.utc), created_at=datetime.now(timezone.utc),
    )
    db_session.add(event)
    db_session.commit()
    event_id = event.id

    order_id = order_response.json()["id"]
    assert client.patch(f"/api/v1/events/{event_id}", headers=operator_headers, json={"confidence": 0.5}).status_code == 403
    assert client.delete(f"/api/v1/events/{event_id}", headers=operator_headers).status_code == 403
    assert client.patch(f"/api/v1/production/orders/{order_id}", headers=operator_headers, json={"product_name": "No"}).status_code == 403
    assert client.delete(f"/api/v1/production/orders/{order_id}", headers=operator_headers).status_code == 403


def test_yolo_auto_selects_gpu_only_when_memory_is_available(monkeypatch):
    from app.services.yolo_service import YoloService

    service = YoloService.__new__(YoloService)
    service.device_reason = ""
    hardware = {
        "cuda_available": True,
        "gpus": [{"index": 0, "name": "Test GPU", "free_memory_mb": 2048}]
    }
    monkeypatch.setattr(YoloService, "get_hardware_info", staticmethod(lambda: hardware))
    assert service._resolve_device("auto") == "cuda:0"

    hardware["gpus"][0]["free_memory_mb"] = 512
    assert service._resolve_device("auto") == "cpu"


def test_yolo_rejects_forced_gpu_without_cuda(monkeypatch):
    from app.services.yolo_service import YoloService

    service = YoloService.__new__(YoloService)
    hardware = {
        "cuda_available": False,
        "gpus": [],
        "gpu_unavailable_reason": "PyTorch está instalado sin soporte CUDA."
    }
    monkeypatch.setattr(YoloService, "get_hardware_info", staticmethod(lambda: hardware))

    with pytest.raises(ValueError, match="sin soporte CUDA"):
        service.configure_runtime({
            "device_mode": "gpu",
            "cpu_threads": 2,
            "gpu_memory_fraction": 0.85,
            "stream_img_size": 416,
        })


def test_yolo_runtime_api_is_disabled_outside_development(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import models
    from app.schemas.detection import YoloRuntimeConfiguration

    monkeypatch.setattr(models.settings, "ENVIRONMENT", "production")
    response = models.get_yolo_runtime_configuration(db=None, current_user=None)
    assert response == {"enabled": False, "environment": "production"}

    configuration = YoloRuntimeConfiguration(
        device_mode="auto",
        cpu_threads=2,
        gpu_memory_fraction=0.85,
        stream_img_size=416,
    )
    with pytest.raises(HTTPException) as error:
        models.update_yolo_runtime_configuration(configuration, db=None, current_user=None)
    assert error.value.status_code == 404


def test_yolo_metrics_api_is_development_only(monkeypatch):
    from app.api.v1.endpoints import models

    monkeypatch.setattr(models.settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(models.yolo_service, "get_runtime_metrics", lambda: {
        "process_cpu_percent": 12.5,
        "process_memory_mb": 256.0,
        "inference_average_ms": 80.0,
    })
    metrics = models.get_yolo_runtime_metrics(current_user=None)
    assert metrics["enabled"] is True
    assert metrics["process_cpu_percent"] == 12.5

    monkeypatch.setattr(models.settings, "ENVIRONMENT", "production")
    disabled = models.get_yolo_runtime_metrics(current_user=None)
    assert disabled == {"enabled": False, "environment": "production"}


def test_yolo_runtime_reload_failure_restores_previous_model(monkeypatch):
    from threading import RLock
    from app.services.yolo_service import YoloService

    service = YoloService.__new__(YoloService)
    service.device_mode = "cpu"
    service.device = "cpu"
    service.device_reason = "CPU previo"
    service.cpu_threads = 2
    service.gpu_memory_fraction = 0.85
    service.img_size = 416
    service.stream_img_size = 416
    service.stream_interval_ms = 80
    service.model = object()
    service.classes = {0: "pieza"}
    service.is_loaded = True
    service._inference_lock = RLock()

    monkeypatch.setattr(YoloService, "get_hardware_info", staticmethod(lambda: {
        "cpu_logical_cores": 8,
        "cuda_available": True,
        "gpus": [{"index": 0, "name": "Test GPU", "free_memory_mb": 2048}],
    }))

    def fail_to_load():
        service.model = None
        service.is_loaded = False

    monkeypatch.setattr(service, "_load_model", fail_to_load)
    with pytest.raises(RuntimeError, match="se conservó el modelo anterior"):
        service.configure_runtime({
            "device_mode": "gpu",
            "cpu_threads": 4,
            "gpu_memory_fraction": 0.75,
            "img_size": 512,
            "stream_img_size": 512,
            "stream_interval_ms": 120,
        })

    assert service.device == "cpu"
    assert service.device_mode == "cpu"
    assert service.img_size == 416
    assert service.model is not None
    assert service.is_loaded is True


def test_detection_components_are_associated_only_with_containing_chassis():
    from app.services.detection_service import associate_detections_with_chassis

    stages = {
        "chasis_base": "DOBLADO",
        "cavidad_hueca": "DOBLADO",
        "puerta_sup_panel": "ARMADO_ESTRUCTURAL",
        "puerta_sup_chapa": "ARMADO_ESTRUCTURAL",
        "puerta_inferior": "ARMADO_ESTRUCTURAL",
        "vinilo_frontal": "VINILADO",
        "vinilo_lateral": "VINILADO",
    }
    detections = [
        {"class_name": "chasis_base", "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}},
        {"class_name": "chasis_base", "bbox": {"x1": 150, "y1": 0, "x2": 250, "y2": 100}},
        {"class_name": "cavidad_hueca", "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
        {"class_name": "vinilo_frontal", "bbox": {"x1": 170, "y1": 20, "x2": 190, "y2": 40}},
        {"class_name": "puerta_inferior", "bbox": {"x1": 110, "y1": 20, "x2": 130, "y2": 40}},
    ]

    groups = associate_detections_with_chassis(detections, stages)

    assert groups == [
        {
            "stage": "DOBLADO",
            "label": "Chasis doblado",
            "anchor_class": "chasis_base",
            "representative_class": "chasis_base",
            "classes": ["cavidad_hueca", "chasis_base"],
        },
        {
            "stage": "VINILADO",
            "label": "Chasis vinilado",
            "anchor_class": "chasis_base",
            "representative_class": "vinilo_frontal",
            "classes": ["chasis_base", "vinilo_frontal"],
        },
    ]


def test_composite_classification_uses_associated_classes_and_supports_single_class_rules():
    from app.services.detection_service import associate_detections_with_chassis
    from app.services.zone_config_service import DEFAULT_CLASSIFICATION_RULES

    stages = {
        "chasis_base": "DOBLADO",
        "chasis_vinilado": "VINILADO",
        "cavidad_hueca": "DOBLADO",
        "puerta_inferior": "ARMADO_ESTRUCTURAL",
    }
    detections = [
        {"class_name": "chasis_base", "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}},
        {"class_name": "chasis_base", "bbox": {"x1": 200, "y1": 0, "x2": 300, "y2": 100}},
        {"class_name": "chasis_vinilado", "bbox": {"x1": 400, "y1": 0, "x2": 500, "y2": 100}},
        {"class_name": "chasis_base", "bbox": {"x1": 600, "y1": 0, "x2": 700, "y2": 100}},
        {"class_name": "cavidad_hueca", "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
        {"class_name": "puerta_inferior", "bbox": {"x1": 220, "y1": 20, "x2": 240, "y2": 40}},
        {"class_name": "puerta_inferior", "bbox": {"x1": 120, "y1": 20, "x2": 140, "y2": 40}},
    ]

    groups = associate_detections_with_chassis(detections, stages, DEFAULT_CLASSIFICATION_RULES)

    assert [(group["label"], group["stage"]) for group in groups] == [
        ("Chasis doblado", "DOBLADO"),
        ("Chasis estructurado", "ARMADO_ESTRUCTURAL"),
        ("Chasis vinilado", "VINILADO"),
        ("Chasis sin clasificar", None),
    ]
    assert groups[0]["classes"] == ["cavidad_hueca", "chasis_base"]
    assert groups[1]["classes"] == ["chasis_base", "puerta_inferior"]
    assert groups[2]["classes"] == ["chasis_vinilado"]
    assert groups[3]["stage"] is None
    assert groups[3]["label"] == "Chasis sin clasificar"
    assert groups[3]["classes"] == ["chasis_base"]

    custom_anchor = associate_detections_with_chassis(
        [{"class_name": "carcasa", "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}}],
        {"carcasa": "DOBLADO"},
        [{
            "id": "carcasa-simple",
            "name": "Carcasa simple",
            "stage": "DOBLADO",
            "anchor_class": "carcasa",
            "required_classes": [],
            "one_of_classes": [],
        }],
    )
    assert custom_anchor[0]["label"] == "Carcasa simple"


def test_camera_machine_counts_use_composite_classification_rules():
    from app.services.camera_capture import _count_machines
    from app.services.zone_config_service import DEFAULT_CLASSIFICATION_RULES

    counts = _count_machines(
        "ARMADO_ESTRUCTURAL",
        [
            {"class_name": "chasis_base", "bbox": {"x1": 0, "y1": 0, "x2": 100, "y2": 100}},
            {"class_name": "puerta_inferior", "bbox": {"x1": 20, "y1": 20, "x2": 40, "y2": 40}},
        ],
        {"chasis_base": "DOBLADO", "puerta_inferior": "ARMADO_ESTRUCTURAL"},
        {
            "zones": {"ARMADO_ESTRUCTURAL": {"allowed": [], "blocked": []}},
            "classification_rules": DEFAULT_CLASSIFICATION_RULES,
        },
    )

    assert counts["machine_count"] == 1
    assert counts["stage_counts"] == {"ARMADO_ESTRUCTURAL": 1}
    assert counts["classification_counts"] == {"Chasis estructurado": 1}


def test_detection_zone_config_persists_composite_classification_rules(client, admin_headers):
    rules = [{
        "id": "chasis-estructurado",
        "name": "Estructura personalizada",
        "stage": "ARMADO_ESTRUCTURAL",
        "anchor_class": "chasis_base",
        "required_classes": [],
        "one_of_classes": ["puerta_inferior", "puerta_sup_panel"],
    }]
    payload = {
        "zones": {"DOBLADO": {"description": "", "allowed": [], "blocked": []}},
        "classification_rules": rules,
    }

    response = client.put("/api/v1/detection-zones", headers=admin_headers, json=payload)

    assert response.status_code == 200
    assert response.json()["classification_rules"] == rules
    assert client.get("/api/v1/detection-zones", headers=admin_headers).json()["classification_rules"] == rules


def test_detection_zone_update_without_new_rules_keeps_default_compatibility(client, admin_headers):
    reset = client.post("/api/v1/detection-zones/reset", headers=admin_headers)
    assert reset.status_code == 200

    response = client.put(
        "/api/v1/detection-zones",
        headers=admin_headers,
        json={"zones": {"DOBLADO": {"description": "", "allowed": [], "blocked": []}}},
    )

    assert response.status_code == 200
    assert {rule["id"] for rule in response.json()["classification_rules"]} == {
        "chasis-estructurado",
        "chasis-doblado",
        "chasis-vinilado",
    }


def test_camera_api_rejects_unsupported_zones(client, admin_headers):
    response = client.post(
        "/api/v1/cameras",
        headers=admin_headers,
        json={"name": "invalid-zone", "zone": "ZONA_INEXISTENTE", "source": "rtsp://127.0.0.1/test"},
    )

    assert response.status_code == 422


def test_camera_api_rejects_local_camera_indices(client, admin_headers):
    response = client.post(
        "/api/v1/cameras",
        headers=admin_headers,
        json={"name": "local-index", "zone": "VINILADO", "source": "0"},
    )

    assert response.status_code == 422


def test_camera_capture_refuses_local_camera_indices():
    import pytest
    from app.api.v1.endpoints.cameras import open_video_capture

    with pytest.raises(ValueError, match="fuente de red"):
        open_video_capture("0")
