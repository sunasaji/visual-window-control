# Visual Window Control

[![PyPI](https://img.shields.io/pypi/v/visual-window-control)](https://pypi.org/project/visual-window-control/)

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

## For LLM Agents

See [LLM.md](LLM.md) for a CLI reference designed for LLM agents — recommended workflow, command examples, and common patterns.

## Usage

### CLI (`vwctl`)

```bash
# List all visible windows
vwctl list

# Capture and OCR a window (by title)
vwctl -w "Remote Desktop" ocr

# Type text with inline tags
vwctl -w "Remote Desktop" type "ls -la{enter}"

# Type from stdin (pipe or streaming, raw mode by default)
printf "ls -la\n" | vwctl -w "Remote Desktop" type

# Send a special key with modifiers
vwctl -w "Remote Desktop" key c -m ctrl

# Send a key with custom delay (wait 800ms after key press)
vwctl -w "Remote Desktop" key f -m alt -d 800

# Send a key sequence with per-step timing control (delay_ms in ms)
vwctl -w "Remote Desktop" keys '[{"key":"tab"},{"key":"enter","delay_ms":500}]'

# Click at coordinates relative to window
vwctl -w "Remote Desktop" click 400 300

# Execute a command and read output via OCR
vwctl -w "Remote Desktop" exec "ls -la" -W 2.0

# Capture screenshot to file (default: JPEG quality 85)
vwctl -w "Remote Desktop" capture
# → Saved: 2026-03-07_22-24-00_vwctl.jpg (1920x1080)

# Capture with custom JPEG quality 1-95 (default: 85)
vwctl -w "Remote Desktop" capture -q 60

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
| `list` | List all visible windows with hwnd and title |
| `type [TEXT] [-f FILE]` | Type text with inline `{tag}` support (reads from stdin if omitted; `-f` to read from file, `-f -` for explicit stdin) |
| `key KEY [-m MOD] [-d MS]` | Send a single key press with optional modifiers and delay |
| `keys JSON` | Send a key sequence from JSON array (per-step `key`, `modifiers`, `delay_ms`) |
| `click X Y [-b]` | Click at position relative to window |
| `move X Y [-r]` | Move mouse cursor (absolute or relative) |
| `drag X1 Y1 X2 Y2` | Drag mouse from start to end position |
| `scroll AMOUNT` | Scroll mouse wheel (+up, -down) |
| `capture [-o FILE] [-q Q] [-b]` | Capture window to JPEG file or base64 stdout (`.png` extension for PNG) |
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
jpeg_quality = 85
no_focus = false
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `VWCTL_WINDOW` | Default target window title |
| `VWCTL_HWND` | Default target window handle |
| `VWCTL_OCR_CMD` | Tesseract executable path |
| `VWCTL_CAPTURE_LOG_DIR` | Default directory for capture output |
| `VWCTL_JPEG_QUALITY` | JPEG quality 1-95 (default: 85) |
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

**Supported keys**: `{enter}`, `{tab}`, `{escape}`, `{backspace}`, `{delete}`, `{space}`, `{up}`, `{down}`, `{left}`, `{right}`, `{home}`, `{end}`, `{pageup}`, `{pagedown}`, `{insert}`, `{f1}`–`{f24}`, `{print_screen}`, `{pause}`, `{menu}`, `{caps_lock}`, `{num_lock}`, `{scroll_lock}`, `{media_play_pause}`, `{media_stop}`, `{media_volume_mute}`, `{media_volume_down}`, `{media_volume_up}`, `{media_previous}`, `{media_next}`

**Modifiers** (also usable standalone): `{ctrl}`, `{alt}`, `{shift}`, `{win}` — with left/right variants: `{ctrl_l}`, `{ctrl_r}`, `{alt_l}`, `{alt_r}`, `{alt_gr}`, `{shift_r}`, `{win_r}`

**Modifier combos**: `{ctrl+c}`, `{alt+f4}`, `{shift+tab}`, `{win+d}`

**Escaping**: `{{` → literal `{`, `}}` → literal `}`

### Supported Characters

Each mode accepts a specific set of characters. Text containing unsupported characters (e.g. escape sequences, null bytes) will be rejected with an error before any keystrokes are sent.

| Mode | Accepted characters | Special keys |
|------|-------------------|--------------|
| **Tag mode** (default for text arg) | Printable characters (U+0020–U+007E, U+0080+) | Via `{tag}` syntax: `{enter}`, `{tab}`, `{ctrl+c}`, etc. |
| **Raw mode** (`-r`, default for stdin/file) | Printable characters + `\t` (Tab) + line endings (`\n`, `\r\n`, `\r` → Enter) | None (modifier combos like Ctrl+C not available) |

**Choosing a mode**: Use raw mode (`-r`) for multi-line or long text input where modifier key combinations are not needed. Use tag mode for interactive sequences that require special keys or modifiers.

**Sending arbitrary data**: If your text contains control characters or escape sequences (e.g. ANSI codes), encode it as base64 and decode on the remote side:

```bash
# Encode locally, type via raw mode, decode on remote
base64 -w0 binary_file.dat | vwctl -H HWND type -f -
# Then on the remote side: echo "<pasted>" | base64 -d > file
# Or as a single pipeline command:
echo "echo '$(base64 -w0 binary_file.dat)' | base64 -d > /tmp/file{enter}" | vwctl -H HWND type -t
```

### Raw Mode

Disable all tag interpretation. Line endings (`\n`, `\r\n`, `\r`) are sent as Enter key presses, and tab characters (`\t`) are sent as Tab. For multi-line or long text input where modifier key combinations (e.g. `{ctrl+c}`) are not needed, raw mode (`-r`) is recommended.

```bash
# CLI
vwctl -w "Remote Desktop" type -r "echo hello
echo world
"

# MCP: {"text": "echo hello\necho world\n", "raw": true}
```

### Stdin and File Input

When the text argument is omitted, `type` reads from stdin line by line. Use `--file`/`-f` to read from a file, or `-f -` for explicit stdin.

Stdin and file input **default to raw mode** (no tag interpretation), since the typical use case is piping file/program output. Use `-t`/`--tags` to enable tag interpretation for these sources.

```bash
# Pipe from another command (raw by default — \n is sent as Enter)
printf "ls -la\n" | vwctl -w "Remote Desktop" type

# Explicit stdin with "-f -"
cat commands.txt | vwctl -w "Remote Desktop" type -f -

# Read from a file directly (raw by default)
vwctl -w "Remote Desktop" type -f commands.txt

# File input with tag interpretation
vwctl -w "Remote Desktop" type -f commands.txt -t

# Streaming (line-by-line as data arrives)
tail -f commands.fifo | vwctl -w "Remote Desktop" type
```

If both a text argument and stdin are present, the text argument wins (stdin is ignored).

`-r`/`--raw` and `-t`/`--tags` are mutually exclusive.

### Focus Loss Detection

The `type` and `keys` commands (and MCP `send_keys` / `send_key_sequence` tools) monitor whether the target window remains in the foreground during input. If another window takes focus, input is immediately aborted:

```
# type command
Aborted: target window lost focus (typed 42 characters)

# keys command
Aborted: target window lost focus (sent 2/5 key steps)
```

This prevents keystrokes from being sent to an unintended window. Focus checking is disabled in no-focus mode (`-n` for CLI, `no_focus: true` for MCP).

### Key Delay (`delay_ms`)

After each key press, `vwctl` waits for a configurable delay before proceeding to the next action. This gives the target application time to process the keystroke (especially important for remote desktop apps, menus, and GUI transitions).

**Default delays** (when `delay_ms` is not specified):

| Context | Default delay |
|---------|---------------|
| `key` / `keys` commands (focus mode) | 600 ms |
| `key` / `keys` commands (no-focus mode, `-n`) | 100 ms |
| Inline `{tag}` in `type` command | 100 ms |
| Plain text in `type` command | 20 ms (per character) |

**Overriding the delay**:

- **`keys` command** (CLI): set `delay_ms` per step in the JSON array.
  ```bash
  vwctl -H HWND keys '[{"key":"alt+f","delay_ms":800},{"key":"s","delay_ms":200}]'
  ```
- **`send_special_key` MCP tool**: set the `delay_ms` parameter directly.
- **`send_key_sequence` MCP tool**: set `delay_ms` per step in the `steps` array.

- **`key` command** (CLI): set `--delay`/`-d` in milliseconds.
  ```bash
  vwctl -H HWND key f -m alt -d 800
  ```

**When to adjust**: Increase the delay for slow UI transitions (e.g. menu opening, dialog loading). Decrease it for fast sequential keypresses where the default 600 ms is too slow.

## Limitations

- **Focus stealing**: When sending input to the target window, focus is moved to that window by default. This is required for the input to be received by the target application.
- **No-focus mode (`-n` / `--no-focus`)**: An option exists to send input via `PostMessage` without stealing focus, but key support varies by target application:

  | Target application | Text | Common keys | F1–F24 | Lock/system keys | Media keys |
  |---|---|---|---|---|---|
  | **Native console** (cmd.exe, Git Bash/mintty, PuTTY) | OK | OK | OK | Sent (toggle depends on OS) | Sent (no effect) |
  | **RDP/remote desktop** (mstsc, Windows Sandbox, VNC, Guacamole) | NG | NG | NG | NG | NG |

  Common keys: enter, tab, escape, backspace, delete, arrows, home/end, pageup/pagedown, space, insert.
  In focus mode, all keys work with all applications.
- **Admin privileges**: When the target application runs as admin, the controlling process must also run as admin due to Windows UIPI restrictions.

## OCR Tips

- Use monospace fonts (JetBrains Mono, Hack, Fira Code) at 24pt+
- Use high-contrast terminal themes
- Larger window sizes improve accuracy

## Tested With

- Windows 11, Python 3.12+, Tesseract 5.x
- Remote Desktop (mstsc.exe)
