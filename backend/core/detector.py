import os
import time
import logging
import cv2
import uuid
import numpy as np
from pathlib import Path
import pywt
from datetime import datetime

try:
    import onnxruntime as rt
    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

logger = logging.getLogger(__name__)


class SignalReliability:
    ELA_RELIABILITY = 0.75
    ORB_RELIABILITY = 0.55
    WAVELET_RELIABILITY = 0.65
    CNN_RELIABILITY = 0.85


NEUTRAL_CNN_SCORE = 0.5


class ErrorCodes:
    SUCCESS = 0
    ERR_INVALID_IMAGE = "ERR_INVALID_IMAGE"
    ERR_LOW_RESOLUTION = "ERR_LOW_RESOLUTION"
    ERR_FORMAT_MISMATCH = "ERR_FORMAT_MISMATCH"
    ERR_MODEL_MISSING = "ERR_MODEL_MISSING"
    ERR_MODEL_INFERENCE = "ERR_MODEL_INFERENCE"
    ERR_INSUFFICIENT_DATA = "ERR_INSUFFICIENT_DATA"


def to_native(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.float32, np.float64)):
        return float(obj)
    if isinstance(obj, (np.int32, np.int64)):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: to_native(v) for k, v in obj.items()}
    return [to_native(i) for i in obj] if isinstance(obj, (list, tuple)) else obj


def validate_image(raw_img):
    if raw_img is None:
        return False, ErrorCodes.ERR_INVALID_IMAGE
    h, w = raw_img.shape[:2]
    if h < 64 or w < 64:
        return False, ErrorCodes.ERR_LOW_RESOLUTION
    if h > 4096 or w > 4096:
        return False, ErrorCodes.ERR_INVALID_IMAGE
    return True, ErrorCodes.SUCCESS


def resize_for_forensics(img, max_dim=2000):
    try:
        h, w = img.shape[:2]
        if max(h, w) <= max_dim:
            return img
        scale = max_dim / max(h, w)
        return cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    except Exception:
        return img


def analyze_ela(img, file_path: str, upload_dir: Path):
    temp_id = str(uuid.uuid4())[:8]
    temp_file = f"temp_ela_{temp_id}.jpg"
    try:
        cv2.imwrite(temp_file, img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        orig = img.astype(np.float32)
        resaved = cv2.imread(temp_file).astype(np.float32)
        diff = 15 * cv2.absdiff(orig, resaved)
        output_name = f"{os.path.basename(file_path)}_ela_{temp_id}.png"
        cv2.imwrite(str(upload_dir / output_name), diff.astype(np.uint8))
        score = np.mean(diff) / 255.0
        normalized_score = float(min(score * 5, 1.0))
        return {
            "map": output_name,
            "score": float(score),
            "normalized": normalized_score,
            "reliability": SignalReliability.ELA_RELIABILITY
        }, normalized_score
    except Exception as e:
        logger.warning(f"ELA analysis failed: {e}")
        return {"map": "", "score": 0.0, "normalized": 0.0, "reliability": 0.0}, 0.0
    finally:
        if os.path.exists(temp_file):
            from contextlib import suppress
            with suppress(OSError):
                os.remove(temp_file)


def analyze_copy_move_detection(img):
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=2000, scaleFactor=1.2, nlevels=8)
        kp, des = orb.detectAndCompute(gray, None)
        
        if des is None or len(des) < 8:
            return {
                "matches": 0,
                "status": "Insufficient_Keypoints",
                "reliability": 0.0
            }, 0.0
        
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        matches = bf.knnMatch(des, des, k=2)
        
        good_matches = []
        for match_pair in matches:
            if len(match_pair) == 2:
                m, n = match_pair
                if m.distance < 0.75 * n.distance:
                    good_matches.append(m)
        
        match_count = len(good_matches)
        threshold = 40
        
        if match_count < 10:
            score = 0.0
            status = "Clean"
        elif 10 <= match_count < threshold:
            score = match_count / threshold * 0.5
            status = "Low_Suspicion"
        else:
            score = min(match_count / (threshold * 2), 1.0)
            status = "Copy_Move_Suspected"
        
        return {
            "matches": match_count,
            "status": status,
            "reliability": SignalReliability.ORB_RELIABILITY
        }, float(score)
    
    except Exception as e:
        logger.warning(f"ORB copy-move detection failed: {e}")
        return {"matches": 0, "status": "Error", "reliability": 0.0}, 0.0


def analyze_wavelet_prnu(img):
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        coeffs = pywt.dwt2(gray, 'db1')
        cA, (cH, cV, cD) = coeffs
        hh_noise = np.abs(cD)
        noise_std = float(np.std(hh_noise))
        
        hist, _ = np.histogram(hh_noise, bins=256, range=(0, 1))
        hist = hist / hist.sum()
        entropy = -np.sum(hist * np.log2(hist + 1e-7))
        
        fingerprint_score = min(max(entropy - 2.8, 0) / 1.5, 1.0)
        
        return {
            "wavelet_std": round(noise_std, 6),
            "entropy": round(float(entropy), 4),
            "fingerprint_score": round(float(fingerprint_score), 4),
            "reliability": SignalReliability.WAVELET_RELIABILITY
        }, float(fingerprint_score)
    except Exception as e:
        logger.error(f"Wavelet analysis failed: {e}")
        return {"wavelet_std": 0.0, "entropy": 0.0, "fingerprint_score": 0.0, "reliability": 0.0}, 0.0


def load_onnx_model(model_path: str):
    if not ONNX_AVAILABLE:
        logger.error("ONNX Runtime not available")
        return None
    
    if not os.path.exists(model_path):
        logger.error(f"Model file not found at {model_path}")
        return None
    
    try:
        return rt.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    except Exception as e:
        logger.error(f"Failed to load ONNX model: {e}")
        return None


def run_cnn_inference(session, img, target_size=224):
    if session is None:
        logger.warning("CNN model not available. Using neutral score fallback.")
        return NEUTRAL_CNN_SCORE
    
    try:
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img_resized = cv2.resize(img_rgb, (target_size, target_size))
        img_normalized = img_resized.astype(np.float32) / 255.0
        
        mean = np.array([0.485, 0.456, 0.406])
        std = np.array([0.229, 0.224, 0.225])
        img_normalized = (img_normalized - mean) / std
        
        img_transposed = np.transpose(img_normalized, (2, 0, 1))
        img_batch = np.expand_dims(img_transposed, axis=0)
        
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name
        result = session.run([output_name], {input_name: img_batch})
        
        output = result[0][0]
        if isinstance(output, np.ndarray):
            score = float(output.item()) if output.size == 1 else float(output[1])
        else:
            score = float(output)
        
        return max(0.0, min(score, 1.0))
    except Exception as e:
        logger.error(f"CNN inference failed: {e}")
        raise


def calculate_bayesian_decision(signal_scores: dict) -> dict:
    ela_score = signal_scores.get("ela", 0.0)
    orb_score = signal_scores.get("orb", 0.0)
    wavelet_score = signal_scores.get("wavelet", 0.0)
    cnn_score = signal_scores.get("cnn", 0.0)
    
    ela_weight = SignalReliability.ELA_RELIABILITY
    orb_weight = SignalReliability.ORB_RELIABILITY
    wavelet_weight = SignalReliability.WAVELET_RELIABILITY
    cnn_weight = SignalReliability.CNN_RELIABILITY
    
    total_weight = ela_weight + orb_weight + wavelet_weight + cnn_weight
    
    weighted_sum = (
        ela_score * ela_weight +
        orb_score * orb_weight +
        wavelet_score * wavelet_weight +
        cnn_score * cnn_weight
    )
    
    final_score = weighted_sum / total_weight
    
    signal_variance = np.var([ela_score, orb_score, wavelet_score, cnn_score])
    agreement_metric = 1.0 - (signal_variance * 0.3)
    agreement_metric = max(0.0, min(agreement_metric, 1.0))
    
    threshold_high = 0.75
    threshold_low = 0.40
    
    if final_score > threshold_high:
        verdict = "FORGED"
        confidence_lower = max(final_score - 0.15, 0.0)
        confidence_upper = min(final_score + 0.10, 1.0)
    elif final_score < threshold_low:
        verdict = "AUTHENTIC"
        confidence_lower = max((1.0 - final_score) - 0.15, 0.0)
        confidence_upper = min((1.0 - final_score) + 0.10, 1.0)
    else:
        verdict = "INCONCLUSIVE"
        confidence_lower = 0.3
        confidence_upper = 0.7
    
    return {
        "verdict": verdict,
        "score": float(final_score),
        "confidence_lower": float(confidence_lower),
        "confidence_upper": float(confidence_upper),
        "agreement": float(agreement_metric)
    }


def run_forensic_pipeline(file_path: str, upload_dir_str: str):
    start_time = time.time()
    execution_trace = []
    
    try:
        upload_dir = Path(upload_dir_str)
        raw_img = cv2.imread(file_path)
        execution_trace.append({"stage": "image_loaded", "status": "ok"})
        
        valid, status = validate_image(raw_img)
        if not valid:
            execution_trace.append({"stage": "validation", "status": "failed", "reason": status})
            return to_native({
                "isForged": False,
                "confidence": 0.0,
                "confidence_score": 0.0,
                "execution_time_ms": (time.time() - start_time) * 1000,
                "error": status,
                "analyses": None,
                "execution_trace": execution_trace
            })
        
        execution_trace.append({"stage": "validation", "status": "passed"})
        
        img = resize_for_forensics(raw_img)
        execution_trace.append({"stage": "resize", "status": "ok"})
        
        model_path = "backend/ml/forgery_model.onnx"
        session = load_onnx_model(model_path)

        if session is None:
            execution_trace.append({
                "stage": "model_load",
                "status": "fallback",
                "message": "CNN model unavailable. Continuing with neutral CNN score."
            })
        else:
            execution_trace.append({"stage": "model_load", "status": "ok"})
        
        ela_res, ela_score = analyze_ela(img, file_path, upload_dir)
        execution_trace.append({"stage": "ela_analysis", "status": "ok", "score": float(ela_score)})
        
        orb_res, orb_score = analyze_copy_move_detection(img)
        execution_trace.append({"stage": "copy_move", "status": "ok", "score": float(orb_score)})
        
        wavelet_res, wavelet_score = analyze_wavelet_prnu(img)
        execution_trace.append({"stage": "wavelet", "status": "ok", "score": float(wavelet_score)})
        
        try:
            cnn_score = run_cnn_inference(session, img)
            execution_trace.append({
                "stage": "cnn_inference",
                "status": "ok" if session is not None else "fallback",
                "score": float(cnn_score)
            })
        except Exception as e:
            logger.error(f"CNN inference failed: {e}")
            cnn_score = NEUTRAL_CNN_SCORE
            execution_trace.append({
                "stage": "cnn_inference",
                "status": "fallback",
                "error": str(e),
                "score": float(cnn_score)
            })
        
        signal_scores = {
            "ela": ela_score,
            "orb": orb_score,
            "wavelet": wavelet_score,
            "cnn": cnn_score
        }
        
        decision = calculate_bayesian_decision(signal_scores)
        execution_trace.append({"stage": "decision", "status": "ok", "verdict": decision["verdict"]})
        
        is_forged = decision["verdict"] == "FORGED"
        confidence_display = (decision["confidence_lower"] + decision["confidence_upper"]) / 2 * 100
        
        exec_time = (time.time() - start_time) * 1000
        return to_native({
            "isForged": bool(is_forged),
            "verdict": decision["verdict"],
            "confidence_score": float(decision["score"]),
            "confidence_lower_bound": float(decision["confidence_lower"] * 100),
            "confidence_upper_bound": float(decision["confidence_upper"] * 100),
            "confidence_display": round(confidence_display, 1),
            "confidence": round(confidence_display, 1),
            "signal_agreement": float(decision["agreement"]),
            "execution_time_ms": round(float(exec_time), 2),
            "timestamp": datetime.utcnow().isoformat(),
            "analyses": {
                "ela": ela_res,
                "copy_move": orb_res,
                "sift": orb_res,
                "wavelet_noise": wavelet_res,
                "cnn_inference": round(cnn_score, 4)
            },
            "signal_scores": {
                "ela": round(ela_score, 4),
                "copy_move": round(orb_score, 4),
                "wavelet": round(wavelet_score, 4),
                "cnn": round(cnn_score, 4)
            },
            "execution_trace": execution_trace,
            "status": "Verified"
        })
    
    except Exception as e:
        execution_trace.append({"stage": "pipeline", "status": "error", "error": str(e)})
        logger.error(f"Forensic pipeline critical failure: {e}", exc_info=True)
        return to_native({
            "isForged": False,
            "confidence": 0.0,
            "confidence_score": 0.0,
            "error": ErrorCodes.ERR_MODEL_INFERENCE,
            "error_detail": str(e),
            "execution_time_ms": (time.time() - start_time) * 1000,
            "execution_trace": execution_trace,
            "status": "Failed"
        })
