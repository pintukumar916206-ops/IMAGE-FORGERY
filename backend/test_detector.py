import tempfile
from pathlib import Path

import cv2
import numpy as np

from backend.app.services.detector import run_forensic_analysis, validate_image


class TestValidateImage:
    def test_rejects_none(self):
        valid, code = validate_image(None)
        assert valid is False
        assert code == "ERR_INVALID_IMAGE"

    def test_rejects_tiny_image(self):
        image = np.zeros((32, 32, 3), dtype=np.uint8)
        valid, code = validate_image(image)
        assert valid is False
        assert code == "ERR_LOW_RESOLUTION"

    def test_rejects_oversized_image(self):
        image = np.zeros((5000, 5000, 3), dtype=np.uint8)
        valid, code = validate_image(image)
        assert valid is False
        assert code == "ERR_INVALID_IMAGE"


class TestAnalysisPipeline:
    def test_returns_analysis_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image = np.random.randint(0, 255, (400, 400, 3), dtype=np.uint8)
            file_path = str(Path(tmpdir) / "sample.jpg")
            cv2.imwrite(file_path, image)

            result = run_forensic_analysis(file_path, tmpdir)

        assert result["method"] == "forensic"
        assert 0.0 <= result["score"] <= 1.0
        assert 0.0 <= result["forensic_score"] <= 100.0
        assert "details" in result
        assert {"ela", "orb", "metadata", "wavelet"}.issubset(result["details"].keys())
        assert result["label"] in {"likely_tampered", "likely_authentic", "inconclusive"}

    def test_invalid_image_returns_error_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tiny = np.zeros((32, 32, 3), dtype=np.uint8)
            file_path = str(Path(tmpdir) / "tiny.jpg")
            cv2.imwrite(file_path, tiny)

            result = run_forensic_analysis(file_path, tmpdir)

        assert result["method"] == "forensic"
        assert result["label"] == "invalid_input"
        assert result["score"] == 0.0
        assert result["error"] == "ERR_LOW_RESOLUTION"

    def test_flags_extension_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            image = np.random.randint(0, 255, (320, 320, 3), dtype=np.uint8)
            png_path = Path(tmpdir) / "source.png"
            mismatch_path = Path(tmpdir) / "mismatch.jpg"
            cv2.imwrite(str(png_path), image)
            mismatch_path.write_bytes(png_path.read_bytes())

            result = run_forensic_analysis(str(mismatch_path), tmpdir)

        metadata_flags = result["analysis"]["metadata"]["flags"]
        assert any(flag.startswith("type_mismatch") for flag in metadata_flags)

    def test_score_stability_after_reencode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rng = np.random.default_rng(11)
            image = rng.integers(0, 255, size=(420, 420, 3), dtype=np.uint8)
            original_path = Path(tmpdir) / "original.jpg"
            reencoded_path = Path(tmpdir) / "reencoded.jpg"
            cv2.imwrite(str(original_path), image, [cv2.IMWRITE_JPEG_QUALITY, 96])
            reencoded = cv2.imread(str(original_path))
            cv2.imwrite(str(reencoded_path), reencoded, [cv2.IMWRITE_JPEG_QUALITY, 86])

            baseline = run_forensic_analysis(str(original_path), tmpdir)
            perturbed = run_forensic_analysis(str(reencoded_path), tmpdir)

        assert abs(float(baseline["score"]) - float(perturbed["score"])) <= 0.30
