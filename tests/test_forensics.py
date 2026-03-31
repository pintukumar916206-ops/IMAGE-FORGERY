import io
import os
import sys
import tempfile

import numpy as np
import pytest
from PIL import Image, ImageChops, ImageEnhance

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from backend.core.ml_detector import MLDetector

def make_authentic_arr(size=224, seed=1):
    rng = np.random.default_rng(seed)
    x = np.linspace(80, 180, size).reshape(1, size, 1)
    y = np.linspace(80, 180, size).reshape(size, 1, 1)
    base = np.zeros((size, size, 3), dtype=np.float32)
    base[:, :, 0] = (x * 0.7 + y * 0.3).squeeze()
    base[:, :, 1] = (x * 0.4 + y * 0.6).squeeze()
    base[:, :, 2] = (x * 0.5 + y * 0.5).squeeze()
    noise = rng.normal(0, 3, (size, size, 3))
    img = np.clip(base + noise, 0, 255).astype(np.uint8)
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, "JPEG", quality=92)
    buf.seek(0)
    return np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)

def make_forged_arr(authentic_arr, size=224):
    result = authentic_arr.copy()
    src = Image.fromarray(authentic_arr[5:75, 5:75])
    src = src.resize((35, 35), Image.BICUBIC).resize((70, 70), Image.BICUBIC)
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=65)
    buf.seek(0)
    patch = np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)
    result[120:190, 120:190] = patch
    return result

def score_arr(arr):
    det = MLDetector()
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=92)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        tf.write(buf.getvalue())
        tmp_path = tf.name
    try:
        return det.predict_file(tmp_path)["score"]
    finally:
        os.unlink(tmp_path)

def test_forged_scores_higher_than_authentic():
    auth = make_authentic_arr(seed=1)
    forg = make_forged_arr(auth)
    auth_score = score_arr(auth)
    forg_score = score_arr(forg)
    assert forg_score > auth_score, (
        f"forged={forg_score:.1f} should exceed authentic={auth_score:.1f}"
    )

def test_authentic_score_below_midpoint():
    auth = make_authentic_arr(seed=42)
    score = score_arr(auth)
    assert score < 60, f"authentic image scored too high: {score:.1f}"

def test_predict_returns_required_keys():
    auth = make_authentic_arr(seed=7)
    det = MLDetector()
    buf = io.BytesIO()
    Image.fromarray(auth).save(buf, "JPEG", quality=92)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        tf.write(buf.getvalue())
        tmp_path = tf.name
    try:
        result = det.predict_file(tmp_path)
    finally:
        os.unlink(tmp_path)
    assert "score" in result
    assert "fallback_used" in result
    assert "hard_metrics" in result
    assert 0.0 <= result["score"] <= 100.0
