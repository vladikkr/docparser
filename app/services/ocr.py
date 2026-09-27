import cv2
import numpy as np
import pytesseract
import structlog
from pdf2image import convert_from_bytes
from PIL import Image

logger = structlog.get_logger()


class OCRService:
    def __init__(self):
        # Configure tesseract
        self.tesseract_config = "--oem 3 --psm 6 -l rus+eng"

    def preprocess_image(self, image: Image.Image) -> np.ndarray:
        """Preprocess image for better OCR accuracy"""
        # Convert to OpenCV format
        cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Deskew
        cv_image = self._deskew(cv_image)

        # Denoise
        cv_image = cv2.fastNlMeansDenoisingColored(cv_image, None, 10, 10, 7, 21)

        # Increase contrast
        lab = cv2.cvtColor(cv_image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        cv_image = cv2.merge((l, a, b))
        cv_image = cv2.cvtColor(cv_image, cv2.COLOR_LAB2BGR)

        return cv_image

    def _deskew(self, image: np.ndarray) -> np.ndarray:
        """Deskew image using minAreaRect"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) == 0:
            return image
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        if abs(angle) > 0.5:
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            image = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        return image

    def pdf_to_images(self, pdf_bytes: bytes) -> list[Image.Image]:
        """Convert PDF to list of PIL Images"""
        try:
            images = convert_from_bytes(pdf_bytes, dpi=300, fmt="PNG")
            return images
        except Exception as e:
            logger.error("pdf_to_images_failed", error=str(e))
            raise

    def extract_text(self, image: Image.Image) -> list[tuple[str, float, list[list[int]]]]:
        """
        Extract text from image using Tesseract OCR
        Returns list of (text, confidence, bbox)
        """
        cv_image = self.preprocess_image(image)

        try:
            # Get detailed OCR data
            data = pytesseract.image_to_data(
                cv_image,
                config=self.tesseract_config,
                output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            logger.error("ocr_failed", error=str(e))
            raise

        extracted = []
        n_boxes = len(data['level'])
        for i in range(n_boxes):
            text = data['text'][i].strip()
            if text:
                confidence = float(data['conf'][i]) / 100.0 if data['conf'][i] != -1 else 0.0
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                bbox = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
                extracted.append((text, confidence, bbox))

        return extracted

    def extract_text_from_pdf(self, pdf_bytes: bytes) -> list[list[tuple[str, float, list[list[int]]]]]:
        """Extract text from all pages of PDF"""
        images = self.pdf_to_images(pdf_bytes)
        all_pages = []
        for img in images:
            all_pages.append(self.extract_text(img))
        return all_pages

    def extract_full_text(self, image: Image.Image) -> str:
        """Get full text as single string"""
        try:
            cv_image = self.preprocess_image(image)
            text = pytesseract.image_to_string(cv_image, config=self.tesseract_config)
            return text.strip()
        except Exception as e:
            logger.error("extract_full_text_failed", error=str(e))
            return ""

    def extract_full_text_from_pdf(self, pdf_bytes: bytes) -> str:
        """Get full text from all PDF pages"""
        pages = self.extract_text_from_pdf(pdf_bytes)
        all_text = []
        for page in pages:
            page_text = "\n".join([text for text, _, _ in page])
            all_text.append(page_text)
        return "\n\n--- PAGE BREAK ---\n\n".join(all_text)


ocr_service = OCRService()
