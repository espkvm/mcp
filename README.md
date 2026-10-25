# espkvm-mcp

An [MCP](https://modelcontextprotocol.io) server that gives a model the screen,
keyboard and mouse of a machine through an [ESP-KVM](https://espkvm.io).

The interesting part is the screen. A KVM already lets a *person* see a machine
that has no working operating system; the device can also hand back what a BIOS
or a boot loader is showing **as exact characters** rather than as a picture. So
a model can read the firmware menu, decide, and press a key — which is the whole
loop of sitting in front of a machine, minus the sitting.

Runs on your computer, talks to the device over its normal HTTPS API. Nothing is
installed on the KVM, and nothing here reaches the internet.

## What it can do

Always:

| Tool | |
|---|---|
| `read_screen` | the screen as exact text, on a BIOS, boot loader, memtest or console |
| `screenshot` | a picture, for screens that are pictures |
| `wait_for_screen_text` | wait for words to appear, then return the screen |
| `device_status` | video mode, codec, firmware version, temperature, device profile |

With `--allow-input`:

| Tool | |
|---|---|
| `press_key` | one key, with modifiers: `f2`, `del`, `enter`, `up`, `ctrl`+`alt`+`del` |
| `type_text` | type a string, paced to what the device accepts |
| `click`, `move_pointer` | the pointer, in 0..1 screen coordinates |
| `select_profile` | switch the device profile (pointer mode, gamepad, video for one target) by name |

With `--allow-power`:

| Tool | |
|---|---|
| `power` | tap power, hold power, reset, or Wake-on-LAN |

## Reading is exact, or it is refused

`read_screen` is not OCR. A text-mode screen is drawn by a character generator —
a fixed grid, a fixed bitmap per character — so the device reads each cell by
looking it up in the font. Either the cell matches and the character is certain,
or the screen is reported as unreadable. There is no "recognised with errors",
which matters when the thing being read is a serial number or an error code
somebody is about to act on.

The other side of that: a **graphical** UEFI setup has no grid and is not read at
all. `read_screen` says so and points at `screenshot`.

## Install and register

The server needs Python 3.10+ and the device's address.

With Claude Code:

```sh
claude mcp add espkvm \
  -e ESPKVM_URL=https://espkvm.local \
  -e ESPKVM_PASSWORD=your-password \
  -- uvx --from git+https://github.com/espkvm/mcp espkvm-mcp
```

Add `--allow-input` after `espkvm-mcp` to let the model use the keyboard and
mouse as well (see the warning below), and `--allow-power` for power control.

For a client that takes a JSON config, such as Claude Desktop:

```json
{
  "mcpServers": {
    "espkvm": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/espkvm/mcp", "espkvm-mcp"],
      "env": {
        "ESPKVM_URL": "https://espkvm.local",
        "ESPKVM_PASSWORD": "your-password"
      }
    }
  }
}
```

### In a container (Podman or Docker)

No Python needed, only Podman or Docker. The image is `ghcr.io/espkvm/mcp`, for
x86-64 and ARM:

```sh
claude mcp add espkvm -- docker run -i --rm \
  -e ESPKVM_URL=https://192.168.1.42 \
  -e ESPKVM_PASSWORD=your-password \
  -e ESPKVM_CA=/ca.pem -v "$PWD/espkvm-ca.pem:/ca.pem:ro" \
  ghcr.io/espkvm/mcp
```

Flags go at the end, after the image name: `ghcr.io/espkvm/mcp --allow-input`.
In a JSON config the command is `docker` and the rest goes in `args`.

Use the device's **IP address**, not `espkvm.local`: that name is mDNS, which
does not reach a container through its network bridge. On Linux,
`--network host` makes `espkvm.local` work too. Keep `-i` and leave out `-t`:
the server talks MCP over stdin and stdout.

Podman takes the same command with `podman` in place of `docker`. On Fedora or
RHEL add `,Z` to the mount (`:/ca.pem:ro,Z`) so SELinux lets the container read
the file, and keep the CA file readable by everyone (`chmod 644`): the server
runs as an unprivileged user inside the container.

To build the image yourself: `podman build -t espkvm-mcp .`, or
`docker build -f Containerfile -t espkvm-mcp .`

### Settings

| Variable | |
|---|---|
| `ESPKVM_URL` | the device, e.g. `https://espkvm.local` — required |
| `ESPKVM_PASSWORD` | the console password |
| `ESPKVM_USER` | defaults to `admin` |
| `ESPKVM_SESSION` | a `kvm_session` cookie from a signed-in browser, used instead of the password - the only way in when two-factor sign-in is on. A device restart ends it |
| `ESPKVM_CA` | path to the device's CA certificate (download it from `/cert.pem`) |
| `ESPKVM_INSECURE` | `1` to accept the device's certificate without checking it |

A device issues its own certificate, so one of `ESPKVM_CA` or `ESPKVM_INSECURE`
is usually needed. Prefer the CA: it is one download and it makes the connection
real rather than nominal.

## Before you turn on input

This hands a model a keyboard and mouse on somebody's bare metal, at a moment
when that machine may have no operating system to protect itself. Treat it as
you would giving anyone else physical access to the box.

- Input and screenshots also require the **agent API** on the device itself
  (Settings → Security). Both switches have to be on; either one off is a no.
- Start without `--allow-input`. Reading is useful on its own, and it is the
  half that cannot break anything.
- `--allow-power` can cost the target unsaved work. Turn it on for a machine
  you are deliberately recovering, not by default.
- The KVM is not a security boundary, and neither is this. Keep both on a
  network you trust.

## What it is good for

- **"Look at this machine and tell me why it will not boot."** The model reads
  the screen instead of you photographing it.
- **Changing a BIOS setting without counting keystrokes.** `wait_for_screen_text`
  waits for the menu entry to appear, so the same instructions survive a
  different firmware version — where a fixed sequence of arrow keys does not.
- **Unattended install or recovery.** Mount an image on the KVM, power the
  target on, and let the model walk the installer by reading what it says.
- **A runbook that reads.** "If the screen says *no boot device*, reset and boot
  the rescue image" is a rule a model can follow, and now check.

## Limits worth knowing

- `type_text` sends key *positions*, not characters. What lands depends on the
  layout the target has active — set the device's `kbd_layout` to match.
- `screenshot` needs the MJPEG codec; the device cannot snapshot an H.264 stream.
- The device reads the screen while a viewer is connected. Open the console, or
  leave a session running, when you expect a model to be watching.

## Tests

No device needed — the tools are checked against a stand-in for the firmware:

```sh
python3 tests/test_server.py
```

## Licence

Apache-2.0, like the firmware.
