import io
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

os.environ["USE_PROCESS_POOL"] = "false"

import backend.app.services.tasks as task_service
from backend.app.db.session import Base, engine
from backend.app.main import app


def _image_bytes():
    image = np.random.randint(0, 255, (320, 320, 3), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return io.BytesIO(encoded.tobytes())


def _register_and_token(client: TestClient, username: str, password: str):
    reg = client.post("/api/auth/register", json={"username": username, "password": password})
    assert reg.status_code in (200, 400)
    tok = client.post("/api/auth/token", json={"username": username, "password": password})
    assert tok.status_code == 200
    assert "set-cookie" in tok.headers
    payload = tok.json()
    access_token = payload["access_token"]
    csrf_token = payload["csrf_token"]
    return {
        "access_token": access_token,
        "csrf_token": csrf_token,
        "auth_headers": {"Authorization": f"Bearer {access_token}"},
        "csrf_headers": {"X-CSRF-Token": csrf_token},
    }


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def fake_analysis(file_path: str, upload_dir: str):
        name = Path(file_path).name
        artifact = f"{name}_ela_test.png"
        Path(upload_dir).mkdir(parents=True, exist_ok=True)
        (Path(upload_dir) / artifact).write_bytes(b"fake")
        return {
            "method": "forensic",
            "score": 0.42,
            "forensic_score": 42.0,
            "label": "inconclusive",
            "details": {"ela": 0.4, "orb": 0.5, "metadata": 0.2, "wavelet": 0.6},
            "analysis": {"ela": {"map": artifact}},
            "artifacts": {"ela_map": artifact},
            "execution_time_ms": 10.2,
        }

    monkeypatch.setattr(task_service, "run_forensic_analysis", fake_analysis)
    return TestClient(app)


class TestAuth:
    def test_register_and_get_token(self, client):
        response = client.post("/api/auth/register", json={"username": "alice", "password": "pass1234"})
        assert response.status_code == 200
        token = client.post("/api/auth/token", json={"username": "alice", "password": "pass1234"})
        assert token.status_code == 200
        assert "access_token" in token.json()
        assert "csrf_token" in token.json()
        assert "forensic_refresh" in token.headers.get("set-cookie", "")

    def test_refresh_rotation(self, client):
        _register_and_token(client, "rotate", "pass1234")
        first = client.post("/api/auth/token", json={"username": "rotate", "password": "pass1234"})
        assert first.status_code == 200
        first_access = first.json()["access_token"]
        first_csrf = first.json()["csrf_token"]

        refreshed = client.post("/api/auth/refresh", headers={"X-CSRF-Token": first_csrf})
        assert refreshed.status_code == 200
        second_access = refreshed.json()["access_token"]
        second_csrf = refreshed.json()["csrf_token"]
        assert second_access != first_access
        assert second_csrf != first_csrf
        assert "forensic_refresh" in refreshed.headers.get("set-cookie", "")

    def test_logout_revokes_refresh(self, client):
        auth = _register_and_token(client, "logoutuser", "pass1234")
        out = client.post("/api/auth/logout", headers=auth["csrf_headers"])
        assert out.status_code == 204

        refreshed = client.post("/api/auth/refresh", headers=auth["csrf_headers"])
        assert refreshed.status_code == 401

    def test_refresh_rejects_missing_csrf(self, client):
        _register_and_token(client, "csrfuser", "pass1234")
        refreshed = client.post("/api/auth/refresh")
        assert refreshed.status_code == 401

    def test_refresh_rejects_invalid_csrf(self, client):
        _register_and_token(client, "badcsrf", "pass1234")
        refreshed = client.post("/api/auth/refresh", headers={"X-CSRF-Token": "invalid-token"})
        assert refreshed.status_code == 401

    def test_logout_requires_csrf(self, client):
        _register_and_token(client, "logoutcsrf", "pass1234")
        out = client.post("/api/auth/logout")
        assert out.status_code == 401

    def test_register_rejects_short_password(self, client):
        response = client.post("/api/auth/register", json={"username": "shortpwd", "password": "12345"})
        assert response.status_code == 422


class TestDetectionFlow:
    def test_detect_requires_auth(self, client):
        response = client.post(
            "/api/detect",
            files={"file": ("demo.jpg", _image_bytes(), "image/jpeg")},
        )
        assert response.status_code == 401

    def test_detect_progress_report(self, client):
        auth = _register_and_token(client, "bob", "pass1234")
        headers = auth["auth_headers"]

        detect = client.post(
            "/api/detect",
            files={"file": ("demo.jpg", _image_bytes(), "image/jpeg")},
            headers=headers,
        )
        assert detect.status_code == 200
        task_id = detect.json()["task_id"]
        assert detect.json()["queue_mode"] == "local"

        for _ in range(20):
            progress = client.get(f"/api/progress/{task_id}", headers=headers)
            assert progress.status_code == 200
            if progress.json()["status"] == "complete":
                break
            time.sleep(0.05)

        report = client.get(f"/api/report/{task_id}", headers=headers)
        assert report.status_code == 200
        payload = report.json()
        assert payload["method"] == "forensic"
        assert "details" in payload
        assert payload["forensic_score"] == 42.0

        unauthenticated = client.get(f"/api/uploads/{payload['artifacts']['ela_map']}")
        assert unauthenticated.status_code == 401

        media = client.get(f"/api/uploads/{payload['artifacts']['ela_map']}", headers=headers)
        assert media.status_code == 200

    def test_task_ownership_enforced(self, client):
        headers_owner = _register_and_token(client, "owner", "pass1234")["auth_headers"]
        headers_other = _register_and_token(client, "other", "pass1234")["auth_headers"]

        detect = client.post(
            "/api/detect",
            files={"file": ("secret.jpg", _image_bytes(), "image/jpeg")},
            headers=headers_owner,
        )
        task_id = detect.json()["task_id"]

        blocked = client.get(f"/api/progress/{task_id}", headers=headers_other)
        assert blocked.status_code == 404
