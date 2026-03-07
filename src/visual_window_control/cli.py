"""CLI for visual window control."""

import argparse
import base64
import datetime
import io
import json
import os
import sys
import time

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

from .ocr import TerminalOCR
from .window_control import WindowController

_controller: WindowController | None = None
_ocr: TerminalOCR | None = None
_config: dict | None = None


# ── Config loading ────────────────────────────────────────────────────


def _load_config(config_path: str | None = None) -> dict:
    """Load config from TOML file.

    Search order (first found wins):
      1. config_path argument (--config CLI arg)
      2. VWCTL_CONFIG environment variable
      3. ./vwctl.toml (current directory)
      4. ~/.config/vwctl/config.toml (Linux) / %APPDATA%\\vwctl\\config.toml (Windows)
    """
    import tomllib

    candidates: list[str] = []
    if config_path:
        candidates.append(config_path)
    env_config = os.environ.get("VWCTL_CONFIG")
    if env_config:
        candidates.append(env_config)
    candidates.append(os.path.join(os.getcwd(), "vwctl.toml"))
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            candidates.append(os.path.join(appdata, "vwctl", "config.toml"))
    else:
        candidates.append(os.path.expanduser("~/.config/vwctl/config.toml"))

    for path in candidates:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return tomllib.load(f)
    return {}


def get_config(config_path: str | None = None) -> dict:
    global _config
    if _config is None:
        _config = _load_config(config_path)
    return _config


def _resolve(key: str, cli_val, env_name: str, config: dict, *, convert=None):
    """Resolve a setting value with priority: CLI arg > env var > config file."""
    if cli_val is not None:
        return cli_val
    env_val = os.environ.get(env_name)
    if env_val is not None:
        return convert(env_val) if convert else env_val
    cfg_val = config.get(key)
    if cfg_val is not None:
        return convert(cfg_val) if convert else cfg_val
    return None


# ── Singletons ────────────────────────────────────────────────────────


def get_controller() -> WindowController:
    global _controller
    if _controller is None:
        _controller = WindowController()
    return _controller


def get_ocr() -> TerminalOCR:
    global _ocr
    if _ocr is None:
        config = get_config()
        ocr_cmd = _resolve("ocr_cmd", None, "VWCTL_OCR_CMD", config)
        _ocr = TerminalOCR(tesseract_cmd=ocr_cmd)
    return _ocr


def _set_window(args: argparse.Namespace) -> int:
    """Set target window from resolved args. Returns 0 on success, 1 on failure."""
    ctrl = get_controller()
    config = get_config()
    hwnd = _resolve("hwnd", args.hwnd, "VWCTL_HWND", config, convert=int)
    title = _resolve("window", args.window, "VWCTL_WINDOW", config)
    if hwnd:
        result = ctrl.set_target_hwnd(int(hwnd))
    elif title:
        result = ctrl.set_target_window(title)
    else:
        print("Error: -w/--window or -H/--hwnd is required for this command", file=sys.stderr)
        return 1
    if result.startswith("No window found") or result.startswith("Multiple windows") or result.startswith("Error"):
        print(result, file=sys.stderr)
        return 1
    return 0


def _get_capture_log_dir() -> str | None:
    config = get_config()
    return _resolve("capture_log_dir", None, "VWCTL_CAPTURE_LOG_DIR", config)


def _is_no_focus(args: argparse.Namespace) -> bool:
    config = get_config()
    val = _resolve("no_focus", getattr(args, "no_focus", None), "VWCTL_NO_FOCUS", config)
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).lower() in ("1", "true", "yes")


def _error(msg: str) -> int:
    print(msg, file=sys.stderr)
    return 1


# ── Subcommand handlers ──────────────────────────────────────────────


def cmd_list_windows(args: argparse.Namespace) -> int:
    ctrl = get_controller()
    windows = ctrl.list_windows()
    print(json.dumps(windows, indent=2, ensure_ascii=False))
    return 0


def cmd_type(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    ctrl.send_keys(args.text, raw=args.raw, no_focus=_is_no_focus(args))
    print(f"Typed {len(args.text)} characters")
    return 0


def cmd_key(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    modifiers = args.mod or []
    ctrl.send_special_key(args.key, modifiers, no_focus=_is_no_focus(args))
    mod_str = "+".join(modifiers) + "+" if modifiers else ""
    print(f"Sent: {mod_str}{args.key}")
    return 0


def cmd_keys(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    steps = json.loads(args.steps_json)
    no_focus = _is_no_focus(args)
    for step in steps:
        key = step.get("key")
        if not key:
            continue
        modifiers = step.get("modifiers")
        delay_ms = step.get("delay_ms")
        ctrl.send_special_key(key, modifiers, delay_ms, no_focus=no_focus)
    print(f"Sent {len(steps)} key steps")
    return 0


def cmd_click(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    ctrl.click(args.x, args.y, args.button)
    print(f"Clicked {args.button} at ({args.x}, {args.y})")
    return 0


def cmd_move(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    ctrl.mouse_move(args.x, args.y, args.relative)
    if args.relative:
        print(f"Moved mouse by ({args.x}, {args.y})")
    else:
        print(f"Moved mouse to ({args.x}, {args.y})")
    return 0


def cmd_drag(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    ctrl.mouse_drag(args.start_x, args.start_y, args.end_x, args.end_y, args.button)
    print(f"Dragged {args.button} from ({args.start_x}, {args.start_y}) to ({args.end_x}, {args.end_y})")
    return 0


def cmd_scroll(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    ctrl.mouse_scroll(args.amount)
    direction = "up" if args.amount > 0 else "down"
    print(f"Scrolled {direction} by {abs(args.amount)}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    image = ctrl.capture_window(background=args.background)
    if image is None:
        return _error("Error: Could not capture window")

    if args.base64:
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=85)
        print(base64.standard_b64encode(buf.getvalue()).decode("ascii"))
    else:
        if args.output:
            output = args.output
        else:
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{ts}_vwctl.jpg"
            capture_dir = _get_capture_log_dir()
            if capture_dir:
                os.makedirs(capture_dir, exist_ok=True)
                filename = os.path.join(capture_dir, filename)
            output = filename
        fmt = "PNG" if output.lower().endswith(".png") else "JPEG"
        save_kwargs = {"quality": 85} if fmt == "JPEG" else {}
        image.save(output, format=fmt, **save_kwargs)
        print(f"Saved: {output} ({image.width}x{image.height})")
    return 0


def cmd_ocr(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()
    image = ctrl.capture_window(background=args.background)
    if image is None:
        return _error("Error: Could not capture window")

    text = get_ocr().extract_text(image)
    print(text)
    return 0


def cmd_exec(args: argparse.Namespace) -> int:
    if rc := _set_window(args):
        return rc
    ctrl = get_controller()

    # Click center to ensure focus
    window_rect = ctrl.get_window_rect()
    if window_rect:
        _, _, width, height = window_rect
        ctrl.click(width // 2, height // 2, "left")
        time.sleep(0.1)

    ctrl.send_keys(args.command, raw=True)
    time.sleep(0.1)
    ctrl.send_special_key("enter", [])
    time.sleep(args.wait)

    image = ctrl.capture_window()
    if image is None:
        return _error("Error: Could not capture window")

    text = get_ocr().extract_text(image)
    print(text)
    return 0


# ── Parser ────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vwctl",
        description="CLI tool for visual window control via OCR",
    )
    parser.add_argument("-w", "--window", default=None,
                        help="Target window title (partial match) (env: VWCTL_WINDOW)")
    parser.add_argument("-H", "--hwnd", type=int, default=None,
                        help="Target window handle (env: VWCTL_HWND)")
    parser.add_argument("-c", "--config", dest="config_file", default=None,
                        help="Config file path (env: VWCTL_CONFIG)")
    parser.add_argument("-n", "--no-focus", action="store_true", default=None,
                        help="Send input via PostMessage without stealing focus (env: VWCTL_NO_FOCUS). "
                             "Works with cmd.exe, Git Bash, PuTTY, etc. May not work with RDP or browser-based apps.")

    sub = parser.add_subparsers(dest="command", required=True)

    # list-windows
    p = sub.add_parser("list-windows", help="List all visible windows")
    p.set_defaults(func=cmd_list_windows)

    # type
    p = sub.add_parser("type", help="Type text with inline tags")
    p.add_argument("text", help='Text to type, e.g. "ls -la{enter}"')
    p.add_argument("-r", "--raw", action="store_true",
                   help="Disable tag interpretation; newlines become Enter")
    p.set_defaults(func=cmd_type)

    # key
    p = sub.add_parser("key", help="Send a single key press")
    p.add_argument("key", help="Key name (e.g. enter, tab, a, f1)")
    p.add_argument("-m", "--mod", action="append", help="Modifier key (ctrl, shift, alt)")
    p.set_defaults(func=cmd_key)

    # keys
    p = sub.add_parser("keys", help="Send a key sequence (JSON)")
    p.add_argument("steps_json", help='JSON array, e.g. \'[{"key":"a"},{"key":"b"}]\'')
    p.set_defaults(func=cmd_keys)

    # click
    p = sub.add_parser("click", help="Click at position in target window")
    p.add_argument("x", type=int, help="X coordinate relative to window")
    p.add_argument("y", type=int, help="Y coordinate relative to window")
    p.add_argument("-b", "--button", default="left", choices=["left", "right", "middle"])
    p.set_defaults(func=cmd_click)

    # move
    p = sub.add_parser("move", help="Move mouse cursor")
    p.add_argument("x", type=int, help="X coordinate relative to window, or X offset")
    p.add_argument("y", type=int, help="Y coordinate relative to window, or Y offset")
    p.add_argument("-r", "--relative", action="store_true", help="Relative movement")
    p.set_defaults(func=cmd_move)

    # drag
    p = sub.add_parser("drag", help="Drag mouse from start to end")
    p.add_argument("start_x", type=int)
    p.add_argument("start_y", type=int)
    p.add_argument("end_x", type=int)
    p.add_argument("end_y", type=int)
    p.add_argument("-b", "--button", default="left", choices=["left", "right", "middle"])
    p.set_defaults(func=cmd_drag)

    # scroll
    p = sub.add_parser("scroll", help="Scroll mouse wheel")
    p.add_argument("amount", type=int, help="Scroll amount (+up, -down)")
    p.set_defaults(func=cmd_scroll)

    # capture
    p = sub.add_parser("capture", help="Capture window to file or stdout")
    p.add_argument("-o", "--output", default=None, help="Output file (default: timestamp_vwctl.jpg; use .png extension for PNG)")
    p.add_argument("-e", "--base64", action="store_true", help="Output base64-encoded JPEG to stdout")
    p.add_argument("-b", "--background", action="store_true",
                   help="Use PrintWindow API (works when occluded, but may produce black images for hardware-accelerated apps)")
    p.set_defaults(func=cmd_capture)

    # ocr
    p = sub.add_parser("ocr", help="Capture window and extract text via OCR")
    p.add_argument("-b", "--background", action="store_true",
                   help="Use PrintWindow API (works when occluded, but may produce black images for hardware-accelerated apps)")
    p.set_defaults(func=cmd_ocr)

    # exec
    p = sub.add_parser("exec", help="Type command, press Enter, wait, then OCR")
    p.add_argument("command", help="Command to execute")
    p.add_argument("-W", "--wait", type=float, default=1.0, help="Wait seconds (default: 1.0)")
    p.set_defaults(func=cmd_exec)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Load config file (before any command runs)
    get_config(args.config_file)

    try:
        rc = args.func(args)
        sys.exit(rc)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        sys.exit(_error(f"Error: {e}"))


if __name__ == "__main__":
    main()
