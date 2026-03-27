"""Tests for OCREngine (cellocr wrapper)."""

from unittest.mock import MagicMock, patch

from PIL import Image

# Mock cellocr to avoid requiring installation.
with patch.dict("sys.modules", {"cellocr": MagicMock()}):
    import visual_window_control.ocr as _ocr_mod
    from visual_window_control.ocr import OCREngine


class TestOCREngine:
    def _make_engine(self):
        """Create an OCREngine with the module-level mock CellOCR."""
        return OCREngine()

    def test_extract_text_calls_recognize(self):
        engine = self._make_engine()
        mock_cellocr = MagicMock()
        mock_result = MagicMock()
        mock_result.text = "hello world"
        mock_cellocr.recognize.return_value = mock_result
        engine._cellocr = mock_cellocr

        img = Image.new("RGB", (100, 50))
        text = engine.extract_text(img)

        assert text == "hello world"
        mock_cellocr.recognize.assert_called_once_with(img)

    def test_options_forwarded_to_from_options(self):
        mock_cls = MagicMock()
        orig = _ocr_mod.CellOCR
        _ocr_mod.CellOCR = mock_cls
        try:
            OCREngine(options="-d Consolas -T 0.9")
            mock_cls.from_options.assert_called_once_with("-d Consolas -T 0.9")
        finally:
            _ocr_mod.CellOCR = orig

    def test_no_options_passes_none(self):
        mock_cls = MagicMock()
        orig = _ocr_mod.CellOCR
        _ocr_mod.CellOCR = mock_cls
        try:
            OCREngine()
            mock_cls.from_options.assert_called_once_with(None)
        finally:
            _ocr_mod.CellOCR = orig

    def test_error_returns_error_string(self):
        engine = self._make_engine()
        mock_cellocr = MagicMock()
        mock_cellocr.recognize.side_effect = RuntimeError("bad image")
        engine._cellocr = mock_cellocr

        img = Image.new("RGB", (100, 50))
        assert engine.recognize(img) is None
        assert engine.extract_text(img) == "[OCR Error]"
