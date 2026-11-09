"""OpenCV image preprocessing pipeline for receipt images.

Provides:
- Blur detection via Laplacian variance
- Deskewing and rotation normalization
- Contrast enhancement and noise filtering
- Conversion between bytes, PIL Images, and OpenCV BGR arrays
"""

from dataclasses import dataclass
import io
import math
import numpy as np
from PIL import Image

try:
    import cv2
except ImportError:
    cv2 = None


@dataclass
class PreprocessingResult:
    """Outcome of receipt preprocessing."""
    processed_image: Image.Image
    processed_bytes: bytes
    blur_score: float
    is_blurry: bool
    skew_angle: float
    width: int
    height: int
    warnings: list[str]


class ImagePreprocessor:
    """Preprocesses receipt images for optimal AI vision and OCR extraction."""

    BLUR_THRESHOLD: float = 85.0  # Laplacian variance below this is flagged as blurry

    def __init__(self, blur_threshold: float = BLUR_THRESHOLD):
        self.blur_threshold = blur_threshold

    def bytes_to_cv2(self, image_bytes: bytes) -> np.ndarray:
        """Decodes image bytes to OpenCV BGR array."""
        nparr = np.frombuffer(image_bytes, np.uint8)
        if cv2 is None:
            # Fallback if cv2 is not yet imported
            from PIL import Image
            pil_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            return np.array(pil_img)[:, :, ::-1].copy()
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Failed to decode image bytes. Unsupported or corrupted file.")
        return img

    def cv2_to_bytes(self, cv2_img: np.ndarray, format: str = "PNG") -> bytes:
        """Encodes an OpenCV image back to bytes."""
        if cv2 is None:
            pil_img = Image.fromarray(cv2_img[:, :, ::-1] if len(cv2_img.shape) == 3 else cv2_img)
            buf = io.BytesIO()
            pil_img.save(buf, format=format)
            return buf.getvalue()
        ext = f".{format.lower()}"
        success, buf = cv2.imencode(ext, cv2_img)
        if not success:
            raise ValueError(f"Failed to encode image to {format}.")
        return buf.tobytes()

    def cv2_to_pil(self, cv2_img: np.ndarray) -> Image.Image:
        """Converts OpenCV BGR or Grayscale array to PIL Image."""
        if len(cv2_img.shape) == 2:
            return Image.fromarray(cv2_img)
        # BGR to RGB
        return Image.fromarray(cv2_img[:, :, ::-1])

    def detect_blur(self, cv2_img: np.ndarray) -> tuple[float, bool]:
        """Calculates Laplacian variance to detect out-of-focus or motion-blurred receipts."""
        if len(cv2_img.shape) == 3:
            if cv2 is not None:
                gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
            else:
                gray = np.dot(cv2_img[..., :3], [0.114, 0.587, 0.299]).astype(np.uint8)
        else:
            gray = cv2_img

        if cv2 is not None:
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            score = float(laplacian.var())
        else:
            # Simple fallback gradient variance if cv2 is absent
            gy, gx = np.gradient(gray.astype(float))
            gnorm = np.sqrt(gx**2 + gy**2)
            score = float(np.var(gnorm))

        is_blurry = score < self.blur_threshold
        return round(score, 2), is_blurry

    def detect_and_correct_skew(self, cv2_img: np.ndarray) -> tuple[np.ndarray, float]:
        """Detects receipt tilt angle and straightens the image."""
        if cv2 is None:
            return cv2_img, 0.0

        if len(cv2_img.shape) == 3:
            gray = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2GRAY)
        else:
            gray = cv2_img

        # Invert colors so text is foreground
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

        # Find coordinates of all foreground pixels
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 50:
            return cv2_img, 0.0

        # Compute minimum rotated bounding box
        rect = cv2.minAreaRect(coords)
        angle = rect[-1]

        # Normalize angle to [-45, 45] range
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle

        # Only deskew if tilt is between 0.5 and 45 degrees
        if abs(angle) < 0.5 or abs(angle) > 45.0:
            return cv2_img, 0.0

        (h, w) = cv2_img.shape[:2]
        center = (w // 2, h // 2)
        rot_mat = cv2.getRotationMatrix2D(center, angle, 1.0)
        deskewed = cv2.warpAffine(
            cv2_img, rot_mat, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
        )
        return deskewed, round(float(angle), 2)

    def enhance_contrast(self, cv2_img: np.ndarray) -> np.ndarray:
        """Applies CLAHE (Contrast Limited Adaptive Histogram Equalization) and edge sharpening."""
        if cv2 is None:
            return cv2_img

        if len(cv2_img.shape) == 3:
            # Convert to LAB color space to equalize only luminance
            lab = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            merged = cv2.merge((cl, a, b))
            enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        else:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(cv2_img)

        return enhanced

    def preprocess(self, image_bytes: bytes) -> PreprocessingResult:
        """Runs the complete preprocessing pipeline on image bytes."""
        cv_img = self.bytes_to_cv2(image_bytes)
        h, w = cv_img.shape[:2]
        warnings: list[str] = []

        # 1. Blur check
        blur_score, is_blurry = self.detect_blur(cv_img)
        if is_blurry:
            warnings.append(
                f"Image appears blurry (Laplacian variance: {blur_score} < {self.blur_threshold}). "
                "Extraction accuracy may be degraded."
            )

        # 2. Deskew
        deskewed, skew_angle = self.detect_and_correct_skew(cv_img)
        if abs(skew_angle) >= 0.5:
            warnings.append(f"Image deskewed by {skew_angle}°.")

        # 3. Contrast enhancement
        enhanced = self.enhance_contrast(deskewed)

        # 4. Convert to outputs
        pil_img = self.cv2_to_pil(enhanced)
        processed_bytes = self.cv2_to_bytes(enhanced, format="PNG")

        return PreprocessingResult(
            processed_image=pil_img,
            processed_bytes=processed_bytes,
            blur_score=blur_score,
            is_blurry=is_blurry,
            skew_angle=skew_angle,
            width=w,
            height=h,
            warnings=warnings,
        )

