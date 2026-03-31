import cv2
import numpy as np
import io
import base64
import logging
import os
import uuid
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
        try:
            img = Image.open(img_path)
            exif = img.getexif()
            if not exif:
                return {"has_metadata": False, "warnings": []}

            warnings = []
            software = ""
            if 0x0131 in exif:
                software = str(exif[0x0131]).lower()
                suspicious = ["photoshop", "gimp", "lightroom", "canva", "illustrator", "midjourney", "dall-e", "stable diffusion"]
                if any(s in software for s in suspicious):
                    warnings.append(f"Editing software detected: {exif[0x0131]}")

            return {
                "has_metadata": True,
                "warnings": warnings,
                "software_signature": str(exif.get(0x0131, "None"))
            }
        except Exception:
            return {"has_metadata": False, "warnings": []}

    def _analyze_ela(self, img_path):
        try:
            original = Image.open(img_path).convert('RGB')
            temp_io = io.BytesIO()
            original.save(temp_io, 'JPEG', quality=settings.ELA_JPEG_QUALITY)
            temp_io.seek(0)
            compressed = Image.open(temp_io)
            diff = ImageChops.difference(original, compressed)
            extrema = diff.getextrema()
            max_diff = max([ex[1] for ex in extrema])
            if max_diff == 0:
                max_diff = 1
            scale = 255.0 / max_diff
            ela_image = ImageEnhance.Brightness(diff).enhance(scale)
            gray_ela = np.array(ela_image.convert('L'))
            ela_score = float(np.std(gray_ela))
            buf = io.BytesIO()
            ela_image.save(buf, format="PNG", optimize=True)
            buf.seek(0)
            ela_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
            is_forged = ela_score > settings.ELA_THRESHOLD
            return {
                "is_forged": is_forged,
                "anomaly_score": round(ela_score, 2),
                "ela_heatmap_b64": f"data:image/png;base64,{ela_b64}"
            }
        except Exception as e:
            return {"is_forged": False, "anomaly_score": 0, "error": str(e), "ela_heatmap_b64": None}

    def _analyze_sift(self, img):
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

            try:
                H, mask = cv2.findHomography(q_pts, t_pts, cv2.RANSAC, 4.0)
                if H is None or np.sum(mask) < settings.SIFT_MIN_INLIERS:
                    return None
                inliers = q_pts[mask.ravel() == 1]
                if len(inliers) < settings.SIFT_MIN_INLIERS:
                    return None
            except:
                return None

            pts = np.vstack((q_pts, t_pts))
            if len(pts) > 3000:
                return None

            z_link = hierarchy.linkage(pdist(pts, "euclidean"), "ward")
            clusters = hierarchy.fcluster(z_link, t=self.cluster_threshold, criterion="inconsistent", depth=4)
            count = Counter(clusters)
            valid = [k for k, v in count.items() if v >= settings.SIFT_MIN_CLUSTER_SIZE]

            if not valid:
                return None

            keep_idx = [i for i, c in enumerate(clusters) if c in valid]
            f_clusters = clusters[keep_idx]
            f_pts = pts[keep_idx]
            n = int(f_pts.shape[0] / 2)
            p1_f, p2_f = f_pts[:n], f_pts[n:]
            clusters_f = f_clusters[:p1_f.shape[0]]

            fig = Figure(figsize=(8, 8))
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(111)
            ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
            ax.axis("off")
            ax.scatter(p1_f[:, 0], p1_f[:, 1], c=clusters_f, s=30, edgecolors='white', linewidth=0.8)

            for (x1, y1), (x2, y2) in zip(p1_f, p2_f):
                ax.plot([x1, x2], [y1, y2], "cyan", linestyle="--", alpha=0.6, linewidth=1.2)

            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, dpi=120)
            buf.seek(0)
            sift_b64 = base64.b64encode(buf.read()).decode('utf-8')

            return {
                "is_forged": True,
                "clone_clusters_found": len(valid),
                "sift_heatmap_b64": f"data:image/png;base64,{sift_b64}"
            }
        except Exception as e:
            logger.debug(f"SIFT analysis failed: {e}")
            return None

    def detect_file(self, file_path: str, ml_result: dict = None) -> dict:
        try:
            exif_res = self._analyze_exif(file_path)
            ela_res = self._analyze_ela(file_path)

            img = cv2.imread(file_path, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("Invalid or corrupted image data.")

            sift_res = self._analyze_sift(img)
            if not sift_res:
                sift_res = {"is_forged": False, "clone_clusters_found": 0, "sift_heatmap_b64": None}

            ml_score = ml_result.get("score", 0.0) if ml_result else 0.0

            points = 0.0
            reasons = []

            # AI/ML Signal (Base Score)
            ai_points = (ml_score / 50.0)
            points += ai_points
            if ml_score > 70:
                reasons.append(f"AI/ML model identifies manipulation probability ({ml_score}%).")

            # EXIF Metadata (Booster)
            if exif_res.get("warnings"):
                points += 1.0
                reasons.extend(exif_res["warnings"])

            # Forensic Signal: ELA (Booster)
            if ela_res.get("is_forged"):
                points += 1.5
                reasons.append(f"ELA detected compression variance (score: {ela_res.get('anomaly_score', 0)}).")

            # Forensic Signal: SIFT/Copy-Move (Critical Booster)
            if sift_res.get("is_forged"):
                points += 2.0
                reasons.append(f"Copy-move analysis found {sift_res.get('clone_clusters_found', 0)} suspicious clusters.")

            # Decision Logic
            # Require 2.5 points for a definitive FAKE verdict (Ensemble agreement)
            is_forged = points >= 2.5

            if points < 1.0:
                confidence = 95
                reasons = ["No structural anomalies detected. Image appears authentic."]
            elif is_forged:
                confidence = min(100, 70 + int(points * 5))
            else:
                confidence = 65
                reasons.append("Minor forensic indicators found, but insufficient for definitive verdict.")

            return {
                "is_forged": is_forged,
                "confidence": min(100, confidence),
                "reasons": reasons,
                "evidence": {
                    "exif": exif_res,
                    "ela": ela_res,
                    "sift": sift_res,
                    "ml": ml_result or {"score": 0.0, "fallback_used": True}
                }
            }
        except Exception as e:
            logger.error(f"Detection failed: {e}")
            raise
