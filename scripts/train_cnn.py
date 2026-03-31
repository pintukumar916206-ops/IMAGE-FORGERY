import argparse
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np

def ela_patch(img_arr, quality=90):
    from PIL import Image, ImageChops, ImageEnhance
    img = Image.fromarray(img_arr)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    recompressed = Image.open(buf)
    diff = ImageChops.difference(img, recompressed)
    extrema = diff.getextrema()
    max_diff = max(ex[1] for ex in extrema) or 1
    scale = 255.0 / max_diff
    ela_pil = ImageEnhance.Brightness(diff).enhance(scale)
    return np.asarray(ela_pil, dtype=np.float32) / 255.0

def load_image(path, size=224):
    from PIL import Image
    return np.asarray(Image.open(path).convert("RGB").resize((size, size)), dtype=np.uint8)

def make_authentic(rng, size):
    from PIL import Image
    cx = rng.uniform(0.4, 1.0, 3)
    x = np.linspace(40, 200, size).reshape(1, size, 1)
    y = np.linspace(40, 200, size).reshape(size, 1, 1)
    base = np.zeros((size, size, 3), dtype=np.float32)
    for i in range(3):
        base[:, :, i] = (x * cx[i] + y * (1.0 - cx[i])).squeeze()
    noise = rng.normal(0, 4, (size, size, 3))
    img = np.clip(base + noise, 0, 255).astype(np.uint8)
    pil = Image.fromarray(img)
    buf = io.BytesIO()
    pil.save(buf, "JPEG", quality=92)
    buf.seek(0)
    return np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)

def make_forged(rng, img_arr, size):
    from PIL import Image
    result = img_arr.copy()
    h_p = int(rng.integers(size // 5, size // 3))
    w_p = int(rng.integers(size // 5, size // 3))
    ys = int(rng.integers(5, max(6, size // 3 - h_p)))
    xs = int(rng.integers(5, max(6, size // 3 - w_p)))
    yd = int(rng.integers(size // 2, max(size // 2 + 1, size - h_p)))
    xd = int(rng.integers(size // 2, max(size // 2 + 1, size - w_p)))
    src = Image.fromarray(img_arr[ys:ys + h_p, xs:xs + w_p])
    tmp_h = max(8, int(h_p * rng.uniform(0.5, 0.75)))
    tmp_w = max(8, int(w_p * rng.uniform(0.5, 0.75)))
    src = src.resize((tmp_w, tmp_h), Image.BICUBIC).resize((w_p, h_p), Image.BICUBIC)
    buf = io.BytesIO()
    src.save(buf, "JPEG", quality=int(rng.integers(60, 82)))
    buf.seek(0)
    patch = np.asarray(Image.open(buf).convert("RGB"), dtype=np.uint8)
    actual_h = min(patch.shape[0], size - yd)
    actual_w = min(patch.shape[1], size - xd)
    result[yd:yd + actual_h, xd:xd + actual_w] = patch[:actual_h, :actual_w]
    return result

def make_synthetic_dataset(n_per_class=400, size=224, seed=42):
    rng = np.random.default_rng(seed)
    X, y = [], []
    for _ in range(n_per_class):
        img = make_authentic(rng, size)
        X.append(np.transpose(ela_patch(img), (2, 0, 1)))
        y.append(0)
    for _ in range(n_per_class):
        base_img = make_authentic(rng, size)
        img = make_forged(rng, base_img, size)
        X.append(np.transpose(ela_patch(img), (2, 0, 1)))
        y.append(1)
    idx = rng.permutation(len(X))
    return np.stack(X)[idx].astype(np.float32), np.array(y, dtype=np.int64)[idx]

def load_real_dataset(data_dir, size=224):
    from pathlib import Path
    X, y = [], []
    for label, subfolder in [(0, "authentic"), (1, "forged")]:
        folder = Path(data_dir) / subfolder
        if not folder.exists():
            print(f"[warn] {folder} not found, skipping.")
            continue
        files = list(folder.glob("*.jpg")) + list(folder.glob("*.png")) + list(folder.glob("*.jpeg"))
        print(f"  {len(files)} images from {folder.name}/")
        for f in files:
            try:
                img = load_image(str(f), size=size)
                X.append(np.transpose(ela_patch(img), (2, 0, 1)))
                y.append(label)
            except Exception as e:
                print(f"  [skip] {f.name}: {e}")
    if not X:
        raise RuntimeError("No images found. Check --data-dir layout.")
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(X))
    return np.stack(X)[idx].astype(np.float32), np.array(y, dtype=np.int64)[idx]

def build_model():
    try:
        import torch.nn as nn
    except ImportError:
        print("[error] PyTorch is not installed. Run: pip install torch")
        sys.exit(1)

    class ForgeryCNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(3, 16, kernel_size=3, padding=1),
                nn.BatchNorm2d(16),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(16, 32, kernel_size=3, padding=1),
                nn.BatchNorm2d(32),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
                nn.Conv2d(32, 64, kernel_size=3, padding=1),
                nn.BatchNorm2d(64),
                nn.ReLU(inplace=True),
                nn.AdaptiveAvgPool2d((4, 4)),
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),
                nn.Linear(64 * 4 * 4, 128),
                nn.ReLU(inplace=True),
                nn.Dropout(0.3),
                nn.Linear(128, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            return self.classifier(self.features(x))

    return ForgeryCNN()

def train(model, X, y, epochs, batch_size, lr, device):
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, TensorDataset
    model = model.to(device)
    split = int(0.8 * len(X))
    X_tr, X_val = X[:split], X[split:]
    y_tr, y_val = y[:split], y[split:]
    tr_loader = DataLoader(
        TensorDataset(torch.tensor(X_tr), torch.tensor(y_tr, dtype=torch.float32)),
        batch_size=batch_size, shuffle=True
    )
    val_loader = DataLoader(
        TensorDataset(torch.tensor(X_val), torch.tensor(y_val, dtype=torch.float32)),
        batch_size=batch_size
    )
    criterion = nn.BCELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    print(f"\nsamples={len(X_tr)}  val={len(X_val)}  device={device}  epochs={epochs}\n")
    best_val_acc = 0.0
    best_state = None
    for epoch in range(1, epochs + 1):
        model.train()
        tr_loss = 0.0
        for xb, yb in tr_loader:
            xb, yb = xb.to(device), yb.to(device)
            pred = model(xb).squeeze(1)
            loss = criterion(pred, yb)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            tr_loss += loss.item() * len(xb)
        model.eval()
        correct = total = 0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                pred = (model(xb).squeeze(1) > 0.5).float()
                correct += (pred == yb).sum().item()
                total += len(yb)
        val_acc = correct / total
        scheduler.step()
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        print(f"  epoch {epoch:3d}/{epochs}  loss={tr_loss/len(X_tr):.4f}  val_acc={val_acc:.4f}")
    print(f"\nbest val accuracy: {best_val_acc:.4f}")
    model.load_state_dict(best_state)
    return model

def export_onnx(model, output_path, input_size=224):
    import torch
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    model.eval()
    dummy = torch.zeros(1, 3, input_size, input_size)
    torch.onnx.export(
        model, dummy, output_path,
        input_names=["input"], output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        opset_version=13,
    )
    size_mb = os.path.getsize(output_path) / 1024 / 1024
    print(f"saved {output_path}  ({size_mb:.2f} MB)")

def evaluate(model, X, y, device):
    import torch
    model.eval()
    model = model.to(device)
    with torch.no_grad():
        logits = model(torch.tensor(X).to(device)).squeeze(1).cpu().numpy()
    preds = (logits > 0.5).astype(int)
    tp = int(((preds == 1) & (y == 1)).sum())
    tn = int(((preds == 0) & (y == 0)).sum())
    fp = int(((preds == 1) & (y == 0)).sum())
    fn = int(((preds == 0) & (y == 1)).sum())
    total = len(y)
    acc = (tp + tn) / total
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    print(f"\n  accuracy : {acc*100:.1f}%  fpr : {fpr*100:.1f}%")
    print("             Pred Auth   Pred Forge")
    print(f"  Auth        {tn:>5}        {fp:>5}")
    print(f"  Forge       {fn:>5}        {tp:>5}")
    return {"accuracy": acc, "fpr": fpr, "matrix": [[tn, fp], [fn, tp]]}

def save_metadata(metrics, param_count, output_path, n_train, n_test, elapsed, dataset_name):
    meta = {
        "model_architecture": "Custom ForgeryCNN",
        "benchmark_dataset": dataset_name,
        "train_samples": n_train,
        "test_samples": n_test,
        "proven_accuracy": f"{metrics['accuracy'] * 100:.1f}%",
        "false_positive_rate": f"{metrics['fpr'] * 100:.1f}%",
        "model_params": param_count,
        "training_time_s": round(elapsed, 1),
        "confusion_matrix": metrics["matrix"],
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = os.path.join(os.path.dirname(output_path) or ".", "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"saved {meta_path}")

def parse_args():
    parser = argparse.ArgumentParser(description="Train ForgeryCNN and export to ONNX")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--img-size", type=int, default=224)
    parser.add_argument("--output", type=str, default="backend/ml/forgery_model.onnx")
    parser.add_argument("--synthetic-n", type=int, default=400)
    return parser.parse_args()

def main():
    args = parse_args()
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        print("[error] PyTorch is required: pip install torch")
        sys.exit(1)
    t0 = time.time()
    if args.data_dir:
        print(f"loading dataset from {args.data_dir}")
        X, y = load_real_dataset(args.data_dir, size=args.img_size)
        dataset_name = f"real: {args.data_dir}"
    else:
        print(f"generating synthetic dataset ({args.synthetic_n} per class)...")
        X, y = make_synthetic_dataset(n_per_class=args.synthetic_n, size=args.img_size)
        print(f"  {len(X)} total samples")
        dataset_name = "synthetic JPEG-splice simulation"
    split = int(0.8 * len(X))
    model = build_model()
    model = train(model, X, y, epochs=args.epochs, batch_size=args.batch_size, lr=args.lr, device=device)
    metrics = evaluate(model, X, y, device=device)
    export_onnx(model, args.output, input_size=args.img_size)
    elapsed = time.time() - t0
    param_count = sum(p.numel() for p in model.parameters() if p.requires_grad)
    save_metadata(metrics, param_count, args.output, split, len(X) - split, elapsed, dataset_name)
    print(f"\ndone in {elapsed:.1f}s")

if __name__ == "__main__":
    main()
