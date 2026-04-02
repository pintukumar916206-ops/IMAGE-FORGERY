import os
import sys
import time
import argparse
import pandas as pd
from pathlib import Path
from tabulate import tabulate

root_path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_path))

try:
    from backend.core.detector import run_forensic_pipeline
except ImportError:
    print("Error: Could not import backend.core.detector. Run from the project root.")
    sys.exit(1)


def run_benchmark(dataset_path: str, upload_dir: str):
    dataset_dir = Path(dataset_path)
    if not dataset_dir.exists():
        print(f"Error: Dataset directory {dataset_path} not found.")
        return

    results = []
    image_files = list(dataset_dir.glob("*.jpg")) + list(dataset_dir.glob("*.png")) + list(dataset_dir.glob("*.jpeg"))
    
    if not image_files:
        print("No images found in the dataset directory.")
        return

    print(f"Starting benchmark on {len(image_files)} images...")
    
    tp, fp, tn, fn = 0, 0, 0, 0
    
    for img_path in image_files:
        filename = img_path.name
        is_ground_truth_forged = any(x in filename.lower() for x in ["forged", "mask", "_f", "tampered"])
        
        print(f"Processing {filename}...", end="\r")
        start = time.time()
        pipeline_res = run_forensic_pipeline(str(img_path), upload_dir)
        duration = (time.time() - start) * 1000
        
        predicted_forged = pipeline_res.get("isForged", False)
        confidence = pipeline_res.get("confidence", 0.0)
        
        if is_ground_truth_forged and predicted_forged:
            tp += 1
            status = "TP"
        elif not is_ground_truth_forged and predicted_forged:
            fp += 1
            status = "FP"
        elif is_ground_truth_forged and not predicted_forged:
            fn += 1
            status = "FN"
        else:
            tn += 1
            status = "TN"
            
        results.append({
            "filename": filename,
            "gt": "Forged" if is_ground_truth_forged else "Authentic",
            "pred": "Forged" if predicted_forged else "Authentic",
            "conf": confidence,
            "time_ms": duration,
            "status": status
        })

    print("\nBenchmark Complete.\n")
    accuracy = (tp + tn) / len(results)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0
    
    summary = [
        ["Metric", "Value"],
        ["Total Images", len(results)],
        ["True Positives (TP)", tp],
        ["False Positives (FP)", fp],
        ["True Negatives (TN)", tn],
        ["False Negatives (FN)", fn],
        ["Accuracy", f"{accuracy:.2%}"],
        ["Precision", f"{precision:.2f}"],
        ["Recall (Sensitivity)", f"{recall:.2f}"],
        ["F1-Score", f"{f1:.2f}"]
    ]
    
    print(tabulate(summary, headers="firstrow", tablefmt="grid"))
    df = pd.DataFrame(results)
    df.to_csv("benchmark_results.csv", index=False)
    print("\nDetailed results saved to benchmark_results.csv")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Image Forgery Detection Benchmark Tool")
    parser.add_argument("--dataset", required=True, help="Path to ground-truth image dataset")
    parser.add_argument("--upload-dir", default="uploads", help="Temporary upload dir for ELA maps")
    try:
        import tabulate as _
        import pandas as _
    except ImportError:
        print("Required libraries 'pandas' and 'tabulate' not found. Installing...")
        os.system("pip install pandas tabulate")
    
    args = parser.parse_args()
    Path(args.upload_dir).mkdir(exist_ok=True)
    run_benchmark(args.dataset, args.upload_dir)
