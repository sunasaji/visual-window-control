"""OCR backend for visual-window-control.

Thin wrapper around cellocr. All OCR details (preprocessing, template
matching, tesseract fallback, option parsing) are encapsulated in the
cellocr package.
"""

import logging

from cellocr import CellOCR, OCRResult
from PIL import Image

logger = logging.getLogger(__name__)


class OCREngine:
    """OCR engine backed by cellocr.

    Options are passed as a CLI-style string and parsed by cellocr.
    """

    def __init__(self, options: str | None = None):
        self._cellocr = CellOCR.from_options(options)

    def recognize(self, image: Image.Image) -> OCRResult | None:
        """Run OCR and return the full result (or None on error)."""
        try:
            return self._cellocr.recognize(image)
        except Exception as e:
            logger.error("cellocr failed: %s", e)
            return None

    def extract_text(self, image: Image.Image) -> str:
        """Extract text from an image."""
        result = self.recognize(image)
        if result is None:
            return "[OCR Error]"
        return result.text
