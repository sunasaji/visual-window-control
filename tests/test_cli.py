"""Tests for CLI argument parsing and config resolution."""

import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# Mock Windows-only modules before importing CLI
with patch.dict("sys.modules", {
    "pynput": MagicMock(),
    "pynput.keyboard": MagicMock(),
    "pynput.mouse": MagicMock(),
    "mss": MagicMock(),
    "pytesseract": MagicMock(),
}):
    from visual_window_control.cli import _resolve, _load_config, build_parser


# ── _resolve ──────────────────────────────────────────────────────────


class TestResolve:
    def test_cli_wins_over_env_and_config(self):
        with patch.dict(os.environ, {"TEST_VAR": "env_val"}):
            result = _resolve("key", "cli_val", "TEST_VAR", {"key": "cfg_val"})
            assert result == "cli_val"

    def test_env_wins_over_config(self):
        with patch.dict(os.environ, {"TEST_VAR": "env_val"}):
            result = _resolve("key", None, "TEST_VAR", {"key": "cfg_val"})
            assert result == "env_val"

    def test_config_used_as_fallback(self):
        with patch.dict(os.environ, {}, clear=False):
            # Ensure env var is not set
            os.environ.pop("TEST_VAR", None)
            result = _resolve("key", None, "TEST_VAR", {"key": "cfg_val"})
            assert result == "cfg_val"

    def test_returns_none_when_all_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_VAR", None)
            result = _resolve("key", None, "TEST_VAR", {})
            assert result is None

    def test_convert_applied_to_env(self):
        with patch.dict(os.environ, {"TEST_VAR": "42"}):
            result = _resolve("key", None, "TEST_VAR", {}, convert=int)
            assert result == 42

    def test_convert_applied_to_config(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_VAR", None)
            result = _resolve("key", None, "TEST_VAR", {"key": "42"}, convert=int)
            assert result == 42

    def test_convert_not_applied_to_cli(self):
        # CLI values are already the right type
        result = _resolve("key", "hello", "TEST_VAR", {}, convert=int)
        assert result == "hello"


# ── _load_config ──────────────────────────────────────────────────────


class TestLoadConfig:
    def test_loads_toml_file(self, tmp_path):
        cfg = tmp_path / "test.toml"
        cfg.write_text('window = "Remote Desktop"\nno_focus = true\n')
        config = _load_config(str(cfg))
        assert config["window"] == "Remote Desktop"
        assert config["no_focus"] is True

    def test_returns_empty_dict_when_no_config(self):
        config = _load_config("/nonexistent/path/config.toml")
        assert config == {}

    def test_env_var_config_path(self, tmp_path):
        cfg = tmp_path / "test.toml"
        cfg.write_text('window = "Test"\n')
        with patch.dict(os.environ, {"VWCTL_CONFIG": str(cfg)}):
            config = _load_config()
            assert config["window"] == "Test"


# ── build_parser ──────────────────────────────────────────────────────


class TestBuildParser:
    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_list_windows(self, parser):
        args = parser.parse_args(["list-windows"])
        assert args.command == "list-windows"

    def test_type_command(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "hello{enter}"])
        assert args.window == "Test"
        assert args.text == "hello{enter}"
        assert args.raw is False

    def test_type_raw(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "-r", "hello"])
        assert args.raw is True

    def test_key_with_modifier(self, parser):
        args = parser.parse_args(["-w", "Test", "key", "c", "-m", "ctrl"])
        assert args.key == "c"
        assert args.mod == ["ctrl"]

    def test_click(self, parser):
        args = parser.parse_args(["-w", "Test", "click", "100", "200"])
        assert args.x == 100
        assert args.y == 200

    def test_capture_default(self, parser):
        args = parser.parse_args(["-w", "Test", "capture"])
        assert args.output is None
        assert args.base64 is False
        assert args.background is False

    def test_capture_background(self, parser):
        args = parser.parse_args(["-w", "Test", "capture", "-b"])
        assert args.background is True

    def test_capture_output(self, parser):
        args = parser.parse_args(["-w", "Test", "capture", "-o", "test.png"])
        assert args.output == "test.png"

    def test_exec_with_wait(self, parser):
        args = parser.parse_args(["-w", "Test", "exec", "ls", "-W", "3.0"])
        assert args.command == "ls"
        assert args.wait == 3.0

    def test_exec_default_wait(self, parser):
        args = parser.parse_args(["-w", "Test", "exec", "ls"])
        assert args.wait == 1.0

    def test_hwnd_option(self, parser):
        args = parser.parse_args(["-H", "12345", "ocr"])
        assert args.hwnd == 12345

    def test_no_focus_flag(self, parser):
        args = parser.parse_args(["-w", "Test", "-n", "type", "hello"])
        assert args.no_focus is True

    def test_move_relative(self, parser):
        args = parser.parse_args(["-w", "Test", "move", "10", "20", "-r"])
        assert args.relative is True

    def test_drag(self, parser):
        args = parser.parse_args(["-w", "Test", "drag", "0", "0", "100", "100"])
        assert args.start_x == 0
        assert args.end_x == 100

    def test_scroll(self, parser):
        args = parser.parse_args(["-w", "Test", "scroll", "-3"])
        assert args.amount == -3

    def test_missing_command_fails(self, parser):
        with pytest.raises(SystemExit):
            parser.parse_args([])
