# Visual Window Control

MCP server & CLI for controlling windows visually — capture screenshots, extract text via OCR (Tesseract), and send keyboard/mouse input to any target window. Designed for remote desktop workflows (RDP, etc.) but works with any window.

## Requirements

- Windows 10/11
- Python 3.10+
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)

## Installation

```bash
# Install Tesseract OCR (via Chocolatey or manual download)
choco install tesseract

# Install the package
pip install -e .
```

## Usage

### CLI (`vwctl`)

```bash
# List all visible windows
vwctl list-windows

# Capture and OCR a window (by title)
vwctl -w "Remote Desktop" ocr

# Type text with inline tags
vwctl -w "Remote Desktop" type "ls -la{enter}"

# Type from stdin (pipe or streaming)
echo "ls -la{enter}" | vwctl -w "Remote Desktop" type

# Send a special key with modifiers
vwctl -w "Remote Desktop" key c -m ctrl

# Send a key sequence with per-step timing control
vwctl -w "Remote Desktop" keys '[{"key":"tab"},{"key":"enter","delay_ms":500}]'

# Click at coordinates relative to window
vwctl -w "Remote Desktop" click 400 300

# Execute a command and read output via OCR
vwctl -w "Remote Desktop" exec "ls -la" -W 2.0

# Capture screenshot to file (default: JPEG quality 85)
vwctl -w "Remote Desktop" capture
# → Saved: 2026-03-07_22-24-00_vwctl.jpg (1920x1080)

# Capture with custom filename (use .png extension for PNG output)
vwctl -w "Remote Desktop" capture -o screen.png

# Capture occluded window without bringing to foreground
# (uses PrintWindow API; may produce black images for hardware-accelerated apps)
vwctl -w "Remote Desktop" capture -b

# Use hwnd instead of title (faster, no search overhead)
vwctl -H 1234567 ocr

# Send input without stealing focus (works with cmd.exe, Git Bash, PuTTY, etc.)
vwctl -w "Command Prompt" -n type "dir{enter}"
```

#### Subcommands

| Command | Description |
|---------|-------------|
| `list-windows` | List all visible windows with hwnd and title |
| `type [TEXT]` | Type text with inline `{tag}` support (reads from stdin if omitted) |
| `key KEY [-m MOD]` | Send a single key press with optional modifiers |
| `keys JSON` | Send a key sequence from JSON array (per-step modifiers and delays) |
| `click X Y [-b]` | Click at position relative to window |
| `move X Y [-r]` | Move mouse cursor (absolute or relative) |
| `drag X1 Y1 X2 Y2` | Drag mouse from start to end position |
| `scroll AMOUNT` | Scroll mouse wheel (+up, -down) |
| `capture [-o FILE] [-b]` | Capture window to JPEG file or base64 stdout (`.png` extension for PNG) |
| `ocr [-b]` | Capture window and extract text via OCR |
| `exec CMD [-W SEC]` | Type command, Enter, wait, then OCR output |

#### Global Options

| Option | Description |
|--------|-------------|
| `-w, --window TITLE` | Target window by title (partial match) |
| `-H, --hwnd HWND` | Target window by handle directly |
| `-c, --config FILE` | Config file path |
| `-n, --no-focus` | Send input via PostMessage without stealing focus |

## Configuration

Settings can be provided via config file, environment variables, or CLI arguments. Priority: **CLI args > env vars > config file**.

### Config File

TOML format. Search order (first found wins):

1. `--config FILE` / `VWCTL_CONFIG` env var
2. `./vwctl.toml` (current directory)
3. `~/.config/vwctl/config.toml` (Linux) / `%APPDATA%\vwctl\config.toml` (Windows)

Example `vwctl.toml`:

```toml
window = "Remote Desktop"
ocr_cmd = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
capture_log_dir = "./captures"
no_focus = false
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `VWCTL_WINDOW` | Default target window title |
| `VWCTL_HWND` | Default target window handle |
| `VWCTL_OCR_CMD` | Tesseract executable path |
| `VWCTL_CAPTURE_LOG_DIR` | Default directory for capture output |
| `VWCTL_NO_FOCUS` | Send input via PostMessage without stealing focus (`1`/`true`) |
| `VWCTL_CONFIG` | Config file path |

### MCP Server

Add to your MCP client configuration (e.g. `.claude.json`):

```json
{
  "mcpServers": {
    "visual-window-control": {
      "type": "stdio",
      "command": "mcp-visual-window-control"
    }
  }
}
```

The MCP server exposes the same functionality as the CLI as tools: `list_windows`, `set_target_window`, `get_screen_text`, `get_screen_image`, `send_keys`, `send_special_key`, `send_key_sequence`, `click`, `mouse_move`, `mouse_drag`, `mouse_scroll`, `execute_and_read`, `list_child_windows`, `get_focus_info`.

`send_keys` and `send_key_sequence` automatically detect focus loss: if the target window loses foreground focus during input, the operation is aborted and the tool returns an `"Aborted: target window lost focus (sent X/Y ...)"` message instead of the normal result.

## Inline Tags (`send_keys` / `type`)

Text input supports `{tag}` syntax for special keys:

```
"ls -la{enter}"                     → types "ls -la" then presses Enter
"awk '{print $1}' file.txt{enter}"  → braces pass through (not a known tag)
"echo {{enter}}"                    → types "echo {enter}" (escaped)
"{ctrl+c}"                          → sends Ctrl+C
```

**Whitelist-based**: Only recognized key names are interpreted as tags. Unknown `{content}` passes through literally, so code with curly braces (awk, Python, shell) works without escaping.

**Supported keys**: `{enter}`, `{tab}`, `{escape}`, `{backspace}`, `{delete}`, `{up}`, `{down}`, `{left}`, `{right}`, `{home}`, `{end}`, `{pageup}`, `{pagedown}`, `{space}`, `{f1}`–`{f12}`

**Modifiers**: `{ctrl+c}`, `{alt+f4}`, `{shift+tab}`

**Escaping**: `{{` → literal `{`, `}}` → literal `}`

### Raw Mode

Disable all tag interpretation. Newline characters (`\n`) are sent as Enter key presses.

```bash
# CLI
vwctl -w "Remote Desktop" type -r "echo hello
echo world
"

# MCP: {"text": "echo hello\necho world\n", "raw": true}
```

### Stdin Input

When the text argument is omitted, `type` reads from stdin line by line. This enables piping and streaming:

```bash
# Pipe from another command
echo "ls -la{enter}" | vwctl -w "Remote Desktop" type

# Pipe file contents
cat commands.txt | vwctl -w "Remote Desktop" type -r

# Streaming (line-by-line as data arrives)
tail -f commands.fifo | vwctl -w "Remote Desktop" type -r
```

Providing both a text argument and stdin is an error.

### Focus Loss Detection

The `type` and `keys` commands (and MCP `send_keys` / `send_key_sequence` tools) monitor whether the target window remains in the foreground during input. If another window takes focus, input is immediately aborted:

```
# type command
Aborted: target window lost focus (typed 42 characters)

# keys command
Aborted: target window lost focus (sent 2/5 key steps)
```

This prevents keystrokes from being sent to an unintended window. Focus checking is disabled in no-focus mode (`-n` for CLI, `no_focus: true` for MCP).

## Limitations

- **Focus stealing**: When sending input to the target window, focus is moved to that window by default. This is required for the input to be received by the target application.
- **No-focus mode (`-n` / `--no-focus`)**: An option exists to send input via `PostMessage` without stealing focus, but this only works with certain native Windows applications (e.g. `cmd.exe`, Git Bash, PuTTY). **Remote desktop applications (RDP, Guacamole, VNC, etc.) do not support no-focus input** — they require the window to be focused and in the foreground to receive keyboard/mouse events.
- **Admin privileges**: When the target application runs as admin, the controlling process must also run as admin due to Windows UIPI restrictions.

## OCR Tips

- Use monospace fonts (JetBrains Mono, Hack, Fira Code) at 24pt+
- Use high-contrast terminal themes
- Larger window sizes improve accuracy

## For LLM Agents

See [LLM.md](LLM.md) for a CLI reference designed for LLM agents — recommended workflow, command examples, and common patterns.

## Tested With

- Windows 11, Python 3.12+, Tesseract 5.x
- Remote Desktop (mstsc.exe)
