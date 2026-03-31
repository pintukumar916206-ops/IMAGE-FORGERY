import io
import logging
import os
import numpy as np
from PIL import Image, ImageChops, ImageEnhance

logger = logging.getLogger(__name__)

class MLDetector:
    def __init__(self, model_path: str = "backend/ml/forgery_model.onnx"):
        self.model_path = model_path
        self.model = None
        self.fallback_used = False
        self.input_name = None
        self.output_name = None
        
        try:
            import onnxruntime as ort
            if os.path.exists(self.model_path):
                self.model = ort.InferenceSession(self.model_path, providers=["CPUExecutionProvider"])
                self.input_name = self.model.get_inputs()[0].name
                self.output_name = self.model.get_outputs()[0].name
                logger.debug(f"Loaded model from {self.model_path}")
            else:
                self.fallback_used = True
        except Exception as exc:
            logger.warning(f"ONNX initialization failed: {exc}")
            self.fallback_used = True

    def _ela_array(self, file_path: str, size: int = 224) -> np.ndarray:
        img = Image.open(file_path).convert("RGB").resize((size, size))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        buf.seek(0)
        recompressed = Image.open(buf)
        diff = ImageChops.difference(img, recompressed)
        extrema = diff.getextrema()
        max_diff = max(ex[1] for ex in extrema) or 1
        scale = 255.0 / max_diff
        ela = np.asarray(ImageEnhance.Brightness(diff).enhance(scale), dtype=np.float32) / 255.0
        return ela

    def _preprocess(self, file_path: str) -> np.ndarray:
        ela = self._ela_array(file_path)
        tensor = np.transpose(ela, (2, 0, 1))
        return np.expand_dims(tensor, axis=0).astype(np.float32)

    def _calculate_heuristic_score(self, file_path: str) -> float:
        try:
            ela = self._ela_array(file_path)
            score = float(np.std(ela) * 2.2)
            return min(100.0, max(0.0, score))
        except Exception:
            return 0.0

    def predict_file(self, file_path: str) -> dict:
        if self.model and self.input_name and self.output_name:
            try:
                input_tensor = self._preprocess(file_path)
                raw_output = self.model.run([self.output_name], {self.input_name: input_tensor})[0]
                score = float(np.squeeze(raw_output))
                if score <= 1.0:
                    score *= 100.0
                score = max(0.0, min(100.0, score))
                return {
                    "score": round(score, 2), 
                    "method": "Neural Network",
                    "fallback_used": False
                }
            except Exception as exc:
                logger.error(f"Inference task failed: {exc}")
        
        return {
            "score": round(self._calculate_heuristic_score(file_path), 2),
            "method": "Heuristic ELA Variance",
            "fallback_used": True
        }
