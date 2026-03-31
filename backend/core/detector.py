import cv2
import numpy as np
import io
import logging
import os
import time
from PIL import Image, ImageChops, ImageEnhance
from collections import Counter
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from scipy.cluster import hierarchy
from scipy.spatial.distance import pdist
from .config import settings

logger = logging.getLogger(__name__)

class ForgeryDetector:
    def __init__(self, max_keypoints=2000):
        self.min_matches = settings.SIFT_MIN_MATCHES
        self.cluster_threshold = settings.SIFT_CLUSTER_DISTANCE
        self.max_keypoints = max_keypoints

    def _analyze_exif(self, img_path):
        start_time = time.time()
        try:
            img = Image.open(img_path)
            exif = img.getexif()
            if not exif:
                return {"has_metadata": False, "warnings": [], "duration_ms": round((time.time() - start_time) * 1000, 2)}

            warnings = []
            if 0x0131 in exif:
                software = str(exif[0x0131]).lower()
                suspicious = ["photoshop", "gimp", "lightroom", "canva", "illustrator", "midjourney", "dall-e", "stable diffusion"]
                if any(s in software for s in suspicious):
                    warnings.append(f"Editing software detected: {exif[0x0131]}")

            return {
                "has_metadata": True,
                "warnings": warnings,
                "software_signature": str(exif.get(0x0131, "None")),
                "duration_ms": round((time.time() - start_time) * 1000, 2)
            }
        except Exception:
            return {"has_metadata": False, "warnings": [], "duration_ms": round((time.time() - start_time) * 1000, 2)}

    def _analyze_ela(self, img_path):
        start_time = time.time()
        try:
            original = Image.open(img_path).convert('RGB')
            temp_io = io.BytesIO()
            original.save(temp_io, 'JPEG', quality=settings.ELA_JPEG_QUALITY)
            temp_io.seek(0)
            compressed = Image.open(temp_io)
            diff = ImageChops.difference(original, compressed)
            extrema = diff.getextrema()
            max_diff = max([ex[1] for ex in extrema]) or 1
            scale = 255.0 / max_diff
            ela_image = ImageEnhance.Brightness(diff).enhance(scale)
            gray_ela = np.array(ela_image.convert('L'))
            ela_score = float(np.std(gray_ela))
            ela_path = img_path.replace(".jpg", "_ela.png")
            ela_image.save(ela_path, format="PNG", optimize=True)
            url_path = f"/api/media/{os.path.basename(ela_path)}"
            is_forged = ela_score > settings.ELA_THRESHOLD
            return {
                "is_forged": is_forged,
                "anomaly_score": round(ela_score, 2),
                "ela_heatmap_url": url_path,
                "duration_ms": round((time.time() - start_time) * 1000, 2)
            }
        except Exception as e:
            return {"is_forged": False, "anomaly_score": 0, "error": str(e), "ela_heatmap_url": None, "duration_ms": round((time.time() - start_time) * 1000, 2)}

    def _analyze_sift(self, img, img_path):
        start_time = time.time()
        try:
            h, w = img.shape[:2]
            if max(h, w) > 800:
                scale = 800 / max(h, w)
                img = cv2.resize(img, (int(w * scale), int(h * scale)))

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            entropy = float(np.std(gray))
            if entropy < settings.ENTROPY_THRESHOLD:
                return None

            sift = cv2.SIFT_create(nfeatures=self.max_keypoints)
            kps, descs = sift.detectAndCompute(gray, None)
            if descs is None or len(descs) < 15:
                return None

            matcher = cv2.BFMatcher(cv2.NORM_L2)
            matches = matcher.knnMatch(descs, descs, k=min(10, len(descs)))
            q_pts, t_pts = [], []
            ratio = settings.SIFT_RATIO_THRESHOLD

            for m in matches:
                if len(m) < 2:
                    continue
                if m[0].distance < ratio * m[1].distance:
                    p1 = kps[m[0].queryIdx].pt
                    p2 = kps[m[0].trainIdx].pt
                    dist = np.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)
                    if dist > settings.SIFT_MIN_SPATIAL_DISTANCE and dist < settings.SIFT_MAX_SPATIAL_DISTANCE:
                        q_pts.append(p1)
                        t_pts.append(p2)

            if len(q_pts) < 8:
                return None

            q_pts = np.array(q_pts, dtype=np.float32)
            t_pts = np.array(t_pts, dtype=np.float32)

            H, mask = cv2.findHomography(q_pts, t_pts, cv2.RANSAC, 4.0)
            if H is None or np.sum(mask) < settings.SIFT_MIN_INLIERS:
                return None
            inliers = q_pts[mask.ravel() == 1]
            if len(inliers) < settings.SIFT_MIN_INLIERS:
                return None

            pts = np.vstack((q_pts, t_pts))
            z_link = hierarchy.linkage(pdist(pts, "euclidean"), "ward")
            clusters = hierarchy.fcluster(z_link, t=self.cluster_threshold, criterion="inconsistent", depth=4)
            count = Counter(clusters)
            min_cluster = getattr(settings, 'SIFT_MIN_CLUSTER_SIZE', 3)
            valid = [k for k, v in count.items() if v >= min_cluster]

            if not valid:
                return None

            f_pts = pts[[i for i, c in enumerate(clusters) if c in valid]]
            n = int(f_pts.shape[0] / 2)
            p1_f, p2_f = f_pts[:n], f_pts[n:]

            fig = Figure(figsize=(8, 8))
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(111)
            ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            ax.axis("off")
            ax.scatter(p1_f[:, 0], p1_f[:, 1], c="cyan", s=30, edgecolors='white', linewidth=0.8)

            for (x1, y1), (x2, y2) in zip(p1_f, p2_f):
                ax.plot([x1, x2], [y1, y2], "cyan", linestyle="--", alpha=0.6, linewidth=1.2)

            sift_path = img_path.replace(".jpg", "_sift.png")
            fig.savefig(sift_path, format="png", bbox_inches="tight", pad_inches=0, dpi=120)
            url_path = f"/api/media/{os.path.basename(sift_path)}"

            return {
                "is_forged": True,
                "clone_clusters_found": len(valid),
                "sift_heatmap_url": url_path,
                "duration_ms": round((time.time() - start_time) * 1000, 2)
            }
        except Exception as e:
            logger.debug(f"SIFT execution error: {e}")
            return None

    def detect_file(self, file_path: str, ml_result: dict = None) -> dict:
        total_start = time.time()
        exif_res = self._analyze_exif(file_path)
        ela_res = self._analyze_ela(file_path)

        img = cv2.imread(file_path, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Corrupted image data.")

        sift_res = self._analyze_sift(img, file_path)
        if not sift_res:
            sift_res = {"is_forged": False, "clone_clusters_found": 0, "sift_heatmap_url": None, "duration_ms": 0}

        ml_score = ml_result.get("score", 0.0) if ml_result else 0.0
        
        points = 0.0
        reasons = []

        if exif_res.get("warnings"):
            points += 2.0
            reasons.extend(exif_res["warnings"])

        if ela_res.get("is_forged"):
            points += 1.5
            reasons.append(f"ELA Anomaly Identified (Score: {ela_res['anomaly_score']})")

        if sift_res.get("is_forged"):
            points += 3.0
            reasons.append(f"Structural Duplication Detected ({sift_res['clone_clusters_found']} clusters)")

        if ml_score > 70:
            points += (ml_score / 100.0) * 2.0
            reasons.append(f"Probabilistic Analysis Score: {ml_score}%")

        is_forged = points >= 3.0
        confidence = min(99, int((points / 7.5) * 100)) if is_forged else max(40, 100 - int(points * 12))

        if not reasons:
            reasons.append("No structural or probabilistic anomalies detected.")

        return {
            "is_forged": is_forged,
            "confidence": confidence,
            "reasons": reasons,
            "total_duration_ms": round((time.time() - total_start) * 1000, 2),
            "evidence": {
                "exif": exif_res,
                "ela": ela_res,
                "sift": sift_res,
                "ml": ml_result
            }
        }
