from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

sys.path.append(str(Path(__file__).resolve().parents[1]))

from backend.app.services.detector import run_forensic_analysis

VALID_DATASETS = {"casia": "CASIA", "columbia": "Columbia"}
VALID_SPLITS = {"train", "val", "test"}
TAMPERED_LABELS = {"1", "tampered", "forged", "fake", "manipulated", "splice", "spliced"}
AUTHENTIC_LABELS = {"0", "authentic", "real", "original", "clean", "pristine"}


@dataclass(frozen=True)
class Sample:
    dataset: str
    path: Path
    label: int
    split: Optional[str] = None


def parse_label(raw: str) -> int:
    value = str(raw).strip().lower()
    if value in TAMPERED_LABELS:
        return 1
    if value in AUTHENTIC_LABELS:
        return 0
    raise ValueError(f"Unsupported label: {raw}")


def parse_dataset(raw: str) -> str:
    key = str(raw).strip().lower()
    if key not in VALID_DATASETS:
        raise ValueError(f"Unsupported dataset name: {raw}")
    return VALID_DATASETS[key]


def parse_split(raw: str) -> Optional[str]:
    value = str(raw or "").strip().lower()
    if not value:
        return None
    if value not in VALID_SPLITS:
        raise ValueError(f"Unsupported split value: {raw}")
    return value


def load_manifest(manifest_path: Path) -> List[Sample]:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    rows: List[Sample] = []
    with manifest_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"dataset", "image_path", "label"}
        if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
            raise ValueError("Manifest must include columns: dataset,image_path,label")
        for index, row in enumerate(reader, start=2):
            dataset = parse_dataset(row.get("dataset", ""))
            image_path_raw = str(row.get("image_path", "")).strip()
            if not image_path_raw:
                raise ValueError(f"Manifest row {index} missing image_path")
            image_path = Path(image_path_raw)
            if not image_path.is_absolute():
                image_path = (manifest_path.parent / image_path).resolve()
            if not image_path.exists() or not image_path.is_file():
                raise FileNotFoundError(f"Manifest row {index} points to missing file: {image_path}")
            label = parse_label(row.get("label", ""))
            split = parse_split(row.get("split", ""))
            rows.append(Sample(dataset=dataset, path=image_path, label=label, split=split))
    if not rows:
        raise ValueError("Manifest has no rows")
    return rows


def _split_by_manifest(samples: Sequence[Sample]) -> Tuple[List[Sample], List[Sample], List[Sample]]:
    has_split = [sample.split is not None for sample in samples]
    if any(has_split) and not all(has_split):
        raise ValueError("Manifest split column must be present for every row or none")
    if not all(has_split):
        return [], [], []
    train = [sample for sample in samples if sample.split == "train"]
    val = [sample for sample in samples if sample.split == "val"]
    test = [sample for sample in samples if sample.split == "test"]
    if not train or not val or not test:
        raise ValueError("Manifest-defined splits must include train, val, and test samples")
    return train, val, test


def stratified_split(
    samples: Sequence[Sample],
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> Tuple[List[Sample], List[Sample], List[Sample]]:
    grouped: Dict[Tuple[str, int], List[Sample]] = {}
    for sample in samples:
        grouped.setdefault((sample.dataset, sample.label), []).append(sample)

    train: List[Sample] = []
    val: List[Sample] = []
    test: List[Sample] = []
    rng = random.Random(seed)
    for group in grouped.values():
        rng.shuffle(group)
        total = len(group)
        if total < 3:
            raise ValueError("Each dataset-label group must have at least 3 samples for train/val/test split")
        val_count = max(1, int(round(total * val_ratio)))
        test_count = max(1, int(round(total * test_ratio)))
        if val_count + test_count >= total:
            overflow = (val_count + test_count) - (total - 1)
            if overflow > 0:
                if test_count > 1:
                    reduce_test = min(overflow, test_count - 1)
                    test_count -= reduce_test
                    overflow -= reduce_test
                if overflow > 0 and val_count > 1:
                    val_count = max(1, val_count - overflow)
        train_count = total - val_count - test_count
        if train_count < 1:
            raise ValueError("Split ratios leave no training samples for one of the groups")
        train.extend(group[:train_count])
        val.extend(group[train_count : train_count + val_count])
        test.extend(group[train_count + val_count :])
    return train, val, test


def ensure_binary_labels(samples: Sequence[Sample]) -> None:
    labels = {sample.label for sample in samples}
    if labels != {0, 1}:
        raise ValueError("Samples must contain both authentic (0) and tampered (1) labels")


def _weighted_score(details: Dict[str, float], weights: Dict[str, float]) -> float:
    keys = ("ela", "orb", "wavelet", "metadata")
    weighted = sum(float(details.get(key, 0.0)) * float(weights.get(key, 0.0)) for key in keys)
    total = sum(float(weights.get(key, 0.0)) for key in keys)
    return float(np.clip(weighted / total, 0.0, 1.0)) if total > 0 else 0.0


def _fit_weights(records: Sequence[Dict[str, object]]) -> Dict[str, float]:
    keys = ("ela", "orb", "wavelet", "metadata")
    positives = [record for record in records if int(record["label"]) == 1]
    negatives = [record for record in records if int(record["label"]) == 0]
    if not positives or not negatives:
        raise ValueError("Training records must contain both classes")
    raw = {}
    for key in keys:
        pos_mean = float(np.mean([float(record["details"][key]) for record in positives]))
        neg_mean = float(np.mean([float(record["details"][key]) for record in negatives]))
        raw[key] = abs(pos_mean - neg_mean) + 1e-6
    total = sum(raw.values())
    return {key: float(raw[key] / total) for key in keys}


def _confusion(labels: np.ndarray, scores: np.ndarray, threshold: float) -> Dict[str, int]:
    pred = (scores >= threshold).astype(np.int32)
    return {
        "tp": int(np.sum((pred == 1) & (labels == 1))),
        "tn": int(np.sum((pred == 0) & (labels == 0))),
        "fp": int(np.sum((pred == 1) & (labels == 0))),
        "fn": int(np.sum((pred == 0) & (labels == 1))),
    }


def _metrics(conf: Dict[str, int]) -> Dict[str, float]:
    tp = conf["tp"]
    fp = conf["fp"]
    fn = conf["fn"]
    tn = conf["tn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / max(1, tp + tn + fp + fn)
    return {"precision": float(precision), "recall": float(recall), "f1": float(f1), "accuracy": float(accuracy)}


def _find_tampered_threshold(scores: np.ndarray, labels: np.ndarray) -> Tuple[float, Dict[str, float]]:
    candidates = np.unique(np.round(scores, 6))
    best = {"threshold": 0.5, "precision": 0.0, "recall": 0.0, "f1": -1.0, "accuracy": 0.0}
    for threshold in candidates:
        values = _metrics(_confusion(labels, scores, float(threshold)))
        if values["f1"] > best["f1"] or (values["f1"] == best["f1"] and values["precision"] > best["precision"]):
            best = {"threshold": float(threshold), **values}
    return float(best["threshold"]), {k: float(v) for k, v in best.items() if k != "threshold"}


def _find_authentic_threshold(scores: np.ndarray, labels: np.ndarray, max_threshold: float) -> float:
    candidates = np.unique(np.round(scores[scores <= max_threshold], 6))
    if candidates.size == 0:
        return float(max(0.0, max_threshold - 0.1))
    best_threshold = float(candidates[0])
    best_f1 = -1.0
    true_auth = (labels == 0).astype(np.int32)
    for threshold in candidates:
        pred_auth = (scores <= float(threshold)).astype(np.int32)
        tp = int(np.sum((pred_auth == 1) & (true_auth == 1)))
        fp = int(np.sum((pred_auth == 1) & (true_auth == 0)))
        fn = int(np.sum((pred_auth == 0) & (true_auth == 1)))
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) else 0.0
        if f1 > best_f1:
            best_f1 = f1
            best_threshold = float(threshold)
    return float(min(best_threshold, max_threshold))


def _roc_curve(scores: np.ndarray, labels: np.ndarray) -> Tuple[List[Dict[str, float]], float]:
    thresholds = np.sort(np.unique(np.concatenate(([0.0], scores, [1.0]))))[::-1]
    positives = max(1, int(np.sum(labels == 1)))
    negatives = max(1, int(np.sum(labels == 0)))
    points: List[Dict[str, float]] = []
    for threshold in thresholds:
        conf = _confusion(labels, scores, float(threshold))
        tpr = conf["tp"] / positives
        fpr = conf["fp"] / negatives
        points.append({"threshold": float(threshold), "tpr": float(tpr), "fpr": float(fpr)})
    points = sorted(points, key=lambda point: point["fpr"])
    xs = np.array([point["fpr"] for point in points], dtype=np.float64)
    ys = np.array([point["tpr"] for point in points], dtype=np.float64)
    auc = float(np.trapz(ys, xs))
    return points, auc


def _evaluate(records: Sequence[Dict[str, object]], threshold: float) -> Dict[str, float]:
    labels = np.array([int(record["label"]) for record in records], dtype=np.int32)
    scores = np.array([float(record["score"]) for record in records], dtype=np.float64)
    conf = _confusion(labels, scores, threshold)
    values = _metrics(conf)
    _, auc = _roc_curve(scores, labels)
    return {
        "samples": int(len(records)),
        "precision": values["precision"],
        "recall": values["recall"],
        "f1": values["f1"],
        "accuracy": values["accuracy"],
        "roc_auc": auc,
        "confusion": conf,
    }


def _generate_markdown(payload: Dict[str, object]) -> str:
    metrics = payload["metrics"]["test"]
    lines = [
        "# Benchmark Metrics",
        "",
        f"Generated at: {payload['generated_at']}",
        "",
        "| Dataset | Samples | Precision | Recall | F1 | ROC-AUC |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("overall", "CASIA", "Columbia"):
        entry = metrics.get(name)
        if not entry:
            continue
        lines.append(
            f"| {name} | {entry['samples']} | {entry['precision']:.4f} | {entry['recall']:.4f} | {entry['f1']:.4f} | {entry['roc_auc']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Selection split: validation",
            f"Evaluation split: test",
            f"Thresholds: authentic <= {payload['calibration']['thresholds']['authentic']:.4f}, tampered >= {payload['calibration']['thresholds']['tampered']:.4f}",
        ]
    )
    return "\n".join(lines)


def run_pipeline(
    manifest_path: Path,
    artifacts_dir: Path,
    val_ratio: float,
    test_ratio: float,
    seed: int,
) -> Dict[str, object]:
    samples = load_manifest(manifest_path)
    ensure_binary_labels(samples)

    train_samples, val_samples, test_samples = _split_by_manifest(samples)
    if not train_samples:
        train_samples, val_samples, test_samples = stratified_split(
            samples,
            val_ratio=val_ratio,
            test_ratio=test_ratio,
            seed=seed,
        )

    ensure_binary_labels(train_samples)
    ensure_binary_labels(val_samples)
    ensure_binary_labels(test_samples)

    artifacts_dir.mkdir(parents=True, exist_ok=True)

    split_by_path = {str(sample.path): "train" for sample in train_samples}
    split_by_path.update({str(sample.path): "val" for sample in val_samples})
    split_by_path.update({str(sample.path): "test" for sample in test_samples})

    records: List[Dict[str, object]] = []
    failures = 0
    for sample in samples:
        sample_artifacts_dir = artifacts_dir / sample.dataset.lower()
        sample_artifacts_dir.mkdir(parents=True, exist_ok=True)
        result = run_forensic_analysis(str(sample.path), str(sample_artifacts_dir))
        if result.get("label") in {"failed", "invalid_input"}:
            failures += 1
            continue
        details = result.get("details") or {}
        if not all(key in details for key in ("ela", "orb", "wavelet", "metadata")):
            failures += 1
            continue
        path_key = str(sample.path)
        if path_key not in split_by_path:
            failures += 1
            continue
        records.append(
            {
                "path": path_key,
                "dataset": sample.dataset,
                "label": int(sample.label),
                "split": split_by_path[path_key],
                "details": {
                    "ela": float(details["ela"]),
                    "orb": float(details["orb"]),
                    "wavelet": float(details["wavelet"]),
                    "metadata": float(details["metadata"]),
                },
            }
        )

    if len(records) < 20:
        raise ValueError("Not enough valid detector records from manifest to calibrate and evaluate")

    train_records = [record for record in records if record["split"] == "train"]
    val_records = [record for record in records if record["split"] == "val"]
    test_records = [record for record in records if record["split"] == "test"]
    if not train_records or not val_records or not test_records:
        raise ValueError("One or more splits are empty after detector filtering")

    weights = _fit_weights(train_records)

    for record in records:
        record["score"] = _weighted_score(record["details"], weights)
        detail_values = list(record["details"].values())
        record["spread"] = float(max(detail_values) - min(detail_values))

    val_scores = np.array([float(record["score"]) for record in val_records], dtype=np.float64)
    val_labels = np.array([int(record["label"]) for record in val_records], dtype=np.int32)
    tampered_threshold, val_selection_metrics = _find_tampered_threshold(val_scores, val_labels)
    authentic_threshold = _find_authentic_threshold(val_scores, val_labels, tampered_threshold)

    val_distances = np.abs(val_scores - tampered_threshold)
    tight_margin = float(np.clip(np.quantile(val_distances, 0.25), 0.02, 0.30))
    normal_margin = float(np.clip(np.quantile(val_distances, 0.50), tight_margin, 0.35))
    loose_margin = float(np.clip(np.quantile(val_distances, 0.75), normal_margin, 0.45))

    val_spreads = np.array([float(record["spread"]) for record in val_records], dtype=np.float64)
    spread_tight = float(np.clip(np.quantile(val_spreads, 0.33), 0.01, 0.40))
    spread_loose = float(np.clip(np.quantile(val_spreads, 0.66), spread_tight, 0.80))

    test_scores = np.array([float(record["score"]) for record in test_records], dtype=np.float64)
    test_labels = np.array([int(record["label"]) for record in test_records], dtype=np.int32)
    roc_points, test_roc_auc = _roc_curve(test_scores, test_labels)
    overall_test_metrics = _evaluate(test_records, tampered_threshold)
    overall_test_metrics["roc_auc"] = test_roc_auc

    casia_test_records = [record for record in test_records if record["dataset"] == "CASIA"]
    columbia_test_records = [record for record in test_records if record["dataset"] == "Columbia"]

    calibration = {
        "version": f"validation-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        "source": "validation_split",
        "weights": weights,
        "thresholds": {
            "authentic": float(authentic_threshold),
            "tampered": float(tampered_threshold),
        },
        "agreement_margins": {
            "tight": tight_margin,
            "normal": normal_margin,
            "loose": loose_margin,
        },
        "spread_cutoffs": {
            "tight": spread_tight,
            "loose": spread_loose,
        },
    }

    payload = {
        "generated_at": datetime.utcnow().isoformat(),
        "manifest_path": str(manifest_path),
        "records_processed": len(records),
        "records_failed": failures,
        "splits": {
            "train": len(train_records),
            "val": len(val_records),
            "test": len(test_records),
        },
        "calibration": calibration,
        "selection_metrics": {
            "split": "val",
            "precision": val_selection_metrics["precision"],
            "recall": val_selection_metrics["recall"],
            "f1": val_selection_metrics["f1"],
            "accuracy": val_selection_metrics["accuracy"],
        },
        "metrics": {
            "test": {
                "overall": overall_test_metrics,
                "CASIA": _evaluate(casia_test_records, tampered_threshold) if casia_test_records else None,
                "Columbia": _evaluate(columbia_test_records, tampered_threshold) if columbia_test_records else None,
            }
        },
        "roc_curve_test": roc_points,
    }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="CSV with columns dataset,image_path,label[,split]")
    parser.add_argument("--val-ratio", type=float, default=0.20)
    parser.add_argument("--test-ratio", type=float, default=0.20)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--artifacts-dir", default="benchmark/artifacts")
    parser.add_argument("--metrics-json", default="benchmark/latest_metrics.json")
    parser.add_argument("--metrics-md", default="benchmark/latest_metrics.md")
    parser.add_argument("--calibration-json", default="backend/app/services/calibration.json")
    args = parser.parse_args()

    if args.val_ratio <= 0 or args.test_ratio <= 0 or (args.val_ratio + args.test_ratio) >= 0.9:
        raise ValueError("val-ratio and test-ratio must be positive and leave room for train split")

    payload = run_pipeline(
        manifest_path=Path(args.manifest).resolve(),
        artifacts_dir=Path(args.artifacts_dir),
        val_ratio=float(args.val_ratio),
        test_ratio=float(args.test_ratio),
        seed=int(args.seed),
    )

    metrics_json = Path(args.metrics_json)
    metrics_json.parent.mkdir(parents=True, exist_ok=True)
    metrics_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    calibration_json = Path(args.calibration_json)
    calibration_json.parent.mkdir(parents=True, exist_ok=True)
    calibration_json.write_text(json.dumps(payload["calibration"], indent=2), encoding="utf-8")

    metrics_md = Path(args.metrics_md)
    metrics_md.parent.mkdir(parents=True, exist_ok=True)
    metrics_md.write_text(_generate_markdown(payload), encoding="utf-8")

    print(f"Wrote metrics: {metrics_json}")
    print(f"Wrote calibration: {calibration_json}")
    print(f"Wrote markdown report: {metrics_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
