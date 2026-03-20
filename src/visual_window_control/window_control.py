"""Window control utilities for visual window interaction."""

import ctypes
import logging
import re
import time
from ctypes import wintypes
from typing import Literal

import mss
from PIL import Image
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

logger = logging.getLogger(__name__)


class FocusLostError(Exception):
    """Raised when the target window loses foreground focus during input."""

    def __init__(self, chars_sent: int = 0):
        self.chars_sent = chars_sent
        super().__init__(f"Target window lost focus after {chars_sent} characters")


# Windows API constants
SW_RESTORE = 9
SW_SHOW = 5
GWL_STYLE = -16
WS_MINIMIZE = 0x20000000

# SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Load Windows DLLs
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()  # Handle high DPI displays

# Set function argument types
user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
user32.VkKeyScanW.restype = ctypes.c_short
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

psapi = ctypes.windll.psapi
psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
psapi.GetModuleFileNameExW.restype = wintypes.DWORD

dwmapi = ctypes.windll.dwmapi
DWMWA_EXTENDED_FRAME_BOUNDS = 9


# Structures for SendInput
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


class WindowController:
    """Controller for window manipulation and input."""

    def __init__(self):
        """Initialize window controller."""
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.target_hwnd: int | None = None
        self.target_title: str | None = None
        self.target_child_hwnd: int | None = None

        # Special key mapping
        self.special_keys = {
            # Common keys
            "enter": Key.enter, "return": Key.enter,
            "tab": Key.tab,
            "escape": Key.esc, "esc": Key.esc,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "space": Key.space,
            # Arrow keys
            "up": Key.up, "down": Key.down,
            "left": Key.left, "right": Key.right,
            # Navigation
            "home": Key.home, "end": Key.end,
            "pageup": Key.page_up, "pagedown": Key.page_down,
            "insert": Key.insert,
            # Function keys
            "f1": Key.f1, "f2": Key.f2, "f3": Key.f3, "f4": Key.f4,
            "f5": Key.f5, "f6": Key.f6, "f7": Key.f7, "f8": Key.f8,
            "f9": Key.f9, "f10": Key.f10, "f11": Key.f11, "f12": Key.f12,
            "f13": Key.f13, "f14": Key.f14, "f15": Key.f15, "f16": Key.f16,
            "f17": Key.f17, "f18": Key.f18, "f19": Key.f19, "f20": Key.f20,
            "f21": Key.f21, "f22": Key.f22, "f23": Key.f23, "f24": Key.f24,
            # Modifier keys (usable standalone)
            "ctrl": Key.ctrl, "control": Key.ctrl,
            "alt": Key.alt,
            "shift": Key.shift,
            "win": Key.cmd, "super": Key.cmd,
            # Left/right modifier variants
            "ctrl_l": Key.ctrl_l, "ctrl_r": Key.ctrl_r,
            "alt_l": Key.alt_l, "alt_r": Key.alt_r, "alt_gr": Key.alt_gr,
            "shift_r": Key.shift_r,
            "win_r": Key.cmd_r,
            # Lock keys
            "caps_lock": Key.caps_lock, "capslock": Key.caps_lock,
            "num_lock": Key.num_lock, "numlock": Key.num_lock,
            "scroll_lock": Key.scroll_lock, "scrolllock": Key.scroll_lock,
            # System keys
            "print_screen": Key.print_screen, "printscreen": Key.print_screen,
            "pause": Key.pause,
            "menu": Key.menu,
            # Media keys
            "media_play_pause": Key.media_play_pause,
            "media_stop": Key.media_stop,
            "media_volume_mute": Key.media_volume_mute,
            "media_volume_down": Key.media_volume_down,
            "media_volume_up": Key.media_volume_up,
            "media_previous": Key.media_previous,
            "media_next": Key.media_next,
        }

        self.modifier_keys = {
            "ctrl": Key.ctrl, "control": Key.ctrl,
            "ctrl_l": Key.ctrl_l, "ctrl_r": Key.ctrl_r,
            "alt": Key.alt,
            "alt_l": Key.alt_l, "alt_r": Key.alt_r, "alt_gr": Key.alt_gr,
            "shift": Key.shift, "shift_r": Key.shift_r,
            "win": Key.cmd, "super": Key.cmd, "win_r": Key.cmd_r,
        }

        # Virtual key codes for PostMessage (no-focus mode)
        self._vk_map = {
            # Common keys
            "enter": 0x0D, "return": 0x0D, "tab": 0x09,
            "escape": 0x1B, "esc": 0x1B, "backspace": 0x08,
            "delete": 0x2E, "space": 0x20,
            # Arrow keys
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            # Navigation
            "home": 0x24, "end": 0x23,
            "pageup": 0x21, "pagedown": 0x22,
            "insert": 0x2D,
            # Function keys
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
            "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
            "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
            "f13": 0x7C, "f14": 0x7D, "f15": 0x7E, "f16": 0x7F,
            "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
            "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
            # Modifier keys
            "ctrl": 0x11, "control": 0x11,
            "ctrl_l": 0xA2, "ctrl_r": 0xA3,
            "alt": 0x12,
            "alt_l": 0xA4, "alt_r": 0xA5, "alt_gr": 0xA5,
            "shift": 0x10, "shift_r": 0xA1,
            "win": 0x5B, "super": 0x5B, "win_r": 0x5C,
            # Lock keys
            "caps_lock": 0x14, "capslock": 0x14,
            "num_lock": 0x90, "numlock": 0x90,
            "scroll_lock": 0x91, "scrolllock": 0x91,
            # System keys
            "print_screen": 0x2C, "printscreen": 0x2C,
            "pause": 0x13,
            "menu": 0x5D,
            # Media keys
            "media_play_pause": 0xB3,
            "media_stop": 0xB2,
            "media_volume_mute": 0xAD,
            "media_volume_down": 0xAE,
            "media_volume_up": 0xAF,
            "media_previous": 0xB1,
            "media_next": 0xB0,
        }
        self._mod_vk_map = {
            "ctrl": 0x11, "control": 0x11,
            "ctrl_l": 0xA2, "ctrl_r": 0xA3,
            "alt": 0x12,
            "alt_l": 0xA4, "alt_r": 0xA5, "alt_gr": 0xA5,
            "shift": 0x10, "shift_r": 0xA1,
            "win": 0x5B, "super": 0x5B, "win_r": 0x5C,
        }

    def list_windows(self) -> list[dict]:
        """List all visible windows.

        Returns:
            List of dicts with hwnd and title
        """
        windows = []

        def enum_callback(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buffer, length + 1)
                    title = buffer.value
                    if title:  # Skip empty titles
                        windows.append({
                            "hwnd": hwnd,
                            "title": title,
                        })
            return True

        # Define callback type
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

        return windows

    def set_target_window(self, title: str) -> str:
        """Set target window by title (partial match).

        Args:
            title: Window title to search for

        Returns:
            Status message
        """
        windows = self.list_windows()
        title_lower = title.lower()

        matches = [
            w for w in windows
            if title_lower in w["title"].lower()
        ]

        if not matches:
            return f"No window found matching '{title}'"

        if len(matches) > 1:
            lines = [f"  {w['hwnd']}  {w['title']}" for w in matches]
            match_list = "\n".join(lines)
            return f"Multiple windows found:\n{match_list}\nPlease be more specific."

        self.target_hwnd = matches[0]["hwnd"]
        self.target_title = matches[0]["title"]
        self.target_child_hwnd = self._find_deepest_child(self.target_hwnd)  # type: ignore[arg-type]

        return f"Target set to: {self.target_title}"

    def set_target_hwnd(self, hwnd: int) -> str:
        """Set target window by handle directly.

        Args:
            hwnd: Window handle

        Returns:
            Status message
        """
        if not user32.IsWindow(hwnd):
            return f"Error: Invalid window handle {hwnd}"

        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value

        self.target_hwnd = hwnd
        self.target_title = title or f"(hwnd={hwnd})"
        self.target_child_hwnd = self._find_deepest_child(self.target_hwnd)

        return f"Target set to: {self.target_title}"

    def _find_deepest_child(self, hwnd: int) -> int | None:
        """Find a likely input child window for targeting."""
        def enum_child_callback(child_hwnd, lparam):
            if user32.IsWindowVisible(child_hwnd):
                child_list = ctypes.cast(lparam, ctypes.POINTER(ctypes.py_object)).contents.value
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child_hwnd, class_buf, 256)
                child_list.append({
                    "hwnd": child_hwnd,
                    "class": class_buf.value,
                })
            return True

        children: list[dict] = []
        children_ref = ctypes.py_object(children)
        children_ref_id = ctypes.cast(
            ctypes.pointer(children_ref), ctypes.c_void_p
        ).value
        ENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        user32.EnumChildWindows(
            hwnd,
            ENUMPROC(enum_child_callback),
            wintypes.LPARAM(children_ref_id),  # type: ignore[arg-type]
        )

        # Prefer render/input classes for CEF/Chrome hosted windows
        preferred_classes = [
            "Chrome_RenderWidgetHostHWND",
            "Chrome_WidgetWin_0",
            "CefBrowserWindow",
            "Intermediate D3D Window",
        ]
        for cls in preferred_classes:
            for child in children:
                if child["class"] == cls:
                    return child["hwnd"]

        if children:
            return children[-1]["hwnd"]
        return None

    def list_child_windows(self) -> list[dict]:
        """List visible child windows for the target."""
        if self.target_hwnd is None:
            return []

        def enum_child_callback(child_hwnd, lparam):
            if user32.IsWindowVisible(child_hwnd):
                child_list = ctypes.cast(lparam, ctypes.POINTER(ctypes.py_object)).contents.value
                class_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(child_hwnd, class_buf, 256)
                length = user32.GetWindowTextLengthW(child_hwnd)
                title = ""
                if length > 0:
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(child_hwnd, buffer, length + 1)
                    title = buffer.value
                child_list.append({
                    "hwnd": child_hwnd,
                    "class": class_buf.value,
                    "title": title,
                })
            return True

        children: list[dict] = []
        children_ref = ctypes.py_object(children)
        children_ref_id = ctypes.cast(
            ctypes.pointer(children_ref), ctypes.c_void_p
        ).value
        ENUMPROC = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        user32.EnumChildWindows(
            self.target_hwnd,
            ENUMPROC(enum_child_callback),
            wintypes.LPARAM(children_ref_id),  # type: ignore[arg-type]
        )
        return children

    def get_focus_info(self) -> dict:
        """Get focus/foreground info for debugging."""
        info: dict = {
            "target_hwnd": self.target_hwnd,
            "target_child_hwnd": self.target_child_hwnd,
            "foreground_hwnd": None,
            "focus_hwnd": None,
        }

        info["foreground_hwnd"] = user32.GetForegroundWindow()

        if self.target_hwnd is None:
            return info

        current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        target_thread_id = user32.GetWindowThreadProcessId(self.target_hwnd, None)
        attached = False
        if current_thread_id != target_thread_id:
            attached = user32.AttachThreadInput(current_thread_id, target_thread_id, True)
        try:
            info["focus_hwnd"] = user32.GetFocus()
        finally:
            if attached:
                user32.AttachThreadInput(current_thread_id, target_thread_id, False)
        return info

    def _get_process_name(self, hwnd: int) -> str | None:
        """Get process executable name for a window handle."""
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == 0:
            return None

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid.value
        )
        if not handle:
            return None
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleFileNameExW(handle, None, buf, 260) == 0:
                return None
            path = buf.value
            if not path:
                return None
            return path.split("\\")[-1].lower()
        finally:
            kernel32.CloseHandle(handle)

    def send_ctrl_key_wm(self, key: str) -> None:
        """Send Ctrl+<key> using WM_KEYDOWN/WM_KEYUP to the focused window."""
        if len(key) != 1:
            logger.error("send_ctrl_key_wm expects a single character key")
            return

        if not self.focus_window():
            logger.warning("Could not focus window, attempting to send key anyway")

        # Determine target HWND to send messages to
        target_hwnd = self.get_focus_info().get("focus_hwnd") or self.target_child_hwnd or self.target_hwnd
        if not target_hwnd:
            logger.error("No target HWND for WM_KEY messages")
            return

        vk = ord(key.upper())
        sc = user32.MapVirtualKeyW(vk, 0)
        if sc == 0:
            logger.error("Could not map key to scancode: %s", key)
            return

        def make_lparam(scan, keyup):
            # Repeat count=1, scan code in bits 16-23, extended=0, context=0, prev=1 if keyup, transition=1 if keyup
            lparam = 1 | (scan << 16)
            if keyup:
                lparam |= (1 << 30) | (1 << 31)
            return lparam

        # Ctrl down
        user32.PostMessageW(target_hwnd, 0x0100, 0x11, make_lparam(0x1D, False))
        time.sleep(0.01)
        # Key down/up
        user32.PostMessageW(target_hwnd, 0x0100, vk, make_lparam(sc, False))
        user32.PostMessageW(target_hwnd, 0x0101, vk, make_lparam(sc, True))
        time.sleep(0.01)
        # Ctrl up
        user32.PostMessageW(target_hwnd, 0x0101, 0x11, make_lparam(0x1D, True))

    def _send_ctrl_key_keybd_event(self, key: str) -> None:
        """Send Ctrl+<key> using legacy keybd_event (RDP compatibility)."""
        if len(key) != 1:
            logger.error("_send_ctrl_key_keybd_event expects a single character key")
            return

        vk = ord(key.upper())
        sc = user32.MapVirtualKeyW(vk, 0)
        ctrl_sc = user32.MapVirtualKeyW(0x11, 0)

        user32.keybd_event(0x11, ctrl_sc, 0, 0)
        user32.keybd_event(vk, sc, 0, 0)
        user32.keybd_event(vk, sc, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(0x11, ctrl_sc, KEYEVENTF_KEYUP, 0)

    def _send_alt_key_keybd_event(self, key: str) -> None:
        """Send Alt+<key> using legacy keybd_event (RDP compatibility)."""
        if len(key) != 1:
            logger.error("_send_alt_key_keybd_event expects a single character key")
            return

        vk = ord(key.upper())
        sc = user32.MapVirtualKeyW(vk, 0)
        alt_sc = user32.MapVirtualKeyW(0x12, 0)

        user32.keybd_event(0x12, alt_sc, 0, 0)
        user32.keybd_event(vk, sc, 0, 0)
        user32.keybd_event(vk, sc, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(0x12, alt_sc, KEYEVENTF_KEYUP, 0)

    def _get_message_target(self) -> int | None:
        """Get the best HWND for PostMessage (child or main window)."""
        return self.target_child_hwnd or self.target_hwnd

    @staticmethod
    def _make_lparam(scan: int, keyup: bool) -> int:
        lparam = 1 | (scan << 16)
        if keyup:
            lparam |= (1 << 30) | (1 << 31)
        return lparam

    def _post_key(self, hwnd: int, vk: int, down: bool = True, up: bool = True) -> None:
        """Post WM_KEYDOWN/WM_KEYUP for a single virtual key."""
        sc = user32.MapVirtualKeyW(vk, 0)
        if down:
            user32.PostMessageW(hwnd, 0x0100, vk, self._make_lparam(sc, False))
        if up:
            user32.PostMessageW(hwnd, 0x0101, vk, self._make_lparam(sc, True))

    def _post_message_char(self, hwnd: int, char: str) -> None:
        """Send a single character via WM_CHAR."""
        user32.PostMessageW(hwnd, 0x0102, ord(char), 0)

    def _post_message_text(self, hwnd: int, text: str) -> None:
        """Send text via WM_CHAR messages (no focus required)."""
        for ch in text:
            self._post_message_char(hwnd, ch)
            time.sleep(0.02)

    def _post_message_special_key(
        self, hwnd: int, key: str, modifiers: list[str] | None = None
    ) -> None:
        """Send a special key via PostMessage (no focus required)."""
        mods = modifiers or []
        key_lower = key.lower()

        # Single character key (for combos like ctrl+a)
        if len(key) == 1:
            vk = ord(key.upper())
        elif key_lower in self._vk_map:
            vk = self._vk_map[key_lower]
        else:
            logger.error("Unknown key for PostMessage: %s", key)
            return

        # Press modifiers
        for mod in mods:
            mod_vk = self._mod_vk_map.get(mod.lower())
            if mod_vk:
                self._post_key(hwnd, mod_vk, down=True, up=False)
                time.sleep(0.01)

        # Key down/up
        self._post_key(hwnd, vk)
        time.sleep(0.01)

        # Release modifiers in reverse
        for mod in reversed(mods):
            mod_vk = self._mod_vk_map.get(mod.lower())
            if mod_vk:
                self._post_key(hwnd, mod_vk, down=False, up=True)

    def focus_window(self) -> bool:
        """Bring target window to foreground.

        Returns:
            True if successful
        """
        if self.target_hwnd is None:
            logger.error("No target window set")
            return False

        try:
            # Check if window is minimized
            style = user32.GetWindowLongW(self.target_hwnd, GWL_STYLE)
            if style & WS_MINIMIZE:
                user32.ShowWindow(self.target_hwnd, SW_RESTORE)

            # Get thread IDs for input attachment
            current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
            target_thread_id = user32.GetWindowThreadProcessId(self.target_hwnd, None)

            # Attach input threads to allow SetForegroundWindow
            attached = False
            if current_thread_id != target_thread_id:
                attached = user32.AttachThreadInput(current_thread_id, target_thread_id, True)

            try:
                # Only use ALT hack if target is not already the foreground window
                foreground_before = user32.GetForegroundWindow()
                if foreground_before != self.target_hwnd:
                    # Send ALT key to release foreground lock (Windows workaround)
                    user32.keybd_event(0x12, 0, 0, 0)  # ALT down
                    user32.keybd_event(0x12, 0, 2, 0)  # ALT up

                # Bring window to foreground
                user32.BringWindowToTop(self.target_hwnd)
                user32.SetForegroundWindow(self.target_hwnd)

                # Also try SetActiveWindow and SetFocus
                user32.SetActiveWindow(self.target_hwnd)

            finally:
                # Detach input threads
                if attached:
                    user32.AttachThreadInput(current_thread_id, target_thread_id, False)

            time.sleep(0.15)  # Wait for window to focus

            # Verify focus was set
            foreground = user32.GetForegroundWindow()
            if foreground != self.target_hwnd:
                logger.warning("Focus may not have been set correctly. Expected %s, got %s", self.target_hwnd, foreground)

            # Try to focus child window if present
            if self.target_child_hwnd:
                user32.SetFocus(self.target_child_hwnd)

            return True

        except Exception as e:
            logger.error("Failed to focus window: %s", e)
            return False

    def get_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get target window position and size.

        Returns:
            Tuple of (x, y, width, height) or None
        """
        if self.target_hwnd is None:
            return None

        rect = wintypes.RECT()
        # Use DWM extended frame bounds to exclude invisible borders/shadow
        hr = dwmapi.DwmGetWindowAttribute(
            self.target_hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr != 0:
            # Fallback to GetWindowRect if DWM call fails
            if not user32.GetWindowRect(self.target_hwnd, ctypes.byref(rect)):
                return None

        x = rect.left
        y = rect.top
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        return (x, y, width, height)

    def _capture_printwindow(self) -> Image.Image | None:
        """Capture window using PrintWindow API.

        Captures the window content directly, even if occluded by other windows.
        May return a black image for some applications that use hardware-accelerated
        rendering (e.g. DirectX, OpenGL, some Electron apps).
        """
        import ctypes.wintypes
        from ctypes import windll

        rect = wintypes.RECT()
        if not user32.GetClientRect(self.target_hwnd, ctypes.byref(rect)):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None

        gdi32 = windll.gdi32
        hdc_window = user32.GetDC(self.target_hwnd)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
        hbm = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
        old_bm = gdi32.SelectObject(hdc_mem, hbm)

        # PW_RENDERFULLCONTENT = 2 (captures DX content on Win 8.1+)
        windll.user32.PrintWindow(self.target_hwnd, hdc_mem, 2)

        # Read bitmap bits
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height  # top-down
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbm, 0, height, buf, ctypes.byref(bmi), 0)

        # Cleanup
        gdi32.SelectObject(hdc_mem, old_bm)
        gdi32.DeleteObject(hbm)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(self.target_hwnd, hdc_window)

        return Image.frombuffer(
            "RGBX", (width, height), buf,  # type: ignore[arg-type]
            "raw", "BGRX", 0, 1
        ).convert("RGB")

    def capture_window(
        self, region: dict | None = None, background: bool = False
    ) -> Image.Image | None:
        """Capture screenshot of target window.

        Args:
            region: Optional dict with x, y, width, height (relative to window)
            background: If True, use PrintWindow API to capture even when occluded.
                        May produce black images for hardware-accelerated apps.
                        If False (default), bring window to foreground first.

        Returns:
            PIL Image or None
        """
        if self.target_hwnd is None:
            logger.error("No target window set")
            return None

        if background:
            image = self._capture_printwindow()
            if image is None:
                logger.error("PrintWindow capture failed")
                return None
            if region:
                x = region.get("x", 0)
                y = region.get("y", 0)
                w = region.get("width", image.width - x)
                h = region.get("height", image.height - y)
                image = image.crop((x, y, x + w, y + h))
            return image

        # Default: bring window to foreground, then screen-capture
        self.focus_window()

        window_rect = self.get_window_rect()
        if window_rect is None:
            logger.error("Could not get window rect")
            return None

        wx, wy, ww, wh = window_rect

        with mss.mss() as sct:
            if region:
                monitor = {
                    "left": wx + region.get("x", 0),
                    "top": wy + region.get("y", 0),
                    "width": region.get("width", ww),
                    "height": region.get("height", wh),
                }
            else:
                monitor = {
                    "left": wx,
                    "top": wy,
                    "width": ww,
                    "height": wh,
                }

            screenshot = sct.grab(monitor)
            return Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

    def _is_valid_tag(self, tag: str) -> bool:
        """Check if a tag string represents a valid special key (with optional modifiers).

        Args:
            tag: Tag content, e.g. 'enter', 'ctrl+c', 'shift+tab'

        Returns:
            True if tag is a recognized key combination
        """
        parts = tag.lower().split('+')
        key_part = None
        for part in parts:
            if part in self.modifier_keys:
                continue
            elif key_part is None:
                key_part = part
            else:
                # Multiple non-modifier parts → not a valid tag
                return False
        if key_part is None:
            # Modifier-only tag (e.g. {alt}, {ctrl}, {shift}, {win})
            # Valid only if exactly one modifier
            return len(parts) == 1 and parts[0] in self.special_keys
        # Accept known special keys and single characters (for combos like ctrl+a)
        return key_part in self.special_keys or len(key_part) == 1

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into plain characters and tag tokens.

        Tags are delimited by { and }, e.g. {enter}, {ctrl+c}.
        Only recognized special key names are treated as tags;
        unknown {content} is passed through as literal braces + content.
        Use {{ and }} to force literal braces when they collide with a tag name.
        Tag tokens are returned prefixed with \\x01.

        Args:
            text: Input text possibly containing {tag} sequences

        Returns:
            List of tokens: plain chars or '\\x01tagname' for tags
        """
        tokens: list[str] = []
        i = 0
        length = len(text)
        while i < length:
            ch = text[i]
            if ch == '{':
                # Check for escaped brace {{ -> literal {
                if i + 1 < length and text[i + 1] == '{':
                    tokens.append('{')
                    i += 2
                    continue
                # Find closing brace
                end = text.find('}', i + 1)
                if end == -1:
                    # No closing brace, treat as literal
                    tokens.append(ch)
                    i += 1
                else:
                    tag = text[i + 1:end].strip()
                    if tag and self._is_valid_tag(tag):
                        tokens.append('\x01' + tag)
                        i = end + 1
                    else:
                        # Not a recognized tag – emit literal { and continue
                        tokens.append('{')
                        i += 1
            elif ch == '}':
                # Check for escaped brace }} -> literal }
                if i + 1 < length and text[i + 1] == '}':
                    tokens.append('}')
                    i += 2
                    continue
                tokens.append(ch)
                i += 1
            else:
                tokens.append(ch)
                i += 1
        return tokens

    def _send_tag(self, tag: str, no_focus: bool = False) -> None:
        """Send a tag token by delegating to send_special_key.

        Args:
            tag: Tag string like 'enter', 'ctrl+c', 'shift+a'
            no_focus: If True, use PostMessage instead of focus+pynput
        """
        parts = tag.lower().split('+')
        modifiers: list[str] = []
        key_part: str | None = None

        for part in parts:
            if part in self.modifier_keys:
                modifiers.append(part)
            else:
                key_part = part

        if key_part is None:
            if len(modifiers) == 1:
                # Modifier-only tag (e.g. {alt}, {win}) — send as key
                key_part = modifiers.pop()
            else:
                logger.error("No key found in tag: %s", tag)
                return

        # Use a shorter default delay for inline tags (100ms vs 600ms)
        self.send_special_key(key_part, modifiers, delay_ms=100, no_focus=no_focus)

    def _check_focus(self, chars_sent: int) -> None:
        """Raise FocusLostError if target window is no longer in the foreground."""
        fg = user32.GetForegroundWindow()
        if fg != self.target_hwnd:
            raise FocusLostError(chars_sent)

    def send_keys(
        self, text: str, raw: bool = False, no_focus: bool = False,
        check_focus: bool = False,
    ) -> None:
        """Send text input to target window.

        Supports inline tags: {enter}, {tab}, {ctrl+c}, {shift+a}, etc.
        Only recognized special key names inside braces are interpreted as tags;
        unrecognized {content} is sent as literal text (braces included).

        Escaping braces: Use {{ and }} to force literal braces when they
        collide with a recognized tag name.

        Raw mode (raw=True): Disables all {tag} interpretation.
        Line endings (LF, CRLF, CR) are sent as Enter key presses.
        All other printable characters and tabs are sent as-is.

        Args:
            text: Text to type, with optional {tag} sequences
            raw: If True, disable all tag interpretation. Newlines become Enter.
            no_focus: If True, use PostMessage (no focus steal). Works with
                      cmd.exe, Git Bash, PuTTY, etc. May not work with RDP
                      or browser-based apps.
            check_focus: If True, raise FocusLostError when the target window
                         loses foreground focus during input.
        """
        if no_focus:
            hwnd = self._get_message_target()
            if not hwnd:
                logger.error("No target window set")
                return

            if raw:
                segments = text.split('\n')
                for idx, segment in enumerate(segments):
                    if segment:
                        self._post_message_text(hwnd, segment)
                    if idx < len(segments) - 1:
                        self._post_message_special_key(hwnd, "enter")
                        time.sleep(0.1)
                return

            tokens = self._tokenize(text)
            for token in tokens:
                if token.startswith('\x01'):
                    self._send_tag(token[1:], no_focus=True)
                else:
                    self._post_message_text(hwnd, token)
            return

        if not self.focus_window():
            logger.warning("Could not focus window, attempting to type anyway")

        time.sleep(0.1)  # Brief pause after focus

        chars_sent = 0

        # Reject unsupported control characters before sending
        # Raw mode allows \t, \n, \r (tab and line endings handled explicitly)
        # Tag mode: all special keys via {tags}, no control characters allowed
        allowed_ctrl = r'\t\n\r' if raw else ''
        bad = re.search(rf'[^{allowed_ctrl}\x20-\x7e\x80-\uffff]', text)
        if bad:
            ch = bad.group()
            raise ValueError(
                f"unsupported control character U+{ord(ch):04X} "
                f"at position {bad.start()}"
            )

        if raw:
            # Handle all line ending conventions: CRLF, CR, LF
            segments = re.split(r'\r\n|\r|\n', text)
            for idx, segment in enumerate(segments):
                if check_focus:
                    self._check_focus(chars_sent)
                if segment:
                    self.keyboard.type(segment)
                    chars_sent += len(segment)
                    time.sleep(0.02)
                if idx < len(segments) - 1:
                    self.send_special_key("enter", [], delay_ms=100)
                    chars_sent += 1
            return

        tokens = self._tokenize(text)
        for token in tokens:
            if check_focus:
                self._check_focus(chars_sent)
            if token.startswith('\x01'):
                self._send_tag(token[1:])
                chars_sent += 1
            else:
                self.keyboard.type(token)
                chars_sent += len(token)
                time.sleep(0.02)  # Small delay between characters

    def send_special_key(
        self, key: str, modifiers: list[str] | None = None,
        delay_ms: int | None = None, no_focus: bool = False,
    ) -> None:
        """Send special key or key combination.

        Args:
            key: Special key name
            modifiers: List of modifier keys (ctrl, alt, shift)
            delay_ms: Optional delay after sending (milliseconds)
            no_focus: If True, use PostMessage (no focus steal)
        """
        if no_focus:
            hwnd = self._get_message_target()
            if not hwnd:
                logger.error("No target window set")
                return
            self._post_message_special_key(hwnd, key, modifiers)
            if delay_ms is None:
                delay_ms = 100
            time.sleep(delay_ms / 1000)
            return

        # If Ctrl+<letter>, prefer WM_KEYDOWN/UP path for reliability in GUI terminals.
        mods = modifiers or []
        mods_lower = [m.lower() for m in mods]
        if any(m in ("ctrl", "control") for m in mods_lower) and len(key) == 1 and key.isalpha():
            if not self.focus_window():
                logger.warning("Could not focus window, attempting to send key anyway")
            process_name = self._get_process_name(self.target_hwnd) if self.target_hwnd else None
            if process_name == "mstsc.exe":
                self._send_ctrl_key_keybd_event(key)
            else:
                self.send_ctrl_key_wm(key)
            if delay_ms is None:
                delay_ms = 600
            time.sleep(delay_ms / 1000)
            return

        # For RDP (mstsc.exe), handle Alt+<letter> via keybd_event.
        if any(m == "alt" for m in mods_lower) and len(key) == 1 and key.isalpha():
            process_name = self._get_process_name(self.target_hwnd) if self.target_hwnd else None
            if process_name == "mstsc.exe":
                if not self.focus_window():
                    logger.warning("Could not focus window, attempting to send key anyway")
                self._send_alt_key_keybd_event(key)
                if delay_ms is None:
                    delay_ms = 600
                time.sleep(delay_ms / 1000)
                return

        if not self.focus_window():
            logger.warning("Could not focus window, attempting to send key anyway")

        key_lower = key.lower()
        if key_lower in self.special_keys:
            target_key = self.special_keys[key_lower]
        elif len(key_lower) == 1:
            target_key = key_lower
        else:
            logger.error("Unknown special key: %s", key)
            return

        # Press modifiers
        pressed_mods = []
        for mod in mods:
            mod_lower = mod.lower()
            if mod_lower in self.modifier_keys:
                self.keyboard.press(self.modifier_keys[mod_lower])
                pressed_mods.append(self.modifier_keys[mod_lower])

        # Press and release the key
        time.sleep(0.02)
        self.keyboard.press(target_key)
        self.keyboard.release(target_key)
        time.sleep(0.02)

        # Release modifiers in reverse order
        for mod_key in reversed(pressed_mods):
            self.keyboard.release(mod_key)

        if delay_ms is None:
            delay_ms = 600
        time.sleep(delay_ms / 1000)

    def send_key_sequence(
        self, steps: list[dict], check_focus: bool = False,
    ) -> None:
        """Send a sequence of key steps with optional per-step delays.

        Args:
            steps: List of dicts with key, optional modifiers, optional delay_ms
            check_focus: If True, raise FocusLostError when focus is lost
        """
        sent = 0
        for step in steps:
            key = step.get("key")
            if not key:
                continue
            if check_focus:
                self._check_focus(sent)
            modifiers = step.get("modifiers")
            delay_ms = step.get("delay_ms")
            self.send_special_key(key, modifiers, delay_ms)
            sent += 1

    def click(
        self,
        x: int,
        y: int,
        button: Literal["left", "right", "middle"] = "left",
    ) -> None:
        """Click at position relative to target window.

        Args:
            x: X coordinate relative to window
            y: Y coordinate relative to window
            button: Mouse button
        """
        window_rect = self.get_window_rect()
        if window_rect is None:
            logger.error("Could not get window rect")
            return

        wx, wy, _, _ = window_rect

        # Convert to absolute coordinates
        abs_x = wx + x
        abs_y = wy + y

        # Move mouse and click
        self.mouse.position = (abs_x, abs_y)
        time.sleep(0.05)

        button_map = {
            "left": Button.left,
            "right": Button.right,
            "middle": Button.middle,
        }

        self.mouse.click(button_map.get(button, Button.left))

    def mouse_move(
        self,
        x: int,
        y: int,
        relative: bool = False,
    ) -> None:
        """Move mouse cursor relative to target window or by offset.

        Args:
            x: X coordinate relative to window, or X offset if relative=True
            y: Y coordinate relative to window, or Y offset if relative=True
            relative: If True, move by offset from current position
        """
        if relative:
            cur_x, cur_y = self.mouse.position
            self.mouse.position = (cur_x + x, cur_y + y)
        else:
            window_rect = self.get_window_rect()
            if window_rect is None:
                logger.error("Could not get window rect")
                return
            wx, wy, _, _ = window_rect
            self.mouse.position = (wx + x, wy + y)
        time.sleep(0.05)

    def mouse_drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        button: Literal["left", "right", "middle"] = "left",
    ) -> None:
        """Drag from start to end position relative to target window.

        Args:
            start_x: Start X coordinate relative to window
            start_y: Start Y coordinate relative to window
            end_x: End X coordinate relative to window
            end_y: End Y coordinate relative to window
            button: Mouse button
        """
        window_rect = self.get_window_rect()
        if window_rect is None:
            logger.error("Could not get window rect")
            return

        wx, wy, _, _ = window_rect
        btn = {"left": Button.left, "right": Button.right, "middle": Button.middle}.get(button, Button.left)

        self.mouse.position = (wx + start_x, wy + start_y)
        time.sleep(0.05)
        self.mouse.press(btn)
        time.sleep(0.05)
        self.mouse.position = (wx + end_x, wy + end_y)
        time.sleep(0.05)
        self.mouse.release(btn)

    def mouse_scroll(self, amount: int) -> None:
        """Scroll mouse wheel.

        Args:
            amount: Scroll amount (positive=up, negative=down)
        """
        self.mouse.scroll(0, amount)
