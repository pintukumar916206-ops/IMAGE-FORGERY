import os
import sys
import numpy as np
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.core.detector import run_forensic_pipeline

def validate_dataset(dataset_path):
    path = Path(dataset_path)
    if not path.exists():
        print(f"ERROR: Dataset path {dataset_path} does not exist.")
        return

    authentic_dir = path / "authentic"
    forged_dir = path / "forged"

    results = {
        "TP": 0, "TN": 0, "FP": 0, "FN": 0,
        "errors": 0,
        "times": []
    }

    print(f"Starting Validation on {dataset_path}...")
    
    if authentic_dir.exists():
        files = list(authentic_dir.glob("*"))
        print(f"Processing {len(files)} authentic images...")
        for img_path in files:
            try:
                res = run_forensic_pipeline(str(img_path), str(path / 'uploads'))
                if res.get("error"):
                    results["errors"] += 1
                    continue
                
                if res["isForged"]:
                    results["FP"] += 1
                else:
                    results["TN"] += 1
                results["times"].append(res["execution_time_ms"])
            except Exception as e:
                print(f"Error processing {img_path}: {e}")
                results["errors"] += 1

    if forged_dir.exists():
        files = list(forged_dir.glob("*"))
        print(f"Processing {len(files)} forged images...")
        for img_path in files:
            try:
                res = run_forensic_pipeline(str(img_path), str(path / 'uploads'))
                if res.get("error"):
                    results["errors"] += 1
                    continue
                
                if res["isForged"]:
                    results["TP"] += 1
                else:
                    results["FN"] += 1
                results["times"].append(res["execution_time_ms"])
            except Exception as e:
                print(f"Error processing {img_path}: {e}")
                results["errors"] += 1

    total = results["TP"] + results["TN"] + results["FP"] + results["FN"]
    if total == 0:
        print("No images processed successfully.")
        return

    accuracy = (results["TP"] + results["TN"]) / total
    precision = results["TP"] / (results["TP"] + results["FP"]) if (results["TP"] + results["FP"]) > 0 else 0
    recall = results["TP"] / (results["TP"] + results["FN"]) if (results["TP"] + results["FN"]) > 0 else 0
    fpr = results["FP"] / (results["TN"] + results["FP"]) if (results["TN"] + results["FP"]) > 0 else 0
    fnr = results["FN"] / (results["TP"] + results["FN"]) if (results["TP"] + results["FN"]) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0

    print("\n" + "="*40)
    print("DETECTION PROFILE - TEST DATA")
    print("="*40)
    print(f"Total Samples: {total}")
    print(f"Errors:        {results['errors']}")
    print(f"Avg Time:      {np.mean(results['times']):.2f}ms")
    print("-" * 20)
    print("Confusion Matrix:")
    print(f"  [TN: {results['TN']}, FP: {results['FP']}]")
    print(f"  [FN: {results['FN']}, TP: {results['TP']}]")
    print("-" * 20)
    print(f"Accuracy:      {accuracy*100:.2f}%")
    print(f"Precision:     {precision:.4f}")
    print(f"Recall:        {recall:.4f}")
    print(f"FPR:           {fpr*100:.2f}%")
    print(f"FNR:           {fnr*100:.2f}%")
    print(f"F1 Score:      {f1:.4f}")
    print("="*40)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_dataset.py <dataset_directory>")
    else:
        validate_dataset(sys.argv[1])
