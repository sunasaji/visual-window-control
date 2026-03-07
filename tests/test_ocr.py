"""Tests for TerminalOCR preprocessing and postprocessing."""

from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

# Mock pytesseract to avoid requiring Tesseract installation
with patch.dict("sys.modules", {"pytesseract": MagicMock()}):
    from visual_window_control.ocr import TerminalOCR


@pytest.fixture
def ocr():
    with patch("visual_window_control.ocr.pytesseract"):
        return TerminalOCR()


# ── _postprocess_text ─────────────────────────────────────────────────


class TestPostprocessText:
    def test_strips_trailing_whitespace(self, ocr):
        assert ocr._postprocess_text("hello   \nworld  ") == "hello\nworld"

    def test_collapses_excessive_blank_lines(self, ocr):
        text = "a\n\n\n\n\n\nb"
        result = ocr._postprocess_text(text)
        assert result == "a\n\n\nb"

    def test_three_blank_lines_preserved(self, ocr):
        text = "a\n\n\nb"
        result = ocr._postprocess_text(text)
        assert result == "a\n\n\nb"

    def test_safe_correction_pipe_s(self, ocr):
        result = ocr._postprocess_text("run |s command")
        assert "ls" in result

    def test_safe_correction_at_line_start(self, ocr):
        result = ocr._postprocess_text("|s -la")
        # The \n|s pattern requires a newline before it
        # Direct line start without newline won't match
        assert result == "|s -la"

    def test_strips_outer_whitespace(self, ocr):
        assert ocr._postprocess_text("  hello  ") == "hello"

    def test_empty_string(self, ocr):
        assert ocr._postprocess_text("") == ""


# ── preprocess_image ──────────────────────────────────────────────────


class TestPreprocessImage:
    def test_dark_theme_inverted(self, ocr):
        # Dark image (avg brightness < 128)
        img = Image.new("RGB", (100, 50), color=(20, 20, 20))
        result = ocr.preprocess_image(img)
        # Should be upscaled 2x
        assert result.size == (200, 100)
        # After inversion + threshold, dark bg should become white (255)
        pixels = list(result.getdata())
        assert pixels[0] == 255  # Was dark, inverted, thresholded to white

    def test_light_theme_not_inverted(self, ocr):
        # Light image (avg brightness >= 128)
        img = Image.new("RGB", (100, 50), color=(230, 230, 230))
        result = ocr.preprocess_image(img)
        assert result.size == (200, 100)
        # Light pixels should stay white after threshold
        pixels = list(result.getdata())
        assert pixels[0] == 255

    def test_output_is_grayscale(self, ocr):
        img = Image.new("RGB", (50, 50), color=(128, 0, 255))
        result = ocr.preprocess_image(img)
        assert result.mode == "L"

    def test_2x_upscale(self, ocr):
        img = Image.new("RGB", (80, 60), color=(100, 100, 100))
        result = ocr.preprocess_image(img)
        assert result.size == (160, 120)

    def test_binary_output(self, ocr):
        # All pixels should be either 0 or 255 after thresholding
        img = Image.new("RGB", (50, 50), color=(100, 150, 200))
        result = ocr.preprocess_image(img)
        unique_values = set(result.getdata())
        assert unique_values <= {0, 255}
