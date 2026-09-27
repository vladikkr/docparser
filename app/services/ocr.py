"""OCR service with lazy imports.

Heavy dependencies (opencv, pillow, tesseract bindings) are optional so the API
can boot on constrained hosts. Import errors surface only when OCR is used.
"""

import io
from typing import Any, List, Optional, Tuple

import structlog

from app.config import settings

logger = structlog.get_logger()

_IMPORT_ERRORS: dict[str, str] = {}


def _optional_import(module: str, feature: str) -> Any:
    """Import an optional dependency, remembering the failure reason."""
    if module in _IMPORT_ERRORS:
        raise RuntimeError(_IMPORT_ERRORS[module])
    try:
        return __import__(module, fromlist=["*"])
    except Exception as exc:
        _IMPORT_ERRORS[module] = (
            f"{feature} unavailable: {type(exc).__name__}: {exc}. "
            f"Install OCR extras: pip install -r requirements-ocr.txt"
        )
        raise RuntimeError(_IMPORT_ERRORS[module]) from exc


class OCRUnavailableError(RuntimeError):
    """Raised when OCR dependencies are not installed."""


def ocr_available() -> bool:
    try:
        _optional_import("pytesseract", "OCR")
        return True
    except RuntimeError:
        return False


class OCRService:
    """OCR wrapper. Prefers OpenCV+Tesseract, falls back to Pillow only."""

    def __init__(self) -> None:
        self.tesseract_config = "--oem 3 --psm 6 -l rus+eng"

    def _cv2(self) -> Any:
        try:
            return _optional_import("cv2", "OpenCV")
        except RuntimeError:
            return None

    def preprocess_image(self, image: Any) -> Any:
        """Deskew, denoise and boost contrast. Returns a PIL image."""
        cv2 = self._cv2()
        if cv2 is None or image is None:
            return image

        try:
            import numpy as np

            arr = np.array(image.convert("RGB"))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            bgr = self._deskew(cv2, bgr)
            bgr = cv2.fastNlMeansDenoisingColored(bgr, None, 10, 10, 7, 21)
            lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
            channel, a, b = cv2.split(lab)
            channel = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(channel)
            bgr = cv2.merge((channel, a, b))
            bgr = cv2.cvtColor(bgr, cv2.COLOR_LAB2BGR)
            return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        except Exception as exc:
            logger.warning("preprocess_failed", error=str(exc))
            return image

    @staticmethod
    def _deskew(cv2: Any, image: Any) -> Any:
        try:
            import numpy as np

            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            coords = np.column_stack(np.where(thresh > 0))
            if len(coords) == 0:
                return image
            angle = cv2.minAreaRect(coords)[-1]
            angle = -(90 + angle) if angle < -45 else -angle
            if abs(angle) > 0.5:
                h, w = image.shape[:2]
                matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
                image = cv2.warpAffine(
                    image,
                    matrix,
                    (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE,
                )
            return image
        except Exception:
            return image

    def pdf_to_images(self, pdf_bytes: bytes) -> List[Any]:
        """Convert PDF pages to images. Requires poppler-utils."""
        convert = _optional_import("pdf2image", "PDF conversion").convert_from_bytes
        return convert(pdf_bytes, dpi=300, fmt="PNG")

    def extract_text(self, image: Any) -> List[Tuple[str, float, List[List[int]]]]:
        """Return (text, confidence, bbox) tuples for an image."""
        pytesseract = _optional_import("pytesseract", "OCR")
        processed = self.preprocess_image(image)
        try:
            data = pytesseract.image_to_data(
                processed,
                config=self.tesseract_config,
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            logger.error("ocr_failed", error=str(exc))
            raise

        results: List[Tuple[str, float, List[List[int]]]] = []
        for i in range(len(data["level"])):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            raw_conf = data["conf"][i]
            confidence = float(raw_conf) / 100.0 if raw_conf not in (-1, "-1", None) else 0.0
            x, y = data["left"][i], data["top"][i]
            w, h = data["width"][i], data["height"][i]
            bbox = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
            results.append((text, confidence, bbox))
        return results

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> List[List[Tuple[str, float, List[List[int]]]]]:
        return [self.extract_text(img) for img in self.pdf_to_images(pdf_bytes)]

    def extract_full_text(self, image: Any) -> str:
        pytesseract = _optional_import("pytesseract", "OCR")
        try:
            return pytesseract.image_to_string(
                self.preprocess_image(image), config=self.tesseract_config
            ).strip()
        except Exception as exc:
            logger.error("extract_full_text_failed", error=str(exc))
            return ""

    def extract_full_text_from_pdf(self, pdf_bytes: bytes) -> str:
        pages = self.extract_text_from_pdf(pdf_bytes)
        joined = ["\n".join(text for text, _, _ in page) for page in pages]
        return "\n\n--- PAGE BREAK ---\n\n".join(joined)


# Imported lazily at the bottom to keep module import cheap
try:
    from PIL import Image
except Exception:  # pragma: no cover - pillow is optional
    Image = None  # type: ignore[assignment]


ocr_service = OCRService()
