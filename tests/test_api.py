import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.core.config import settings
from backend.core.detector import ForgeryDetector
from backend.core.ml_detector import MLDetector
from backend.main import app


def _make_test_image_bytes() -> bytes:
    image = Image.new("RGB", (64, 64), color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _get_auth_headers(client: TestClient) -> dict:
    response = client.post(
        "/api/token",
        data={"username": settings.ANALYST_USERNAME, "password": settings.ANALYST_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def enforce_auth_sync_mode():
    original_auth = settings.API_KEY_REQUIRED
    original_sync = settings.SYNC_MODE
    settings.API_KEY_REQUIRED = True
    settings.SYNC_MODE = True
    yield
    settings.API_KEY_REQUIRED = original_auth
    settings.SYNC_MODE = original_sync


def test_token_rejects_invalid_credentials():
    client = TestClient(app)
    response = client.post("/api/token", data={"username": "bad", "password": "bad"})
    assert response.status_code == 401


def test_detect_requires_auth(enforce_auth_sync_mode):
    client = TestClient(app)
    response = client.post(
        "/api/detect",
        files={"file": ("sample.jpg", _make_test_image_bytes(), "image/jpeg")},
    )
    assert response.status_code == 401


def test_detect_sync_with_auth_returns_report(enforce_auth_sync_mode, monkeypatch):
    def fake_predict_file(self, file_path):  # noqa: ARG001
        return {"score": 11.0, "fallback_used": True}

    def fake_detect_file(self, file_path, ml_result=None):  # noqa: ARG001
        return {
            "is_forged": False,
            "confidence": 12,
            "reasons": ["No structural anomalies detected."],
            "evidence": {
                "exif": {"has_metadata": False, "warnings": [], "software_signature": "None"},
                "ela": {"is_forged": False, "anomaly_score": 2.0, "ela_heatmap_b64": None},
                "sift": {"is_forged": False, "clone_clusters_found": 0, "sift_heatmap_b64": None},
                "ml": ml_result or {"score": 0.0, "fallback_used": True},
            },
        }

    monkeypatch.setattr(MLDetector, "predict_file", fake_predict_file)
    monkeypatch.setattr(ForgeryDetector, "detect_file", fake_detect_file)

    client = TestClient(app)
    headers = _get_auth_headers(client)

    detect_response = client.post(
        "/api/detect",
        files={"file": ("sample.jpg", _make_test_image_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert detect_response.status_code == 200

    payload = detect_response.json()
    task_id = payload["task_id"]

    progress_response = client.get(f"/api/progress/{task_id}", headers=headers)
    assert progress_response.status_code == 200
    assert progress_response.json()["status"] == "complete"

    report_response = client.get(f"/api/report/{task_id}", headers=headers)
    assert report_response.status_code == 200
    assert report_response.json()["is_forged"] is False


