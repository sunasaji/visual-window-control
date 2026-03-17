# LLM.md — vwctl CLI Reference for LLM Agents

`vwctl` controls windows remotely: capture screenshots, read text via OCR, and send keyboard/mouse input. Use this to operate any window on the host machine.

## Recommended Workflow

**Always start by identifying the target window and confirming with the user before proceeding.**

```bash
# 1. List windows (plain text: "hwnd  title" per line)
vwctl list-windows
# or JSON: vwctl list-windows --json
# → Ask the user: "Which window should I operate on?"

# 2. Once confirmed, note the hwnd and use -H for all subsequent commands
vwctl -H 4653916 ocr
vwctl -H 4653916 type "ls -la{enter}"
vwctl -H 4653916 exec "whoami" -W 2.0
```

**Why `-H HWND` over `-w TITLE`:**
- `-w` does substring matching and may match multiple windows (e.g. two Notepad windows), causing the command to fail
- hwnd is a unique, stable identifier for the lifetime of the window
- No search overhead — faster execution

Use `-w TITLE` only for quick one-off commands when you are certain the title is unique.

## Window Targeting

Every command except `list-windows` requires a target window.

| Option | Description |
|--------|-------------|
| `-H HWND` | Target by window handle (integer, unique and reliable) |
| `-w TITLE` | Match by title substring (case-insensitive, may fail on multiple matches) |

## Commands

In the examples below, `HWND` is the window handle obtained from `list-windows`.

### Read the screen

```bash
vwctl -H HWND ocr              # OCR the entire window
vwctl -H HWND ocr -b           # OCR without bringing window to foreground
vwctl -H HWND capture          # Save screenshot to timestamped JPEG
vwctl -H HWND capture -q 60    # JPEG quality 1-95 (default: 85)
vwctl -H HWND capture -o F.png # Save as PNG
vwctl -H HWND capture -b       # Background capture (no foreground switch)
```

### Send keyboard input

```bash
# Type text with inline special keys (tag mode, default for text arg)
vwctl -H HWND type "ls -la{enter}"
vwctl -H HWND type "cd /tmp{enter}"
vwctl -H HWND type "{ctrl+c}"

# Raw mode: no tag parsing, \n becomes Enter, \t becomes Tab
# Recommended for multi-line/long text where modifier keys ({ctrl+c} etc.) are not needed
vwctl -H HWND type -r "line1
line2
"

# Read from file (raw by default; use -t for tag interpretation)
vwctl -H HWND type -f commands.txt
vwctl -H HWND type -f commands.txt -t

# Read from stdin (raw by default; use -t for tag interpretation)
cat commands.txt | vwctl -H HWND type
cat commands.txt | vwctl -H HWND type -f -

# Send a single key with modifiers
vwctl -H HWND key enter
vwctl -H HWND key c -m ctrl
vwctl -H HWND key a -m ctrl -m shift

# Send a key sequence (JSON array)
vwctl -H HWND keys '[{"key":"tab"},{"key":"enter","delay_ms":500}]'
```

**Inline tags** (used in `type` command, tag mode):
- Keys: `{enter}`, `{tab}`, `{escape}`, `{backspace}`, `{delete}`, `{up}`, `{down}`, `{left}`, `{right}`, `{home}`, `{end}`, `{pageup}`, `{pagedown}`, `{space}`, `{f1}`–`{f12}`
- Modifiers: `{ctrl+c}`, `{alt+f4}`, `{shift+tab}`, `{ctrl+shift+a}`
- Escaping: `{{` → literal `{`, `}}` → literal `}`
- Unrecognized `{content}` passes through as-is (safe for code with braces)

**Supported characters** — text containing unsupported characters is rejected before any keystrokes are sent:
- Tag mode: printable characters only (U+0020–U+007E, U+0080+). All special keys via `{tag}` syntax.
- Raw mode: printable characters + `\t` (Tab) + line endings (`\n`, `\r\n`, `\r` → Enter). No modifier combos.
- Control characters (escape sequences, null bytes, etc.) are not supported in either mode. To send arbitrary data, base64-encode it and decode on the remote side:
  `echo "echo '$(base64 -w0 file)' | base64 -d > /tmp/file{enter}" | vwctl -H HWND type -t`

**Mode defaults**: Text argument defaults to tag mode. Stdin and `--file` default to raw mode. Use `-r`/`--raw` or `-t`/`--tags` to override (mutually exclusive).

### Send mouse input

```bash
vwctl -H HWND click 400 300              # Left click at (400, 300) relative to window
vwctl -H HWND click 400 300 -b right     # Right click
vwctl -H HWND move 100 200               # Move cursor to (100, 200)
vwctl -H HWND move 10 -5 -r              # Move cursor by offset
vwctl -H HWND drag 0 0 200 200           # Drag from (0,0) to (200,200)
vwctl -H HWND scroll 3                   # Scroll up
vwctl -H HWND scroll -3                  # Scroll down
```

All coordinates are relative to the target window's top-left corner.

### Execute and read

```bash
vwctl -H HWND exec "whoami" -W 2.0
```

This is a convenience command that: clicks the window center → types the command (raw mode) → presses Enter → waits `-W` seconds (default: 1.0) → captures and OCRs the screen. Useful for running shell commands and reading output.

## No-Focus Mode (`-n`)

Send input without stealing focus from the current foreground window.

```bash
vwctl -w "Command Prompt" -n type "dir{enter}"
```

- Works with: `cmd.exe`, Git Bash, PuTTY, and other native Windows console apps
- Does NOT work with: Remote Desktop (RDP), browser-based apps (Guacamole, VNC web client), most GUI apps
- Combine with `-b` for fully background operation (no-focus input + background capture)

## Common Patterns

### Run a command and check output
```bash
vwctl -H 12345 type "git status{enter}"
sleep 2
vwctl -H 12345 ocr
```

### Navigate a menu
```bash
vwctl -H HWND key f -m alt          # Open File menu
sleep 0.5
vwctl -H HWND key enter             # Select first item
```

### Select all and copy
```bash
vwctl -H HWND type "{ctrl+a}{ctrl+c}"
```

### Scroll and read
```bash
vwctl -H HWND scroll -5             # Scroll down
sleep 0.5
vwctl -H HWND ocr                   # Read new content
```

### Fully background operation (cmd.exe)
```bash
vwctl -H HWND -n type "hostname{enter}"
sleep 1
vwctl -H HWND capture -b -o result.jpg
vwctl -H HWND ocr -b
```

## Constraints

- **Focus stealing**: Most commands bring the target window to the foreground. This is unavoidable for remote desktop apps.
- **Focus loss detection**: During `type`, `keys`, `send_keys`, and `send_key_sequence`, if the target window loses foreground focus, input is immediately aborted with a message indicating progress (e.g. `"typed 42 characters"` or `"sent 2/5 key steps"`). This prevents keystrokes from being sent to an unintended window. Disabled in no-focus mode (`-n` for CLI, `no_focus: true` for MCP).
- **Admin privileges**: If the target runs as admin, `vwctl` must also run as admin.
- **OCR accuracy**: Best with monospace fonts at 24pt+, high-contrast themes, and larger windows.
- **Background capture** (`-b`): Uses PrintWindow API. May produce black images for hardware-accelerated apps (DirectX, OpenGL, some Electron apps).
- **Timing**: After sending input, use `sleep` before OCR to allow the target application to update its display.
