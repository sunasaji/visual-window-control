"""OCR utilities for terminal text extraction."""

import logging
import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)


class TerminalOCR:
    """OCR engine optimized for terminal/console text."""

    def __init__(self, tesseract_cmd: str | None = None):
        """Initialize OCR engine.

        Args:
            tesseract_cmd: Path to tesseract executable. Auto-detected if None.
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        else:
            # Common Windows installation paths
            possible_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            ]
            for path in possible_paths:
                if Path(path).exists():
                    pytesseract.pytesseract.tesseract_cmd = path
                    break

        # Terminal-optimized Tesseract configuration
        # --oem 3: Use LSTM neural net (most accurate)
        # --psm 6: Assume uniform block of text
        self.tesseract_config = r"--oem 3 --psm 6"

        # Character whitelist for terminal content
        self.terminal_chars = (
            "0123456789"
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "@#$%^&*()_+-=[]{}|;':\",./<>?`~\\ \n\t"
        )

    def preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR accuracy.

        Optimized for terminal screenshots with monospace fonts.

        Args:
            image: Input PIL Image

        Returns:
            Preprocessed PIL Image
        """
        # Convert to grayscale
        img = image.convert("L")

        # Increase contrast
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        # Sharpen
        img = img.filter(ImageFilter.SHARPEN)

        # Determine if dark or light theme by checking average brightness
        avg_brightness = sum(img.getdata()) / (img.width * img.height)

        # Invert if dark theme (white text on dark background)
        # Tesseract works better with dark text on light background
        if avg_brightness < 128:
            img = ImageOps.invert(img)

        # Apply threshold to create binary image
        # This helps with clean terminal fonts
        threshold = 180
        img = img.point(lambda x: 255 if x > threshold else 0, "L")  # type: ignore[operator]

        # Scale up for better recognition (2x)
        new_size = (img.width * 2, img.height * 2)
        img = img.resize(new_size, Image.Resampling.LANCZOS)

        return img

    def extract_text(self, image: Image.Image, preprocess: bool = True) -> str:
        """Extract text from terminal screenshot.

        Args:
            image: PIL Image of terminal
            preprocess: Whether to apply preprocessing (default: True)

        Returns:
            Extracted text
        """
        if preprocess:
            processed = self.preprocess_image(image)
        else:
            processed = image

        try:
            text = pytesseract.image_to_string(
                processed,
                config=self.tesseract_config,
            )

            # Clean up common OCR artifacts
            text = self._postprocess_text(text)

            return text

        except Exception as e:
            logger.error("OCR failed: %s", e)
            return f"[OCR Error: {str(e)}]"

    def extract_text_with_confidence(
        self, image: Image.Image, preprocess: bool = True
    ) -> tuple[str, list[dict]]:
        """Extract text with per-word confidence scores.

        Args:
            image: PIL Image of terminal
            preprocess: Whether to apply preprocessing

        Returns:
            Tuple of (full text, list of word data with confidence)
        """
        if preprocess:
            processed = self.preprocess_image(image)
        else:
            processed = image

        try:
            data = pytesseract.image_to_data(
                processed,
                config=self.tesseract_config,
                output_type=pytesseract.Output.DICT,
            )

            words_data = []
            for i, word in enumerate(data["text"]):
                if word.strip():
                    words_data.append({
                        "text": word,
                        "confidence": int(data["conf"][i]),
                        "x": data["left"][i],
                        "y": data["top"][i],
                        "width": data["width"][i],
                        "height": data["height"][i],
                    })

            full_text = " ".join(w["text"] for w in words_data)
            return full_text, words_data

        except Exception as e:
            logger.error("OCR failed: %s", e)
            return f"[OCR Error: {str(e)}]", []

    def _postprocess_text(self, text: str) -> str:
        """Clean up OCR output.

        Args:
            text: Raw OCR output

        Returns:
            Cleaned text
        """
        # Remove excessive whitespace while preserving structure
        lines = text.split("\n")
        cleaned_lines = []

        for line in lines:
            # Remove trailing whitespace
            line = line.rstrip()

            # Skip completely empty lines if there are multiple in a row
            cleaned_lines.append(line)

        # Remove excessive blank lines (more than 2 consecutive)
        result = "\n".join(cleaned_lines)
        result = re.sub(r"\n{4,}", "\n\n\n", result)

        # Apply safe corrections only
        # These are patterns that are very unlikely in terminal output
        safe_corrections = {
            " |s ": " ls ",
            " |s\n": " ls\n",
            "\n|s ": "\nls ",
        }

        for wrong, correct in safe_corrections.items():
            result = result.replace(wrong, correct)

        return result.strip()

    def get_low_confidence_regions(
        self, image: Image.Image, threshold: int = 70
    ) -> list[dict]:
        """Identify regions with low OCR confidence.

        Useful for requesting image review of uncertain areas.

        Args:
            image: PIL Image
            threshold: Confidence threshold (0-100)

        Returns:
            List of low-confidence word regions
        """
        _, words_data = self.extract_text_with_confidence(image)

        low_conf = [
            w for w in words_data
            if w["confidence"] >= 0 and w["confidence"] < threshold
        ]

        return low_conf
