import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

from backend.core import detector


def _write_test_image(tmpdir: str, filename: str = "sample.jpg") -> str:
    img = np.random.randint(0, 256, (256, 256, 3), dtype=np.uint8)
    file_path = os.path.join(tmpdir, filename)
    ok = cv2.imwrite(file_path, img)
    assert ok
    return file_path


class TestValidateImage:
    def test_rejects_none(self):
        valid, status = detector.validate_image(None)
        assert valid is False
        assert status == detector.ErrorCodes.ERR_INVALID_IMAGE

    def test_rejects_tiny_images(self):
        img = np.zeros((32, 32, 3), dtype=np.uint8)
        valid, status = detector.validate_image(img)
        assert valid is False
        assert status == detector.ErrorCodes.ERR_LOW_RESOLUTION

    def test_rejects_oversized_images(self):
        img = np.zeros((5000, 5000, 3), dtype=np.uint8)
        valid, status = detector.validate_image(img)
        assert valid is False
        assert status == detector.ErrorCodes.ERR_INVALID_IMAGE

    def test_accepts_supported_size(self):
        img = np.zeros((1024, 1024, 3), dtype=np.uint8)
        valid, status = detector.validate_image(img)
        assert valid is True
        assert status == detector.ErrorCodes.SUCCESS


class TestCNNFallback:
    def test_run_cnn_inference_returns_neutral_without_model(self):
        img = np.zeros((224, 224, 3), dtype=np.uint8)
        score = detector.run_cnn_inference(None, img)
        assert score == detector.NEUTRAL_CNN_SCORE


class TestForensicPipeline:
    def test_pipeline_runs_without_model_using_neutral_fallback(self, monkeypatch):
        monkeypatch.setattr(detector, "load_onnx_model", lambda *_args, **_kwargs: None)

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = _write_test_image(tmpdir, "input.jpg")
            Path(tmpdir).mkdir(parents=True, exist_ok=True)

            result = detector.run_forensic_pipeline(file_path, tmpdir)

        assert "error" not in result
        assert result["isForged"] in (True, False)
        assert 0.0 <= result["confidence"] <= 100.0
        assert result["analyses"]["cnn_inference"] == detector.NEUTRAL_CNN_SCORE
        assert "copy_move" in result["analyses"]
        assert "sift" in result["analyses"]

    def test_pipeline_returns_error_for_invalid_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tiny = np.zeros((32, 32, 3), dtype=np.uint8)
            file_path = os.path.join(tmpdir, "tiny.jpg")
            ok = cv2.imwrite(file_path, tiny)
            assert ok

            result = detector.run_forensic_pipeline(file_path, tmpdir)

        assert result["isForged"] is False
        assert result["confidence"] == 0.0
        assert result["error"] == detector.ErrorCodes.ERR_LOW_RESOLUTION
