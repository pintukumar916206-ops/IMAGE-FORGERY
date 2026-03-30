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

    def test_predict_bytes_returns_dict(self):
        res = self.detector.predict_bytes(b"fake_image_content")
        self.assertIn("score", res)
        self.assertIn("fallback_used", res)
        self.assertGreaterEqual(res["score"], 0.0)
        self.assertLessEqual(res["score"], 100.0)
        self.assertTrue(res["fallback_used"])

    def test_predict_real_image_bytes(self):
        img = Image.new('RGB', (100, 100), color = 'red')
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG')
        res = self.detector.predict_bytes(img_byte_arr.getvalue())
        self.assertGreaterEqual(res["score"], 0.0)
        self.assertLessEqual(res["score"], 100.0)
        self.assertTrue(res["fallback_used"])

    def test_predict_file_path(self):
        test_file = "test_dummy.jpg"
        with open(test_file, "wb") as f:
            f.write(b"abc")
        
        try:
            score = self.detector.predict_file_path(test_file)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 100.0)
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)

if __name__ == "__main__":
    unittest.main()
