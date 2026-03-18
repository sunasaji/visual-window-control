"""MCP server for visual window control."""

import asyncio
import base64
import io
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import ImageContent, TextContent, Tool

from .ocr import TerminalOCR
from .window_control import FocusLostError, WindowController

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
ocr: TerminalOCR | None = None
controller: WindowController | None = None


def get_ocr() -> TerminalOCR:
    global ocr
    if ocr is None:
        ocr = TerminalOCR()
    return ocr


def get_controller() -> WindowController:
    global controller
    if controller is None:
        controller = WindowController()
    return controller


# Create MCP server
app = Server("mcp-visual-window-control")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="list_windows",
            description="List all visible windows with their titles. Use this to find the target window.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="set_target_window",
            description="Set the target window by title (partial match supported). All subsequent operations will target this window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Window title to search for (partial match)",
                    },
                },
                "required": ["title"],
            },
        ),
        Tool(
            name="get_screen_text",
            description="Capture the target window and extract text using OCR. Returns the text content of the terminal.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": "Optional region to capture (relative to window). If not specified, captures entire window.",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                    },
                    "background": {
                        "type": "boolean",
                        "description": "If true, capture using PrintWindow API (works even when occluded, but may produce black images for hardware-accelerated apps). Default: false (brings window to foreground).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="get_screen_image",
            description="Capture the target window and return as image. Use sparingly as images consume many tokens. Prefer get_screen_text for terminal content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "object",
                        "description": "Optional region to capture (relative to window)",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                    },
                    "background": {
                        "type": "boolean",
                        "description": "If true, capture using PrintWindow API (works even when occluded, but may produce black images for hardware-accelerated apps). Default: false (brings window to foreground).",
                    },
                    "quality": {
                        "type": "integer",
                        "description": "JPEG quality 1-95. Default: 85.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="send_keys",
            description=(
                'Send text input to the target window. Supports inline tags: {enter}, {tab}, {ctrl+c}, {shift+a}, etc.\n'
                '\n'
                '**Whitelist-based tag parsing:** Only recognized special key names inside {braces} are interpreted as tags. '
                'Unknown {content} (e.g. {print $1}) is passed through as literal text including the braces. '
                'This means code with curly braces (awk, Python, shell) can be sent without escaping in most cases.\n'
                '\n'
                '**Escaping:** Use {{ and }} to force literal braces when they collide with a recognized tag name '
                '(e.g. {{enter}} to type the literal text "{enter}").\n'
                '\n'
                '**Raw mode (raw=true):** Disables ALL tag interpretation. '
                'Newline characters (JSON \\n) are sent as Enter key presses. '
                'Use JSON \\\\n to type a literal backslash + n.\n'
                '\n'
                'Examples:\n'
                '  "ls -la{enter}"                     → types "ls -la" then presses Enter\n'
                '  "awk \'{print $1}\' file.txt{enter}"  → types "awk \'{print $1}\' file.txt" then Enter (braces preserved)\n'
                '  "echo {{enter}}"                    → types "echo {enter}" (escaped to avoid tag)\n'
                '  raw=true: "ls -la\\necho hi\\n"       → types "ls -la", Enter, "echo hi", Enter'
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to type. Supports inline {tag} for special keys: {enter}, {tab}, {escape}, {backspace}, {delete}, {up}, {down}, {left}, {right}, {home}, {end}, {pageup}, {pagedown}, {space}, {f1}-{f12}. Modifiers: {ctrl+c}, {alt+f4}, {shift+tab}. Only recognized key names are treated as tags; other braces pass through literally.",
                    },
                    "raw": {
                        "type": "boolean",
                        "description": "If true, disable all {tag} interpretation. Newline chars (\\n) become Enter key presses. Default: false.",
                    },
                    "no_focus": {
                        "type": "boolean",
                        "description": "If true, send input via PostMessage without stealing focus. Works with cmd.exe, Git Bash, PuTTY, etc. May not work with RDP or browser-based apps. Default: false.",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="send_special_key",
            description="Send a special key or key combination to the target window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Special key name: enter, tab, escape, backspace, delete, up, down, left, right, home, end, pageup, pagedown, f1-f12",
                    },
                    "modifiers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Modifier keys: ctrl, alt, shift",
                    },
                    "delay_ms": {
                        "type": "integer",
                        "description": "Optional delay after sending (milliseconds). Default: 600ms",
                    },
                    "no_focus": {
                        "type": "boolean",
                        "description": "If true, send via PostMessage without stealing focus. Default: false.",
                    },
                },
                "required": ["key"],
            },
        ),
        Tool(
            name="send_key_sequence",
            description="Send a sequence of key steps with optional per-step delays.",
            inputSchema={
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {"type": "string"},
                                "modifiers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "delay_ms": {
                                    "type": "integer",
                                    "description": "Delay after this key step (ms). Default: 600ms (focus) / 100ms (no-focus)",
                                },
                            },
                            "required": ["key"],
                        },
                    },
                },
                "required": ["steps"],
            },
        ),
        Tool(
            name="list_child_windows",
            description="List visible child windows for the current target.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_focus_info",
            description="Get foreground/focus info for debugging input targeting.",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="click",
            description="Click at a position in the target window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate relative to window",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate relative to window",
                    },
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button (default: left)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="mouse_move",
            description="Move mouse cursor to a position in the target window or by offset.",
            inputSchema={
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate relative to window, or X offset if relative=true",
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate relative to window, or Y offset if relative=true",
                    },
                    "relative": {
                        "type": "boolean",
                        "description": "If true, move by offset from current position (default: false)",
                    },
                },
                "required": ["x", "y"],
            },
        ),
        Tool(
            name="mouse_drag",
            description="Drag mouse from start to end position in the target window.",
            inputSchema={
                "type": "object",
                "properties": {
                    "start_x": {"type": "integer", "description": "Start X relative to window"},
                    "start_y": {"type": "integer", "description": "Start Y relative to window"},
                    "end_x": {"type": "integer", "description": "End X relative to window"},
                    "end_y": {"type": "integer", "description": "End Y relative to window"},
                    "button": {
                        "type": "string",
                        "enum": ["left", "right", "middle"],
                        "description": "Mouse button (default: left)",
                    },
                },
                "required": ["start_x", "start_y", "end_x", "end_y"],
            },
        ),
        Tool(
            name="mouse_scroll",
            description="Scroll mouse wheel at the current cursor position.",
            inputSchema={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "Scroll amount (positive=up, negative=down)",
                    },
                },
                "required": ["amount"],
            },
        ),
        Tool(
            name="execute_and_read",
            description="Send a command, press Enter, wait for output, and return the OCR result. Convenient for running shell commands.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute",
                    },
                    "wait_seconds": {
                        "type": "number",
                        "description": "Seconds to wait for output (default: 1.0)",
                    },
                },
                "required": ["command"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent | ImageContent]:
    """Handle tool calls."""
    ctrl = get_controller()
    ocr_engine = get_ocr()

    try:
        if name == "list_windows":
            windows = ctrl.list_windows()
            return [TextContent(
                type="text",
                text=json.dumps(windows, indent=2, ensure_ascii=False),
            )]

        elif name == "set_target_window":
            title = arguments["title"]
            result = ctrl.set_target_window(title)
            return [TextContent(
                type="text",
                text=result,
            )]

        elif name == "get_screen_text":
            region = arguments.get("region")
            background = arguments.get("background", False)
            image = ctrl.capture_window(region, background=background)
            if image is None:
                return [TextContent(type="text", text="Error: Could not capture window. Is target window set?")]

            text = ocr_engine.extract_text(image)
            return [TextContent(type="text", text=text)]

        elif name == "get_screen_image":
            region = arguments.get("region")
            background = arguments.get("background", False)
            quality = arguments.get("quality", 85)
            image = ctrl.capture_window(region, background=background)
            if image is None:
                return [TextContent(type="text", text="Error: Could not capture window. Is target window set?")]

            # Convert to base64 JPEG
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality)
            b64_image = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

            return [ImageContent(
                type="image",
                data=b64_image,
                mimeType="image/jpeg",
            )]

        elif name == "send_keys":
            text = arguments["text"]
            raw = arguments.get("raw", False)
            no_focus = arguments.get("no_focus", False)
            try:
                ctrl.send_keys(text, raw=raw, no_focus=no_focus,
                               check_focus=not no_focus)
            except FocusLostError as e:
                return [TextContent(
                    type="text",
                    text=f"Aborted: target window lost focus "
                         f"(sent {e.chars_sent}/{len(text)} characters)")]
            return [TextContent(type="text", text=f"Sent: {text}")]

        elif name == "send_special_key":
            key = arguments["key"]
            modifiers = arguments.get("modifiers", [])
            delay_ms = arguments.get("delay_ms")
            no_focus = arguments.get("no_focus", False)
            ctrl.send_special_key(key, modifiers, delay_ms, no_focus=no_focus)
            modifier_str = "+".join(modifiers) + "+" if modifiers else ""
            return [TextContent(type="text", text=f"Sent: {modifier_str}{key}")]

        elif name == "send_key_sequence":
            steps = arguments["steps"]
            try:
                ctrl.send_key_sequence(steps, check_focus=True)
            except FocusLostError as e:
                return [TextContent(
                    type="text",
                    text=f"Aborted: target window lost focus "
                         f"(sent {e.chars_sent}/{len(steps)} key steps)")]
            return [TextContent(type="text", text="Sent key sequence")]

        elif name == "list_child_windows":
            children = ctrl.list_child_windows()
            return [TextContent(type="text", text=json.dumps(children, indent=2, ensure_ascii=False))]

        elif name == "get_focus_info":
            info = ctrl.get_focus_info()
            return [TextContent(type="text", text=json.dumps(info, indent=2, ensure_ascii=False))]

        elif name == "click":
            x = arguments["x"]
            y = arguments["y"]
            button = arguments.get("button", "left")
            ctrl.click(x, y, button)
            return [TextContent(type="text", text=f"Clicked {button} at ({x}, {y})")]

        elif name == "mouse_move":
            x = arguments["x"]
            y = arguments["y"]
            relative = arguments.get("relative", False)
            ctrl.mouse_move(x, y, relative)
            if relative:
                return [TextContent(type="text", text=f"Moved mouse by ({x}, {y})")]
            return [TextContent(type="text", text=f"Moved mouse to ({x}, {y})")]

        elif name == "mouse_drag":
            start_x = arguments["start_x"]
            start_y = arguments["start_y"]
            end_x = arguments["end_x"]
            end_y = arguments["end_y"]
            button = arguments.get("button", "left")
            ctrl.mouse_drag(start_x, start_y, end_x, end_y, button)
            return [TextContent(type="text", text=f"Dragged {button} from ({start_x}, {start_y}) to ({end_x}, {end_y})")]

        elif name == "mouse_scroll":
            amount = arguments["amount"]
            ctrl.mouse_scroll(amount)
            direction = "up" if amount > 0 else "down"
            return [TextContent(type="text", text=f"Scrolled {direction} by {abs(amount)}")]

        elif name == "execute_and_read":
            command = arguments["command"]
            wait_seconds = arguments.get("wait_seconds", 1.0)

            # Click in the center of the window to ensure focus
            window_rect = ctrl.get_window_rect()
            if window_rect:
                _, _, width, height = window_rect
                center_x = width // 2
                center_y = height // 2
                ctrl.click(center_x, center_y, "left")
                await asyncio.sleep(0.1)

            # Send command (raw mode: no tag interpretation)
            ctrl.send_keys(command, raw=True)
            await asyncio.sleep(0.1)

            # Press Enter
            ctrl.send_special_key("enter", [])

            # Wait for output
            await asyncio.sleep(wait_seconds)

            # Capture and OCR
            image = ctrl.capture_window()
            if image is None:
                return [TextContent(type="text", text="Error: Could not capture window")]

            text = ocr_engine.extract_text(image)
            return [TextContent(type="text", text=text)]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.exception("Error in tool %s", name)
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def run():
    """Run the MCP server."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    """Entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
