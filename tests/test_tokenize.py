"""Tests for WindowController._tokenize and _is_valid_tag."""

from unittest.mock import patch, MagicMock

import pytest

# Mock pynput before importing window_control
with patch.dict("sys.modules", {
    "pynput": MagicMock(),
    "pynput.keyboard": MagicMock(),
    "pynput.mouse": MagicMock(),
    "mss": MagicMock(),
}):
    from visual_window_control.window_control import WindowController


@pytest.fixture
def ctrl():
    with patch.object(WindowController, "__init__", lambda self: None):
        c = WindowController.__new__(WindowController)
        # Set up only what _tokenize and _is_valid_tag need
        c.special_keys = {
            "enter": None, "return": None, "tab": None,
            "escape": None, "esc": None, "backspace": None,
            "delete": None, "up": None, "down": None,
            "left": None, "right": None, "home": None,
            "end": None, "pageup": None, "pagedown": None,
            "space": None,
            "f1": None, "f2": None, "f3": None, "f4": None,
            "f5": None, "f6": None, "f7": None, "f8": None,
            "f9": None, "f10": None, "f11": None, "f12": None,
        }
        c.modifier_keys = {
            "ctrl": None, "control": None, "alt": None, "shift": None,
        }
        return c


# ── _is_valid_tag ─────────────────────────────────────────────────────


class TestIsValidTag:
    def test_known_special_keys(self, ctrl):
        for key in ("enter", "tab", "escape", "backspace", "delete",
                     "up", "down", "left", "right", "f1", "f12", "space"):
            assert ctrl._is_valid_tag(key) is True

    def test_modifier_plus_key(self, ctrl):
        assert ctrl._is_valid_tag("ctrl+c") is True
        assert ctrl._is_valid_tag("alt+f4") is True
        assert ctrl._is_valid_tag("shift+tab") is True
        assert ctrl._is_valid_tag("ctrl+shift+a") is True

    def test_single_char_key(self, ctrl):
        assert ctrl._is_valid_tag("ctrl+a") is True
        assert ctrl._is_valid_tag("ctrl+z") is True

    def test_unknown_tag_rejected(self, ctrl):
        assert ctrl._is_valid_tag("print $1") is False
        assert ctrl._is_valid_tag("foo") is False
        assert ctrl._is_valid_tag("hello world") is False

    def test_modifier_only_rejected(self, ctrl):
        assert ctrl._is_valid_tag("ctrl") is False
        assert ctrl._is_valid_tag("ctrl+shift") is False

    def test_multiple_non_modifier_parts_rejected(self, ctrl):
        assert ctrl._is_valid_tag("enter+tab") is False


# ── _tokenize ─────────────────────────────────────────────────────────


class TestTokenize:
    def test_plain_text(self, ctrl):
        tokens = ctrl._tokenize("hello")
        assert tokens == list("hello")

    def test_known_tag(self, ctrl):
        tokens = ctrl._tokenize("{enter}")
        assert tokens == ["\x01enter"]

    def test_text_with_tag(self, ctrl):
        tokens = ctrl._tokenize("ls -la{enter}")
        assert tokens == list("ls -la") + ["\x01enter"]

    def test_modifier_tag(self, ctrl):
        tokens = ctrl._tokenize("{ctrl+c}")
        assert tokens == ["\x01ctrl+c"]

    def test_unknown_tag_passthrough(self, ctrl):
        tokens = ctrl._tokenize("awk '{print $1}'")
        # {print $1} is not a known tag, so braces pass through literally
        assert "".join(tokens) == "awk '{print $1}'"

    def test_escaped_braces(self, ctrl):
        tokens = ctrl._tokenize("echo {{enter}}")
        assert "".join(t if not t.startswith("\x01") else t for t in tokens) == "echo {enter}"

    def test_double_closing_brace(self, ctrl):
        tokens = ctrl._tokenize("a}}b")
        assert "".join(tokens) == "a}b"

    def test_unclosed_brace(self, ctrl):
        tokens = ctrl._tokenize("hello {world")
        assert "".join(tokens) == "hello {world"

    def test_multiple_tags(self, ctrl):
        tokens = ctrl._tokenize("a{tab}b{enter}")
        assert tokens == ["a", "\x01tab", "b", "\x01enter"]

    def test_empty_string(self, ctrl):
        assert ctrl._tokenize("") == []

    def test_consecutive_tags(self, ctrl):
        tokens = ctrl._tokenize("{up}{up}{enter}")
        assert tokens == ["\x01up", "\x01up", "\x01enter"]

    def test_curly_braces_in_code(self, ctrl):
        code = "if (x) { return 0; }"
        tokens = ctrl._tokenize(code)
        # None of these are valid tags, so all pass through
        assert "".join(tokens) == code

    def test_python_dict_literal(self, ctrl):
        code = '{"key": "value"}'
        tokens = ctrl._tokenize(code)
        assert "".join(tokens) == code

    def test_f_key_tag(self, ctrl):
        tokens = ctrl._tokenize("{f1}")
        assert tokens == ["\x01f1"]

    def test_alt_f4(self, ctrl):
        tokens = ctrl._tokenize("{alt+f4}")
        assert tokens == ["\x01alt+f4"]
