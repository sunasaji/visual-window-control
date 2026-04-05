"""Tests for CLI argument parsing and config resolution."""

import argparse
import os
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
    import visual_window_control.cli as _cli_mod
    from visual_window_control.cli import _resolve, _load_config, build_parser, cmd_list_windows, cmd_type, cmd_key, cmd_keys, _get_jpeg_quality
    from visual_window_control.window_control import FocusLostError


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


# ── _get_jpeg_quality ─────────────────────────────────────────────────


class TestGetJpegQuality:
    def _make_args(self, jpeg_quality=None):
        return argparse.Namespace(jpeg_quality=jpeg_quality, config=None)

    def test_default(self):
        with patch.object(_cli_mod, "get_config", return_value={}):
            assert _get_jpeg_quality(self._make_args()) == 85

    def test_cli_arg(self):
        with patch.object(_cli_mod, "get_config", return_value={}):
            assert _get_jpeg_quality(self._make_args(jpeg_quality=60)) == 60

    def test_env_var(self):
        with patch.object(_cli_mod, "get_config", return_value={}), \
             patch.dict(os.environ, {"VWCTL_JPEG_QUALITY": "70"}):
            assert _get_jpeg_quality(self._make_args()) == 70

    def test_config_file(self):
        with patch.object(_cli_mod, "get_config", return_value={"jpeg_quality": 50}):
            assert _get_jpeg_quality(self._make_args()) == 50

    def test_cli_overrides_config(self):
        with patch.object(_cli_mod, "get_config", return_value={"jpeg_quality": 50}):
            assert _get_jpeg_quality(self._make_args(jpeg_quality=90)) == 90


# ── build_parser ──────────────────────────────────────────────────────


class TestBuildParser:
    @pytest.fixture
    def parser(self):
        return build_parser()

    def test_list_windows(self, parser):
        args = parser.parse_args(["list"])
        assert args.command == "list"
        assert args.json is False

    def test_list_windows_json_flag(self, parser):
        args = parser.parse_args(["list", "--json"])
        assert args.json is True

    def test_type_command(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "hello{enter}"])
        assert args.window == "Test"
        assert args.text == "hello{enter}"
        assert args.raw is False

    def test_type_no_text_arg(self, parser):
        args = parser.parse_args(["-w", "Test", "type"])
        assert args.text is None

    def test_type_raw(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "-r", "hello"])
        assert args.raw is True

    def test_type_file_option(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "--file", "input.txt"])
        assert args.file == "input.txt"
        assert args.text is None

    def test_type_file_dash_stdin(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "-f", "-"])
        assert args.file == "-"
        assert args.text is None

    def test_type_tags_flag(self, parser):
        args = parser.parse_args(["-w", "Test", "type", "-t", "-f", "input.txt"])
        assert args.tags is True
        assert args.raw is False

    def test_key_with_modifier(self, parser):
        args = parser.parse_args(["-w", "Test", "key", "c", "-m", "ctrl"])
        assert args.key == "c"
        assert args.mod == ["ctrl"]

    def test_key_delay_default_none(self, parser):
        args = parser.parse_args(["-w", "Test", "key", "enter"])
        assert args.delay is None

    def test_key_delay_short_flag(self, parser):
        args = parser.parse_args(["-w", "Test", "key", "enter", "-d", "200"])
        assert args.delay == 200

    def test_key_delay_long_flag(self, parser):
        args = parser.parse_args(["-w", "Test", "key", "f", "-m", "alt", "--delay", "800"])
        assert args.delay == 800

    def test_click(self, parser):
        args = parser.parse_args(["-w", "Test", "click", "100", "200"])
        assert args.x == 100
        assert args.y == 200

    def test_capture_default(self, parser):
        args = parser.parse_args(["-w", "Test", "capture"])
        assert args.output is None
        assert args.base64 is False
        assert args.background is False

    def test_capture_jpeg_quality(self, parser):
        args = parser.parse_args(["-w", "Test", "capture", "-q", "60"])
        assert args.jpeg_quality == 60

    def test_capture_jpeg_quality_default(self, parser):
        args = parser.parse_args(["-w", "Test", "capture"])
        assert args.jpeg_quality is None

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


# ── cmd_list_windows ─────────────────────────────────────────────────


_FAKE_WINDOWS = [
    {"hwnd": 200864, "title": "Windows PowerShell"},
    {"hwnd": 12345, "title": "Untitled - Notepad"},
]


class TestCmdListWindows:
    def _make_args(self, *, json_flag: bool) -> argparse.Namespace:
        return argparse.Namespace(json=json_flag)

    def test_plain_output(self, capsys):
        with patch.object(_cli_mod, "get_controller") as mock_gc:
            mock_gc.return_value.list_windows.return_value = _FAKE_WINDOWS
            rc = cmd_list_windows(self._make_args(json_flag=False))
        assert rc == 0
        out = capsys.readouterr().out
        lines = out.splitlines()
        assert len(lines) == 2
        assert lines[0] == "200864  Windows PowerShell"
        assert lines[1] == "12345  Untitled - Notepad"

    def test_json_output(self, capsys):
        with patch.object(_cli_mod, "get_controller") as mock_gc:
            mock_gc.return_value.list_windows.return_value = _FAKE_WINDOWS
            rc = cmd_list_windows(self._make_args(json_flag=True))
        assert rc == 0
        import json
        out = capsys.readouterr().out
        data = json.loads(out)
        assert len(data) == 2
        assert data[0]["hwnd"] == 200864
        assert data[1]["title"] == "Untitled - Notepad"

    def test_plain_empty(self, capsys):
        with patch.object(_cli_mod, "get_controller") as mock_gc:
            mock_gc.return_value.list_windows.return_value = []
            rc = cmd_list_windows(self._make_args(json_flag=False))
        assert rc == 0
        assert capsys.readouterr().out == ""


# ── cmd_type ─────────────────────────────────────────────────────────


class TestCmdType:
    def _make_args(self, text=None, raw=False, tags=False, window="Test",
                   hwnd=None, no_focus=False, config=None, file=None):
        return argparse.Namespace(
            text=text, raw=raw, tags=tags, window=window, hwnd=hwnd,
            no_focus=no_focus, config=config, file=file,
        )

    def _patch_set_window(self):
        return patch.object(_cli_mod, "_set_window", return_value=0)

    def test_text_arg(self, capsys):
        """Text argument: calls send_keys with check_focus=True."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(text="hello"))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "hello", raw=False, no_focus=False, check_focus=True,
        )
        assert "5 characters" in capsys.readouterr().out

    def test_stdin_input(self, capsys):
        """Stdin input: reads line by line, defaults to raw mode."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.__iter__ = MagicMock(return_value=iter(["line1\n", "line2\n"]))
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(text=None))
        assert rc == 0
        assert ctrl.send_keys.call_count == 2
        # stdin defaults to raw=True
        ctrl.send_keys.assert_any_call(
            "line1\n", raw=True, no_focus=False, check_focus=True,
        )
        assert "12 characters" in capsys.readouterr().out

    def test_text_arg_wins_over_stdin(self, capsys):
        """Both text arg and stdin: text arg wins, stdin is drained."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = ""
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(text="hello"))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "hello", raw=False, no_focus=False, check_focus=True,
        )
        assert "5 characters" in capsys.readouterr().out

    def test_neither_text_nor_stdin_errors(self, capsys):
        """No text arg and no stdin: returns error."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller"), \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            rc = cmd_type(self._make_args(text=None))
        assert rc == 1
        assert "required" in capsys.readouterr().err

    def test_focus_lost_text_arg(self, capsys):
        """Focus loss during text arg typing: reports abort."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            ctrl = mock_gc.return_value
            ctrl.send_keys.side_effect = FocusLostError(3)
            rc = cmd_type(self._make_args(text="hello"))
        assert rc == 1
        err = capsys.readouterr().err
        assert "lost focus" in err

    def test_focus_lost_stdin(self, capsys):
        """Focus loss during stdin streaming: reports cumulative chars."""
        call_count = 0

        def fake_send_keys(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise FocusLostError(2)

        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.__iter__ = MagicMock(return_value=iter(["aaa\n", "bbb\n"]))
            ctrl = mock_gc.return_value
            ctrl.send_keys.side_effect = fake_send_keys
            rc = cmd_type(self._make_args(text=None))
        assert rc == 1
        err = capsys.readouterr().err
        assert "lost focus" in err
        # First line "aaa\n" (4 chars) + 2 chars into second line = 6
        assert "6 characters" in err

    def test_file_dash_reads_stdin(self, capsys):
        """--file='-' streams from stdin."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.__iter__ = MagicMock(return_value=iter(["abc\n"]))
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(file="-"))
        assert rc == 0
        ctrl.send_keys.assert_called_once()
        assert "4 characters" in capsys.readouterr().out

    def test_file_option(self, capsys, tmp_path):
        """--file reads text from file, defaults to raw mode."""
        f = tmp_path / "input.txt"
        f.write_text("file content{enter}", encoding="utf-8")
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(file=str(f)))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "file content{enter}", raw=True, no_focus=False, check_focus=True,
        )
        assert "19 characters" in capsys.readouterr().out

    def test_file_with_tags_flag(self, tmp_path):
        """--file with --tags enables tag interpretation."""
        f = tmp_path / "input.txt"
        f.write_text("hello{enter}", encoding="utf-8")
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(file=str(f), tags=True))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "hello{enter}", raw=False, no_focus=False, check_focus=True,
        )

    def test_stdin_with_tags_flag(self):
        """Stdin with --tags enables tag interpretation."""
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.__iter__ = MagicMock(return_value=iter(["hello{enter}\n"]))
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(text=None, tags=True))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "hello{enter}\n", raw=False, no_focus=False, check_focus=True,
        )

    def test_file_option_ignores_stdin(self, tmp_path):
        """--file takes priority over stdin."""
        f = tmp_path / "input.txt"
        f.write_text("from file", encoding="utf-8")
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            ctrl = mock_gc.return_value
            rc = cmd_type(self._make_args(file=str(f)))
        assert rc == 0
        ctrl.send_keys.assert_called_once_with(
            "from file", raw=True, no_focus=False, check_focus=True,
        )


# ── cmd_key ──────────────────────────────────────────────────────────


class TestCmdKey:
    def _make_args(self, key, mod=None, delay=None, window="Test", hwnd=None,
                   no_focus=False, config=None):
        return argparse.Namespace(
            key=key, mod=mod, delay=delay, window=window, hwnd=hwnd,
            no_focus=no_focus, config=config,
        )

    def _patch_set_window(self):
        return patch.object(_cli_mod, "_set_window", return_value=0)

    def test_sends_key_with_default_delay(self):
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False):
            ctrl = mock_gc.return_value
            rc = cmd_key(self._make_args("enter"))
        assert rc == 0
        ctrl.send_special_key.assert_called_once_with(
            "enter", [], None, no_focus=False,
        )

    def test_sends_key_with_custom_delay(self):
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False):
            ctrl = mock_gc.return_value
            rc = cmd_key(self._make_args("f", mod=["alt"], delay=800))
        assert rc == 0
        ctrl.send_special_key.assert_called_once_with(
            "f", ["alt"], 800, no_focus=False,
        )

    def test_sends_key_no_focus_with_delay(self):
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=True):
            ctrl = mock_gc.return_value
            rc = cmd_key(self._make_args("tab", delay=50))
        assert rc == 0
        ctrl.send_special_key.assert_called_once_with(
            "tab", [], 50, no_focus=True,
        )


# ── cmd_keys ─────────────────────────────────────────────────────────


class TestCmdKeys:
    def _make_args(self, steps_json, window="Test", hwnd=None, no_focus=False,
                   config=None):
        return argparse.Namespace(
            steps_json=steps_json, window=window, hwnd=hwnd,
            no_focus=no_focus, config=config,
        )

    def _patch_set_window(self):
        return patch.object(_cli_mod, "_set_window", return_value=0)

    def test_sends_all_steps(self, capsys):
        steps = '[{"key":"tab"},{"key":"enter"}]'
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("visual_window_control.window_control.user32") as mock_u32:
            ctrl = mock_gc.return_value
            ctrl.target_hwnd = 12345
            mock_u32.GetForegroundWindow.return_value = 12345
            rc = cmd_keys(self._make_args(steps))
        assert rc == 0
        assert ctrl.send_special_key.call_count == 2
        assert "2 key steps" in capsys.readouterr().out

    def test_focus_lost_aborts(self, capsys):
        steps = '[{"key":"tab"},{"key":"enter"},{"key":"space"}]'
        call_count = 0

        def fake_get_fg():
            nonlocal call_count
            call_count += 1
            return 12345 if call_count < 3 else 99999
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=False), \
             patch("visual_window_control.window_control.user32") as mock_u32:
            ctrl = mock_gc.return_value
            ctrl.target_hwnd = 12345
            mock_u32.GetForegroundWindow.side_effect = fake_get_fg
            rc = cmd_keys(self._make_args(steps))
        assert rc == 1
        err = capsys.readouterr().err
        assert "lost focus" in err
        assert "2/3" in err

    def test_no_focus_skips_check(self):
        steps = '[{"key":"tab"},{"key":"enter"}]'
        with self._patch_set_window(), \
             patch.object(_cli_mod, "get_controller") as mock_gc, \
             patch.object(_cli_mod, "_is_no_focus", return_value=True):
            ctrl = mock_gc.return_value
            rc = cmd_keys(self._make_args(steps))
        assert rc == 0
        assert ctrl.send_special_key.call_count == 2
