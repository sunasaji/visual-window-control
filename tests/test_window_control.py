"""Tests for WindowController: _make_lparam, send_keys branching, set_target_window."""

from unittest.mock import patch, MagicMock, call

import pytest

# Mock pynput/mss before importing
with patch.dict("sys.modules", {
    "pynput": MagicMock(),
    "pynput.keyboard": MagicMock(),
    "pynput.mouse": MagicMock(),
    "mss": MagicMock(),
}):
    from visual_window_control.window_control import WindowController


def _make_ctrl(**overrides):
    """Create a WindowController with mocked __init__ and minimal attributes."""
    with patch.object(WindowController, "__init__", lambda self: None):
        c = WindowController.__new__(WindowController)
        c.keyboard = MagicMock()
        c.mouse = MagicMock()
        c.target_hwnd = 12345
        c.target_title = "Test Window"
        c.target_child_hwnd = None
        c.special_keys = {
            "enter": "ENTER", "return": "ENTER", "tab": "TAB",
            "escape": "ESC", "esc": "ESC", "backspace": "BS",
            "delete": "DEL", "up": "UP", "down": "DOWN",
            "left": "LEFT", "right": "RIGHT", "home": "HOME",
            "end": "END", "pageup": "PU", "pagedown": "PD",
            "space": "SPACE",
            "f1": "F1", "f2": "F2", "f3": "F3", "f4": "F4",
            "f5": "F5", "f6": "F6", "f7": "F7", "f8": "F8",
            "f9": "F9", "f10": "F10", "f11": "F11", "f12": "F12",
        }
        c.modifier_keys = {
            "ctrl": "CTRL", "control": "CTRL", "alt": "ALT", "shift": "SHIFT",
        }
        c._vk_map = {
            "enter": 0x0D, "return": 0x0D, "tab": 0x09,
            "escape": 0x1B, "esc": 0x1B, "backspace": 0x08,
            "delete": 0x2E, "up": 0x26, "down": 0x28,
            "left": 0x25, "right": 0x27, "home": 0x24,
            "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
            "space": 0x20,
        }
        c._mod_vk_map = {
            "ctrl": 0x11, "control": 0x11, "alt": 0x12, "shift": 0x10,
        }
        for k, v in overrides.items():
            setattr(c, k, v)
        return c


# ── _make_lparam ──────────────────────────────────────────────────────


class TestMakeLparam:
    def test_keydown_repeat_count_is_1(self):
        lp = WindowController._make_lparam(0x1E, False)  # scan code for 'A'
        assert lp & 0xFFFF == 1  # bits 0-15: repeat count

    def test_keydown_scan_code_in_bits_16_23(self):
        scan = 0x1E
        lp = WindowController._make_lparam(scan, False)
        extracted = (lp >> 16) & 0xFF
        assert extracted == scan

    def test_keydown_no_transition_flags(self):
        lp = WindowController._make_lparam(0x1E, False)
        assert (lp >> 30) & 1 == 0  # bit 30: previous key state
        assert (lp >> 31) & 1 == 0  # bit 31: transition state

    def test_keyup_transition_flags_set(self):
        lp = WindowController._make_lparam(0x1E, True)
        assert (lp >> 30) & 1 == 1  # bit 30: previous key state = 1
        assert (lp >> 31) & 1 == 1  # bit 31: transition state = 1

    def test_keyup_scan_code_preserved(self):
        scan = 0x39  # space
        lp = WindowController._make_lparam(scan, True)
        extracted = (lp >> 16) & 0xFF
        assert extracted == scan

    def test_keyup_repeat_count_is_1(self):
        lp = WindowController._make_lparam(0x1E, True)
        assert lp & 0xFFFF == 1

    def test_different_scan_codes(self):
        for scan in (0x01, 0x0E, 0x1C, 0x39, 0x7F):
            lp_down = WindowController._make_lparam(scan, False)
            lp_up = WindowController._make_lparam(scan, True)
            assert (lp_down >> 16) & 0xFF == scan
            assert (lp_up >> 16) & 0xFF == scan
            # keyup should have higher value due to transition bits
            assert lp_up > lp_down


# ── send_keys branching ──────────────────────────────────────────────


class TestSendKeysBranching:
    """Test that send_keys routes to the correct internal methods for all 4 combinations."""

    def test_default_focus_with_tags(self):
        """Default mode: focus_window + keyboard.type + _send_tag for tags."""
        ctrl = _make_ctrl()
        ctrl.focus_window = MagicMock(return_value=True)
        ctrl._send_tag = MagicMock()

        ctrl.send_keys("hi{enter}")

        ctrl.focus_window.assert_called_once()
        # 'h' and 'i' typed individually
        assert ctrl.keyboard.type.call_count == 2
        ctrl._send_tag.assert_called_once_with("enter")

    def test_raw_mode_focus(self):
        """Raw mode with focus: keyboard.type for text, send_special_key for newlines."""
        ctrl = _make_ctrl()
        ctrl.focus_window = MagicMock(return_value=True)
        ctrl.send_special_key = MagicMock()

        ctrl.send_keys("line1\nline2\n", raw=True)

        ctrl.focus_window.assert_called_once()
        # Two text segments typed
        ctrl.keyboard.type.assert_any_call("line1")
        ctrl.keyboard.type.assert_any_call("line2")
        # Two Enter presses (after line1 and after line2)
        assert ctrl.send_special_key.call_count == 2
        for c in ctrl.send_special_key.call_args_list:
            assert c == call("enter", [], delay_ms=100)

    def test_no_focus_with_tags(self):
        """No-focus mode: PostMessage for text + tags, no focus_window call."""
        ctrl = _make_ctrl(target_child_hwnd=99999)
        ctrl.focus_window = MagicMock()
        ctrl._post_message_text = MagicMock()
        ctrl._send_tag = MagicMock()

        ctrl.send_keys("ab{enter}", no_focus=True)

        ctrl.focus_window.assert_not_called()
        # Characters sent via PostMessage
        assert ctrl._post_message_text.call_count == 2
        ctrl._post_message_text.assert_any_call(99999, "a")
        ctrl._post_message_text.assert_any_call(99999, "b")
        # Tag sent with no_focus=True
        ctrl._send_tag.assert_called_once_with("enter", no_focus=True)

    def test_raw_no_focus(self):
        """Raw + no-focus: PostMessage text + PostMessage enter for newlines."""
        ctrl = _make_ctrl(target_child_hwnd=99999)
        ctrl.focus_window = MagicMock()
        ctrl._post_message_text = MagicMock()
        ctrl._post_message_special_key = MagicMock()

        ctrl.send_keys("cmd1\ncmd2", raw=True, no_focus=True)

        ctrl.focus_window.assert_not_called()
        ctrl._post_message_text.assert_any_call(99999, "cmd1")
        ctrl._post_message_text.assert_any_call(99999, "cmd2")
        ctrl._post_message_special_key.assert_called_once_with(99999, "enter")

    def test_raw_consecutive_newlines(self):
        """Raw mode: consecutive newlines produce multiple Enter presses."""
        ctrl = _make_ctrl()
        ctrl.focus_window = MagicMock(return_value=True)
        ctrl.send_special_key = MagicMock()

        ctrl.send_keys("\n\n\n", raw=True)

        # 3 newlines = 3 Enter presses
        assert ctrl.send_special_key.call_count == 3

    def test_raw_no_focus_consecutive_newlines(self):
        """Raw + no-focus: consecutive newlines produce multiple PostMessage enters."""
        ctrl = _make_ctrl(target_child_hwnd=99999)
        ctrl.focus_window = MagicMock()
        ctrl._post_message_text = MagicMock()
        ctrl._post_message_special_key = MagicMock()

        ctrl.send_keys("\n\n", raw=True, no_focus=True)

        assert ctrl._post_message_special_key.call_count == 2

    def test_no_focus_no_target_logs_error(self):
        """No-focus with no target window should not crash."""
        ctrl = _make_ctrl(target_hwnd=None, target_child_hwnd=None)
        ctrl.focus_window = MagicMock()

        # Should return without error (logs warning internally)
        ctrl.send_keys("test", no_focus=True)
        ctrl.focus_window.assert_not_called()

    def test_tags_not_interpreted_in_raw_mode(self):
        """Raw mode should NOT interpret {enter} as a tag."""
        ctrl = _make_ctrl()
        ctrl.focus_window = MagicMock(return_value=True)
        ctrl._send_tag = MagicMock()

        ctrl.send_keys("{enter}", raw=True)

        ctrl._send_tag.assert_not_called()
        ctrl.keyboard.type.assert_called_once_with("{enter}")


# ── set_target_window ────────────────────────────────────────────────


class TestSetTargetWindow:
    def _make_ctrl_with_windows(self, windows):
        ctrl = _make_ctrl(target_hwnd=None, target_title=None)
        ctrl.list_windows = MagicMock(return_value=windows)
        ctrl._find_deepest_child = MagicMock(return_value=None)
        return ctrl

    def test_exact_match(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 111, "title": "Notepad"},
        ])
        result = ctrl.set_target_window("Notepad")
        assert ctrl.target_hwnd == 111
        assert "Notepad" in result

    def test_partial_match(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 222, "title": "Remote Desktop Connection"},
        ])
        result = ctrl.set_target_window("Remote")
        assert ctrl.target_hwnd == 222

    def test_case_insensitive(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 333, "title": "Command Prompt"},
        ])
        result = ctrl.set_target_window("command prompt")
        assert ctrl.target_hwnd == 333

    def test_no_match(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 111, "title": "Notepad"},
        ])
        result = ctrl.set_target_window("Firefox")
        assert "No window found" in result
        assert ctrl.target_hwnd is None

    def test_multiple_matches(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 111, "title": "Notepad - file1.txt"},
            {"hwnd": 222, "title": "Notepad - file2.txt"},
        ])
        result = ctrl.set_target_window("Notepad")
        assert "Multiple windows" in result
        # target should NOT be set when ambiguous
        assert ctrl.target_hwnd is None

    def test_find_deepest_child_called(self):
        ctrl = self._make_ctrl_with_windows([
            {"hwnd": 444, "title": "Test App"},
        ])
        ctrl.set_target_window("Test App")
        ctrl._find_deepest_child.assert_called_once_with(444)
