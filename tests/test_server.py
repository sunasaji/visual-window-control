"""Tests for MCP server call_tool routing."""

import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Mock Windows-only and heavy modules before importing server
with patch.dict("sys.modules", {
    "pynput": MagicMock(),
    "pynput.keyboard": MagicMock(),
    "pynput.mouse": MagicMock(),
    "mss": MagicMock(),
    "pytesseract": MagicMock(),
}):
    from visual_window_control import server


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset server globals before each test."""
    server.ocr = None
    server.controller = None
    yield
    server.ocr = None
    server.controller = None


def _setup_mocks():
    """Set up mock controller and OCR on the server module."""
    ctrl = MagicMock()
    ocr_engine = MagicMock()
    server.controller = ctrl
    server.ocr = ocr_engine
    return ctrl, ocr_engine


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Tool routing tests ───────────────────────────────────────────────


class TestCallToolRouting:
    def test_list_windows(self):
        ctrl, _ = _setup_mocks()
        ctrl.list_windows.return_value = [{"hwnd": 1, "title": "Test"}]

        result = _run(server.call_tool("list_windows", {}))

        ctrl.list_windows.assert_called_once()
        assert result[0].type == "text"
        data = json.loads(result[0].text)
        assert data[0]["title"] == "Test"

    def test_set_target_window(self):
        ctrl, _ = _setup_mocks()
        ctrl.set_target_window.return_value = "Target set to: Test"

        result = _run(server.call_tool("set_target_window", {"title": "Test"}))

        ctrl.set_target_window.assert_called_once_with("Test")
        assert "Target set to" in result[0].text

    def test_send_keys_default(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("send_keys", {"text": "hello"}))

        ctrl.send_keys.assert_called_once_with("hello", raw=False, no_focus=False)
        assert "hello" in result[0].text

    def test_send_keys_raw(self):
        ctrl, _ = _setup_mocks()

        _run(server.call_tool("send_keys", {"text": "cmd\n", "raw": True}))

        ctrl.send_keys.assert_called_once_with("cmd\n", raw=True, no_focus=False)

    def test_send_keys_no_focus(self):
        ctrl, _ = _setup_mocks()

        _run(server.call_tool("send_keys", {"text": "x", "no_focus": True}))

        ctrl.send_keys.assert_called_once_with("x", raw=False, no_focus=True)

    def test_send_special_key(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("send_special_key", {
            "key": "c", "modifiers": ["ctrl"],
        }))

        ctrl.send_special_key.assert_called_once_with("c", ["ctrl"], None, no_focus=False)
        assert "ctrl+c" in result[0].text

    def test_send_special_key_with_delay(self):
        ctrl, _ = _setup_mocks()

        _run(server.call_tool("send_special_key", {
            "key": "enter", "delay_ms": 200,
        }))

        ctrl.send_special_key.assert_called_once_with("enter", [], 200, no_focus=False)

    def test_click(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("click", {"x": 100, "y": 200}))

        ctrl.click.assert_called_once_with(100, 200, "left")
        assert "(100, 200)" in result[0].text

    def test_click_right_button(self):
        ctrl, _ = _setup_mocks()

        _run(server.call_tool("click", {"x": 50, "y": 50, "button": "right"}))

        ctrl.click.assert_called_once_with(50, 50, "right")

    def test_mouse_move(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("mouse_move", {"x": 10, "y": 20}))

        ctrl.mouse_move.assert_called_once_with(10, 20, False)
        assert "Moved mouse to" in result[0].text

    def test_mouse_move_relative(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("mouse_move", {"x": 5, "y": -5, "relative": True}))

        ctrl.mouse_move.assert_called_once_with(5, -5, True)
        assert "Moved mouse by" in result[0].text

    def test_mouse_drag(self):
        ctrl, _ = _setup_mocks()

        _run(server.call_tool("mouse_drag", {
            "start_x": 0, "start_y": 0, "end_x": 100, "end_y": 100,
        }))

        ctrl.mouse_drag.assert_called_once_with(0, 0, 100, 100, "left")

    def test_mouse_scroll(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("mouse_scroll", {"amount": -3}))

        ctrl.mouse_scroll.assert_called_once_with(-3)
        assert "down" in result[0].text

    def test_mouse_scroll_up(self):
        ctrl, _ = _setup_mocks()

        result = _run(server.call_tool("mouse_scroll", {"amount": 5}))

        assert "up" in result[0].text

    def test_get_screen_text(self):
        ctrl, ocr_engine = _setup_mocks()
        fake_image = MagicMock()
        ctrl.capture_window.return_value = fake_image
        ocr_engine.extract_text.return_value = "hello world"

        result = _run(server.call_tool("get_screen_text", {}))

        ctrl.capture_window.assert_called_once_with(None, background=False)
        ocr_engine.extract_text.assert_called_once_with(fake_image)
        assert result[0].text == "hello world"

    def test_get_screen_text_background(self):
        ctrl, ocr_engine = _setup_mocks()
        ctrl.capture_window.return_value = MagicMock()
        ocr_engine.extract_text.return_value = "text"

        _run(server.call_tool("get_screen_text", {"background": True}))

        ctrl.capture_window.assert_called_once_with(None, background=True)

    def test_get_screen_text_capture_fails(self):
        ctrl, _ = _setup_mocks()
        ctrl.capture_window.return_value = None

        result = _run(server.call_tool("get_screen_text", {}))

        assert "Error" in result[0].text

    def test_get_screen_image(self):
        from PIL import Image
        ctrl, _ = _setup_mocks()
        img = Image.new("RGB", (10, 10), color=(255, 0, 0))
        ctrl.capture_window.return_value = img

        result = _run(server.call_tool("get_screen_image", {}))

        assert result[0].type == "image"
        assert result[0].mimeType == "image/jpeg"
        assert len(result[0].data) > 0  # base64 data present

    def test_send_key_sequence(self):
        ctrl, _ = _setup_mocks()
        steps = [{"key": "a"}, {"key": "b", "modifiers": ["ctrl"]}]

        result = _run(server.call_tool("send_key_sequence", {"steps": steps}))

        ctrl.send_key_sequence.assert_called_once_with(steps)

    def test_unknown_tool(self):
        _setup_mocks()

        result = _run(server.call_tool("nonexistent_tool", {}))

        assert "Unknown tool" in result[0].text

    def test_tool_exception_returns_error(self):
        ctrl, _ = _setup_mocks()
        ctrl.list_windows.side_effect = RuntimeError("something broke")

        result = _run(server.call_tool("list_windows", {}))

        assert "Error" in result[0].text
        assert "something broke" in result[0].text

    def test_list_child_windows(self):
        ctrl, _ = _setup_mocks()
        ctrl.list_child_windows.return_value = [{"hwnd": 99, "class": "Edit", "title": ""}]

        result = _run(server.call_tool("list_child_windows", {}))

        ctrl.list_child_windows.assert_called_once()
        data = json.loads(result[0].text)
        assert data[0]["class"] == "Edit"

    def test_get_focus_info(self):
        ctrl, _ = _setup_mocks()
        ctrl.get_focus_info.return_value = {"target_hwnd": 123, "focus_hwnd": 456}

        result = _run(server.call_tool("get_focus_info", {}))

        data = json.loads(result[0].text)
        assert data["target_hwnd"] == 123
