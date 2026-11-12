import sys
import os
import re
import pytest
from fastapi.testclient import TestClient

# Add server directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.db.session import SessionLocal
from app.core.security import create_access_token
from app.db.models.camera import Camera


@pytest.fixture
def cleanup_zone_scope_test_cameras():
    def cleanup():
        db = SessionLocal()
        try:
            cameras = db.query(Camera).all()
            test_cameras = [
                camera for camera in cameras
                if re.fullmatch(r"zone-[ab]-\d{18,}", camera.name)
            ]
            for camera in test_cameras:
                db.delete(camera)
            if test_cameras:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    cleanup()
    yield
    cleanup()


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def db_session():
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="session")
def admin_token():
    return create_access_token(subject="admin", role="ADMIN")


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}
