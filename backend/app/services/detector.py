from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

import cv2
import numpy as np
import pywt
from PIL import Image, UnidentifiedImageError

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

FORMAT_ALIASES = {
    "jpg": "jpeg",
    "jpe": "jpeg",
    "tif": "tiff",
}
DEFAULT_WEIGHTS = {
    "ela": 0.35,
    "orb": 0.30,
    "wavelet": 0.25,
    "metadata": 0.10,
}
DEFAULT_THRESHOLDS = {
    "authentic": 0.38,
    "tampered": 0.62,
}
DEFAULT_AGREEMENT_MARGINS = {
    "tight": 0.08,
    "normal": 0.12,
    "loose": 0.18,
}
DEFAULT_SPREAD_CUTOFFS = {
    "tight": 0.15,
    "loose": 0.35,
}


@dataclass(frozen=True)
class CalibrationProfile:
    version: str
    source: str
    weights: Dict[str, float]
    thresholds: Dict[str, float]
    agreement_margins: Dict[str, float]
    spread_cutoffs: Dict[str, float]


def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _normalize(value: float, lower: float, upper: float) -> float:
    if upper <= lower:
        return 0.0
    return _clamp01((value - lower) / (upper - lower))


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    normalized = {key: max(0.0, float(weights.get(key, 0.0))) for key in DEFAULT_WEIGHTS}
    total = sum(normalized.values())
    if total <= 0:
        return DEFAULT_WEIGHTS.copy()
    return {key: value / total for key, value in normalized.items()}


def _sanitize_thresholds(thresholds: Dict[str, float]) -> Dict[str, float]:
    authentic = _clamp01(float(thresholds.get("authentic", DEFAULT_THRESHOLDS["authentic"])))
    tampered = _clamp01(float(thresholds.get("tampered", DEFAULT_THRESHOLDS["tampered"])))
    if authentic > tampered:
        authentic, tampered = tampered, authentic
    if tampered - authentic < 0.05:
        midpoint = (authentic + tampered) / 2
        authentic = _clamp01(midpoint - 0.03)
        tampered = _clamp01(midpoint + 0.03)
    return {"authentic": authentic, "tampered": tampered}


def _sanitize_margins(raw_margins: Dict[str, float]) -> Dict[str, float]:
    margins = {key: _clamp01(float(raw_margins.get(key, DEFAULT_AGREEMENT_MARGINS[key]))) for key in DEFAULT_AGREEMENT_MARGINS}
    ordered = sorted(margins.values())
    return {
        "tight": ordered[0],
        "normal": ordered[1],
        "loose": ordered[2],
    }


def _sanitize_spread_cutoffs(raw_cutoffs: Dict[str, float]) -> Dict[str, float]:
    tight = _clamp01(float(raw_cutoffs.get("tight", DEFAULT_SPREAD_CUTOFFS["tight"])))
    loose = _clamp01(float(raw_cutoffs.get("loose", DEFAULT_SPREAD_CUTOFFS["loose"])))
    if tight > loose:
        tight, loose = loose, tight
    return {"tight": tight, "loose": loose}


def _default_calibration() -> CalibrationProfile:
    return CalibrationProfile(
        version="fallback",
        source="defaults",
        weights=DEFAULT_WEIGHTS.copy(),
        thresholds=DEFAULT_THRESHOLDS.copy(),
        agreement_margins=DEFAULT_AGREEMENT_MARGINS.copy(),
        spread_cutoffs=DEFAULT_SPREAD_CUTOFFS.copy(),
    )


@lru_cache(maxsize=1)
def _load_calibration_profile(calibration_path: str) -> CalibrationProfile:
    profile = _default_calibration()
    path = Path(calibration_path)
    if not path.exists():
        logger.warning("Calibration file missing at %s. Using fallback profile.", path)
        return profile
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CalibrationProfile(
            version=str(payload.get("version", "unknown")),
            source=str(payload.get("source", "validation")),
            weights=_normalize_weights(payload.get("weights", {})),
            thresholds=_sanitize_thresholds(payload.get("thresholds", {})),
            agreement_margins=_sanitize_margins(payload.get("agreement_margins", {})),
            spread_cutoffs=_sanitize_spread_cutoffs(payload.get("spread_cutoffs", {})),
        )
    except Exception as exc:
        logger.error("Failed to load calibration profile: %s", exc)
        return profile


def get_calibration_profile() -> CalibrationProfile:
    return _load_calibration_profile(str(Path(settings.CALIBRATION_PATH)))


def validate_image(raw_img) -> Tuple[bool, str]:
    if raw_img is None:
        return False, "ERR_INVALID_IMAGE"
    height, width = raw_img.shape[:2]
    if height < 64 or width < 64:
        return False, "ERR_LOW_RESOLUTION"
    if height > 4096 or width > 4096:
        return False, "ERR_INVALID_IMAGE"
    return True, "SUCCESS"


def resize_for_analysis(img, max_dim: int = 2000):
    height, width = img.shape[:2]
    if max(height, width) <= max_dim:
        return img
    scale = max_dim / max(height, width)
    return cv2.resize(img, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA)


def analyze_ela(img, file_path: str, upload_dir: Path) -> Tuple[Dict[str, float], float]:
    temp_id = str(uuid.uuid4())[:8]
    temp_file = upload_dir / f"ela_temp_{temp_id}.jpg"
    output_name = f"{Path(file_path).name}_ela_{temp_id}.png"
    output_path = upload_dir / output_name
    try:
        cv2.imwrite(str(temp_file), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        original = img.astype(np.float32)
        recompressed = cv2.imread(str(temp_file)).astype(np.float32)
        diff = cv2.absdiff(original, recompressed)
        diff_scaled = np.clip(diff * 12.0, 0, 255).astype(np.uint8)
        cv2.imwrite(str(output_path), diff_scaled)

        mean_diff = float(np.mean(diff))
        score = _normalize(mean_diff, lower=1.5, upper=26.0)
        return {"score": round(score, 4), "mean_diff": round(mean_diff, 4), "map": output_name}, score
    except Exception as exc:
        logger.warning("ELA analysis failed: %s", exc)
        return {"score": 0.0, "mean_diff": 0.0, "map": ""}, 0.0
    finally:
        with suppress(OSError):
            temp_file.unlink()


def analyze_feature_match(img) -> Tuple[Dict[str, float], float]:
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=2000, scaleFactor=1.2, nlevels=8)
        keypoints, descriptors = orb.detectAndCompute(gray, None)

        if descriptors is None or len(descriptors) < 12:
            return {"score": 0.0, "matches": 0, "status": "insufficient_keypoints"}, 0.0

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        candidates = matcher.knnMatch(descriptors, descriptors, k=4)

        min_shift = max(10.0, min(gray.shape[:2]) * 0.03)
        pairs = []
        bins = []

        for query_index, neighbors in enumerate(candidates):
            if not neighbors:
                continue
            filtered = [match for match in neighbors if match.trainIdx != query_index]
            if len(filtered) < 2:
                continue
            first, second = filtered[0], filtered[1]
            if first.distance >= 0.78 * second.distance:
                continue
            query_point = keypoints[first.queryIdx].pt
            train_point = keypoints[first.trainIdx].pt
            shift = float(np.hypot(train_point[0] - query_point[0], train_point[1] - query_point[1]))
            if shift < min_shift:
                continue
            pairs.append((query_point, train_point, float(first.distance)))
            vector_bin = tuple(np.round((np.array(train_point) - np.array(query_point)) / 8.0).astype(int).tolist())
            bins.append(vector_bin)

        if len(pairs) < 6:
            return {
                "score": 0.0,
                "matches": int(len(pairs)),
                "keypoints": int(len(keypoints)),
                "coherent_matches": 0,
                "status": "insufficient_pairs",
            }, 0.0

        counts: Dict[Tuple[int, int], int] = {}
        for vector_bin in bins:
            counts[vector_bin] = counts.get(vector_bin, 0) + 1

        dominant_bin, _ = max(counts.items(), key=lambda item: item[1])
        dominant_pairs = [pair for pair, vector_bin in zip(pairs, bins) if vector_bin == dominant_bin]
        coherent_matches = len(dominant_pairs)
        if len(dominant_pairs) >= 6:
            source = np.float32([pair[0] for pair in dominant_pairs]).reshape(-1, 1, 2)
            target = np.float32([pair[1] for pair in dominant_pairs]).reshape(-1, 1, 2)
            _, inliers = cv2.estimateAffinePartial2D(
                source,
                target,
                method=cv2.RANSAC,
                ransacReprojThreshold=3.0,
                maxIters=2000,
                confidence=0.99,
            )
            if inliers is not None:
                coherent_matches = int(inliers.sum())

        coherence = coherent_matches / max(1, len(pairs))
        dominant_ratio = len(dominant_pairs) / max(1, len(pairs))
        score = _clamp01(
            0.40 * _normalize(float(coherent_matches), lower=4.0, upper=50.0)
            + 0.30 * coherence
            + 0.20 * _normalize(float(len(pairs)), lower=8.0, upper=120.0)
            + 0.10 * _normalize(dominant_ratio, lower=0.25, upper=0.95)
        )

        if score < 0.2:
            status = "clean"
        elif score < 0.5:
            status = "weak_repeat_pattern"
        elif score < 0.75:
            status = "possible_copy_move"
        else:
            status = "strong_copy_move"

        return {
            "score": round(score, 4),
            "matches": int(len(pairs)),
            "keypoints": int(len(keypoints)),
            "coherent_matches": int(coherent_matches),
            "dominant_shift": {"dx": float(dominant_bin[0] * 8), "dy": float(dominant_bin[1] * 8)},
            "status": status,
        }, score
    except Exception as exc:
        logger.warning("Feature match analysis failed: %s", exc)
        return {"score": 0.0, "matches": 0, "status": "error"}, 0.0


def analyze_wavelet_noise(img) -> Tuple[Dict[str, float], float]:
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
        _, (_, _, cD) = pywt.dwt2(gray, "db2")
        high_band = np.abs(cD)

        entropy_hist, _ = np.histogram(high_band, bins=128, range=(0, 1))
        entropy_hist = entropy_hist / max(float(entropy_hist.sum()), 1.0)
        entropy = -np.sum(entropy_hist * np.log2(entropy_hist + 1e-8))
        std_dev = float(np.std(high_band))

        score = _normalize(float(entropy), lower=2.7, upper=4.7)
        return {"score": round(score, 4), "entropy": round(float(entropy), 4), "std_dev": round(std_dev, 6)}, score
    except Exception as exc:
        logger.warning("Wavelet analysis failed: %s", exc)
        return {"score": 0.0, "entropy": 0.0, "std_dev": 0.0}, 0.0


def _normalize_extension(extension: str) -> str:
    stripped = extension.lower().lstrip(".")
    return FORMAT_ALIASES.get(stripped, stripped)


def _detect_image_type(file_path: str) -> str:
    try:
        with Image.open(file_path) as image:
            detected = (image.format or "").lower().strip()
            return _normalize_extension(detected) if detected else "unknown"
    except (UnidentifiedImageError, OSError, ValueError):
        return "unknown"


def analyze_metadata_flags(file_path: str) -> Tuple[Dict[str, object], float]:
    extension = _normalize_extension(Path(file_path).suffix)
    detected_type = _detect_image_type(file_path)
    flags = []
    if detected_type == "unknown":
        flags.append("unknown_binary_signature")
    elif detected_type != extension:
        flags.append(f"type_mismatch:{extension}->{detected_type}")
    metadata_score = _clamp01(len(flags) * 0.6)
    return {
        "score": round(metadata_score, 4),
        "detected_type": detected_type,
        "file_extension": extension or "none",
        "flags": flags,
    }, metadata_score


def _label_from_score(score: float, thresholds: Dict[str, float]) -> str:
    if score >= thresholds["tampered"]:
        return "likely_tampered"
    if score <= thresholds["authentic"]:
        return "likely_authentic"
    return "inconclusive"


def _calculate_weighted_score(
    scores: Dict[str, float],
    weights: Dict[str, float],
    agreement_margins: Dict[str, float],
    spread_cutoffs: Dict[str, float],
) -> Tuple[float, Dict[str, object]]:
    weighted_sum = 0.0
    weight_sum = 0.0
    signal_breakdown = []
    for signal_name, score in scores.items():
        weight = weights.get(signal_name, 0.0)
        weighted_sum += score * weight
        weight_sum += weight
        signal_breakdown.append(
            {
                "signal": signal_name,
                "score": round(score, 4),
                "weight": round(weight, 4),
                "contribution": round(score * weight, 4),
            }
        )

    weighted_score = weighted_sum / weight_sum if weight_sum > 0 else 0.5
    median_score = float(np.median(list(scores.values()))) if scores else 0.5
    final_score = _clamp01((0.8 * weighted_score) + (0.2 * median_score))

    min_score = min(scores.values()) if scores else 0.5
    max_score = max(scores.values()) if scores else 0.5
    signal_spread = max_score - min_score

    if signal_spread <= spread_cutoffs["tight"]:
        agreement_band = "tight"
    elif signal_spread >= spread_cutoffs["loose"]:
        agreement_band = "loose"
    else:
        agreement_band = "normal"

    agreement_margin = agreement_margins.get(agreement_band, agreement_margins["normal"])
    lower_bound = _clamp01(final_score - agreement_margin)
    upper_bound = _clamp01(final_score + agreement_margin)

    return final_score, {
        "lower_bound": round(lower_bound, 4),
        "upper_bound": round(upper_bound, 4),
        "signal_spread": round(signal_spread, 4),
        "agreement_band": agreement_band,
        "agreement_margin": round(agreement_margin, 4),
        "signal_breakdown": signal_breakdown,
    }


def run_forensic_analysis(file_path: str, upload_dir_str: str) -> Dict[str, object]:
    start = time.time()
    execution_trace = []
    upload_dir = Path(upload_dir_str)
    upload_dir.mkdir(parents=True, exist_ok=True)
    calibration = get_calibration_profile()
    try:
        raw_img = cv2.imread(file_path)
        execution_trace.append({"stage": "load_image", "status": "ok"})

        valid, code = validate_image(raw_img)
        if not valid:
            execution_trace.append({"stage": "validate", "status": "failed", "error": code})
            return {
                "method": "forensic",
                "score": 0.0,
                "forensic_score": 0.0,
                "label": "invalid_input",
                "details": {},
                "artifacts": {},
                "error": code,
                "execution_time_ms": round((time.time() - start) * 1000, 2),
                "execution_trace": execution_trace,
            }

        img = resize_for_analysis(raw_img)
        execution_trace.append({"stage": "resize", "status": "ok"})

        ela_result, ela_score = analyze_ela(img, file_path, upload_dir)
        execution_trace.append({"stage": "ela", "status": "ok", "score": round(ela_score, 4)})

        orb_result, orb_score = analyze_feature_match(img)
        execution_trace.append({"stage": "feature_match", "status": "ok", "score": round(orb_score, 4)})

        wavelet_result, wavelet_score = analyze_wavelet_noise(img)
        execution_trace.append({"stage": "wavelet", "status": "ok", "score": round(wavelet_score, 4)})

        metadata_result, metadata_score = analyze_metadata_flags(file_path)
        execution_trace.append({"stage": "metadata", "status": "ok", "score": round(metadata_score, 4)})

        scores = {"ela": ela_score, "orb": orb_score, "wavelet": wavelet_score, "metadata": metadata_score}
        score, agreement_data = _calculate_weighted_score(
            scores=scores,
            weights=calibration.weights,
            agreement_margins=calibration.agreement_margins,
            spread_cutoffs=calibration.spread_cutoffs,
        )
        label = _label_from_score(score, calibration.thresholds)

        return {
            "method": "forensic",
            "version": "4.0",
            "score": round(score, 4),
            "forensic_score": round(score * 100, 1),
            "label": label,
            "calibration": {
                "version": calibration.version,
                "source": calibration.source,
                "thresholds": {
                    "authentic": round(calibration.thresholds["authentic"], 4),
                    "tampered": round(calibration.thresholds["tampered"], 4),
                },
            },
            "agreement": {
                "lower_bound": agreement_data["lower_bound"],
                "upper_bound": agreement_data["upper_bound"],
                "band": agreement_data["agreement_band"],
                "margin": agreement_data["agreement_margin"],
                "spread": agreement_data["signal_spread"],
            },
            "details": {
                "ela": round(ela_score, 4),
                "orb": round(orb_score, 4),
                "wavelet": round(wavelet_score, 4),
                "metadata": round(metadata_score, 4),
            },
            "signal_analysis": agreement_data["signal_breakdown"],
            "analysis": {
                "ela": ela_result,
                "orb": orb_result,
                "wavelet": wavelet_result,
                "metadata": metadata_result,
            },
            "artifacts": {"ela_map": ela_result.get("map", "")},
            "execution_time_ms": round((time.time() - start) * 1000, 2),
            "timestamp": datetime.utcnow().isoformat(),
            "execution_trace": execution_trace,
        }
    except Exception as exc:
        logger.error("Analysis failed: %s", exc, exc_info=True)
        return {
            "method": "forensic",
            "score": 0.0,
            "forensic_score": 0.0,
            "label": "failed",
            "details": {},
            "artifacts": {},
            "error": str(exc),
            "execution_time_ms": round((time.time() - start) * 1000, 2),
            "execution_trace": execution_trace,
        }


run_heuristic_analysis = run_forensic_analysis
