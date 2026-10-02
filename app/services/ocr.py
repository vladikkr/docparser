"""OCR service with lazy imports.

Heavy dependencies (opencv, pillow, tesseract bindings) are optional so the API
can boot on constrained hosts. Import errors surface only when OCR is used.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Any

import structlog
from PIL import Image

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


_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_USER_TESSDATA = Path.home() / "AppData" / "Local" / "docparser" / "tessdata"


def _configure_pytesseract(pytesseract: Any) -> None:
    """Point pytesseract at a Tesseract install and its language data.

    Tesseract is a separate program. On Windows the installer does not add it to
    PATH, and the Russian language pack is not bundled, so both are located
    explicitly.
    """
    if os.name == "nt" and not shutil.which("tesseract"):
        if os.path.isfile(_WINDOWS_TESSERACT):
            pytesseract.pytesseract.tesseract_cmd = _WINDOWS_TESSERACT

    # Prefer user-supplied language data (contains rus) over the bundled set.
    if _USER_TESSDATA.is_dir() and not os.environ.get("TESSDATA_PREFIX"):
        os.environ["TESSDATA_PREFIX"] = str(_USER_TESSDATA)


def available_languages() -> list[str]:
    """Language packs Tesseract can currently load."""
    pytesseract = _optional_import("pytesseract", "OCR")
    _configure_pytesseract(pytesseract)
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception:
        return []


# Words that only appear on a document, used to judge whether an OCR pass
# produced something usable rather than noise.
_RECEIPT_MARKERS = (
    "ИТОГО",
    "К ОПЛАТЕ",
    "СУММА",
    "НАЛИЧНЫМИ",
    "ПОЗИЦИЯ",
    "КАТИР",
    "УНП",
    "РН СККО",
    "КАССИР",
    "ЧЕК",
    "ТОВАР",
    "ЦЕНА",
    "КОЛИЧЕСТВО",
    "ПРОДУКТ",
    "ОПЛАТА",
    "ИТОГ",
    "TOTAL",
    "SUBTOTAL",
    "CASH",
)

# A handful of markers plus real words is enough to trust a pass.
_GOOD_ENOUGH_SCORE = 3


def _receipt_score(text: str) -> int:
    """Rank OCR output by how much it looks like a document rather than noise."""
    if not text:
        return 0
    lowered = text.lower()
    markers = sum(1 for m in _RECEIPT_MARKERS if m.lower() in lowered)

    # Reward readable word density, penalise lines that are pure noise.
    words = re.findall(r"[A-Za-zА-Яа-яЁёІіЎў]{3,}", text)
    lines = [ln for ln in text.splitlines() if ln.strip()]
    density = 0
    if lines:
        readable = sum(1 for ln in lines if len(re.findall(r"[A-Za-zА-Яа-яЁёІіЎ]{3,}", ln)) >= 2)
        density = readable

    return markers + (1 if len(words) >= 5 else 0) + (1 if density >= 2 else 0)



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

    def _run(self, pytesseract: Any, image: Any) -> str:
        return pytesseract.image_to_string(
            self.preprocess_image(image), config=self.tesseract_config
        ).strip()

    def _best_rotation(self, pytesseract: Any, image: Any, baseline: str) -> str:
        """Retry the image at right angles.

        A receipt photographed sideways yields nothing at all with the default
        page segmentation, so each quarter turn is tried and the most
        receipt-like result wins.
        """
        best = baseline
        best_score = _receipt_score(baseline)
        if best_score >= _GOOD_ENOUGH_SCORE:
            return best

        try:
            import cv2
            import numpy as np
        except RuntimeError:
            return best

        arr = np.array(image.convert("RGB"))
        for turn in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180, cv2.ROTATE_90_COUNTERCLOCKWISE):
            rotated = cv2.rotate(arr, turn)
            try:
                text = pytesseract.image_to_string(
                    self.preprocess_image(Image.fromarray(rotated)),
                    config=self.tesseract_config,
                ).strip()
            except Exception as exc:  # noqa: BLE001
                logger.debug("ocr_rotation_failed", error=str(exc))
                continue
            score = _receipt_score(text)
            if score > best_score:
                best, best_score = text, score
            if best_score >= _GOOD_ENOUGH_SCORE:
                break
        return best

    def _best_tiled(self, pytesseract: Any, image: Any, baseline: str) -> str:
        """Split a wide frame into bands for receipts that sit small inside it.

        A cropped photo often leaves the receipt occupying a fraction of the
        frame, which puts the text below Tesseract's comfortable resolution.
        """
        best = baseline
        best_score = _receipt_score(baseline)
        if best_score >= _GOOD_ENOUGH_SCORE:
            return best

        width, height = image.size
        bands = 3
        overlap = 0.12
        step = height / bands
        chunk = int(step * (1 + overlap))
        chunks: list[str] = []
        for i in range(bands):
            top = max(0, int(i * step))
            bottom = min(height, top + chunk)
            if bottom - top < 40:
                continue
            try:
                text = self._run(pytesseract, image.crop((0, top, width, bottom)))
            except Exception as exc:  # noqa: BLE001
                logger.debug("ocr_band_failed", error=str(exc))
                continue
            if text:
                chunks.append(text)
        if not chunks:
            return best

        joined = "\n".join(chunks)
        score = _receipt_score(joined)
        if score > best_score:
            best = joined
        return best

    def extract_full_text(self, image: Any) -> str:
        pytesseract = _optional_import("pytesseract", "OCR")
        _configure_pytesseract(pytesseract)
        try:
            text = self._run(pytesseract, image)
            text = self._best_rotation(pytesseract, image, text)
            text = self._best_tiled(pytesseract, image, text)
            return text
        except Exception as exc:
            logger.error("extract_full_text_failed", error=str(exc))
            return ""

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

    def pdf_to_images(self, pdf_bytes: bytes) -> list[Any]:
        """Convert PDF pages to images. Requires poppler-utils."""
        convert = _optional_import("pdf2image", "PDF conversion").convert_from_bytes
        return convert(pdf_bytes, dpi=300, fmt="PNG")

    def extract_text(self, image: Any) -> list[tuple[str, float, list[list[int]]]]:
        """Return (text, confidence, bbox) tuples for an image."""
        pytesseract = _optional_import("pytesseract", "OCR")
        _configure_pytesseract(pytesseract)
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

        results: list[tuple[str, float, list[list[int]]]] = []
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

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> list[list[tuple[str, float, list[list[int]]]]]:
        return [self.extract_text(img) for img in self.pdf_to_images(pdf_bytes)]

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
