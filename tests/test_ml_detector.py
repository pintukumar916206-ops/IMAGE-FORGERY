import unittest
from backend.core.ml_detector import MLDetector
import os
import io
from PIL import Image

class TestMLDetector(unittest.TestCase):
    def setUp(self):
        self.detector = MLDetector(model_path="non_existent.onnx")

    def test_fallback_flag(self):
        self.assertTrue(self.detector.fallback_used)

    def test_predict_file_returns_dict(self):
        test_file = "test_dummy_dict.jpg"
        with open(test_file, "wb") as f:
            f.write(b"fake_image_content")
        try:
            res = self.detector.predict_file(test_file)
            self.assertIn("score", res)
            self.assertIn("fallback_used", res)
            self.assertGreaterEqual(res["score"], 0.0)
            self.assertLessEqual(res["score"], 100.0)
            self.assertTrue(res["fallback_used"])
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

    def test_predict_real_image_file(self):
        img = Image.new('RGB', (100, 100), color = 'red')
        test_file = "test_dummy_real.jpg"
        img.save(test_file, format='JPEG')
        try:
            res = self.detector.predict_file(test_file)
            self.assertGreaterEqual(res["score"], 0.0)
            self.assertLessEqual(res["score"], 100.0)
            self.assertTrue(res["fallback_used"])
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
