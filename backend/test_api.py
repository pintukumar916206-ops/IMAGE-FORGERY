import io
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
from backend.core.db import Base, engine


def _image_bytes():
    img_array = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    ok, img_bytes = cv2.imencode(".jpg", img_array)
    assert ok
    return io.BytesIO(img_bytes.tobytes())


def _register_and_get_token(client: TestClient, username: str, password: str):
    register_resp = client.post(
        "/api/auth/register",
        json={"username": username, "password": password},
    )
    assert register_resp.status_code in (200, 400)

    token_resp = client.post(
        "/api/auth/token",
        json={"username": username, "password": password},
    )
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def fake_pipeline(file_path: str, upload_dir: str):
        image_name = Path(file_path).name
        ela_name = f"{image_name}_ela_test.png"
        ela_path = Path(upload_dir) / ela_name
        ela_path.parent.mkdir(parents=True, exist_ok=True)
        ela_path.write_bytes(b"fake-image")
        return {
            "isForged": False,
            "verdict": "AUTHENTIC",
            "confidence": 74.2,
            "confidence_score": 0.26,
            "confidence_display": 74.2,
            "execution_time_ms": 11.5,
            "analyses": {
                "ela": {"map": ela_name, "score": 0.12},
                "copy_move": {"matches": 4, "status": "Clean"},
                "sift": {"matches": 4, "status": "Clean"},
                "wavelet_noise": {"entropy": 3.2},
                "cnn_inference": 0.25,
            },
        }

    monkeypatch.setattr(main_module, "run_forensic_pipeline", fake_pipeline)
    return TestClient(main_module.app)


class TestAuthAndDetect:
    def test_token_endpoint_returns_bearer_token(self, client):
        _, headers = _register_and_get_token(client, "alice", "pass123")
        assert "Authorization" in headers

    def test_detect_requires_auth(self, client):
        response = client.post(
            "/api/detect",
            files={"file": ("test.jpg", _image_bytes(), "image/jpeg")},
        )
        assert response.status_code == 401

    def test_detect_progress_report_happy_path(self, client):
        token, headers = _register_and_get_token(client, "bob", "pass123")

        detect_resp = client.post(
            "/api/detect",
            files={"file": ("test.jpg", _image_bytes(), "image/jpeg")},
            headers=headers,
        )
        assert detect_resp.status_code == 200
        payload = detect_resp.json()
        assert "task_id" in payload
        assert len(payload["sha256_hash"]) == 64

        task_id = payload["task_id"]

        status_payload = None
        for _ in range(10):
            status_resp = client.get(f"/api/progress/{task_id}", headers=headers)
            assert status_resp.status_code == 200
            status_payload = status_resp.json()
            if status_payload["status"] == "complete":
                break
            time.sleep(0.05)

        assert status_payload is not None
        assert status_payload["status"] == "complete"

        report_resp = client.get(f"/api/report/{task_id}", headers=headers)
        assert report_resp.status_code == 200
        report = report_resp.json()
        assert report["confidence"] == 74.2
        assert report["analyses"]["copy_move"]["matches"] == 4
        assert report["analyses"]["sift"]["matches"] == 4

        ela_file = report["analyses"]["ela"]["map"]
        media_resp = client.get(f"/api/uploads/{ela_file}?token={token}")
        assert media_resp.status_code == 200


class TestOwnershipEnforcement:
    def test_user_cannot_access_other_users_artifacts(self, client):
        token_a, headers_a = _register_and_get_token(client, "owner", "pass123")
        _, headers_b = _register_and_get_token(client, "intruder", "pass123")

        detect_resp = client.post(
            "/api/detect",
            files={"file": ("secret.jpg", _image_bytes(), "image/jpeg")},
            headers=headers_a,
        )
        assert detect_resp.status_code == 200
        task_id = detect_resp.json()["task_id"]

        progress_other = client.get(f"/api/progress/{task_id}", headers=headers_b)
        assert progress_other.status_code == 404

        report_other = client.get(f"/api/report/{task_id}", headers=headers_b)
        assert report_other.status_code == 404

        report_owner = client.get(f"/api/report/{task_id}", headers=headers_a)
        assert report_owner.status_code == 200
        ela_file = report_owner.json()["analyses"]["ela"]["map"]

        media_no_token = client.get(f"/api/uploads/{ela_file}")
        assert media_no_token.status_code == 401

        media_owner = client.get(f"/api/uploads/{ela_file}?token={token_a}")
        assert media_owner.status_code == 200
