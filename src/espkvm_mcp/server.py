# SPDX-FileCopyrightText: 2026 ESP-KVM contributors
# SPDX-License-Identifier: Apache-2.0
"""
An MCP server that puts an ESP-KVM in front of a model.

What makes this worth having is the screen text. A KVM already lets a person
see a machine that has no working OS; the device can now also hand back what a
BIOS or a boot loader is showing, as exact characters rather than a picture. A
model can read that, decide, and press a key - which is the whole loop of
sitting in front of a machine, minus the sitting.

Two deliberate limits:

  - Reading is always available; typing is not. The input tools appear only
    with --allow-input, and the power tools only with --allow-power, because a
    KVM is a keyboard attached to somebody's bare metal. The device has its own
    switch for the same reason (Settings > Security > agent API), and both have
    to be on.
  - The screen is read, never guessed. A text screen comes back exactly; a
    graphical one comes back as "this is a picture", and the model can take a
    screenshot instead of inventing what it says.
"""

from __future__ import annotations

import argparse
import time

from mcp.server.mcpserver import Image, MCPServer

from .device import Config, Device, DeviceError
from . import keys as keymap

ABS_MAX = 32767


def build(device: Device, allow_input: bool, allow_power: bool) -> MCPServer:
    mcp = MCPServer(
        name="espkvm",
        instructions=(
            "An ESP-KVM: the keyboard, mouse and screen of another machine, "
            "reachable even when that machine has no operating system running. "
            "Read the screen with read_screen; it returns exact text on a BIOS, "
            "boot loader or console, and tells you to take a screenshot when "
            "the screen is a picture instead."
        ),
    )

    # ---- reading ---------------------------------------------------------

    @mcp.tool()
    def read_screen() -> str:
        """
        What the target's screen says, as text.

        Works when the target is in a character mode: a BIOS setup, a boot
        loader, memtest, a Linux console. The characters are read from the grid
        the firmware draws them on, so the text is exact - if it cannot be read
        exactly it is not returned at all. Take a screenshot for anything
        graphical.
        """
        got = device.screen_text()
        if got is None:
            return (
                "The screen is not made of text right now - it is a picture "
                "(a desktop, or a graphical UEFI setup). Use screenshot() to "
                "look at it."
            )
        return (
            f"{got['rows']}x{got['cols']} characters, read {got['ageMs']} ms ago:\n\n"
            + got["text"]
        )

    @mcp.tool()
    def screenshot() -> Image:
        """
        A picture of the target's screen.

        For screens read_screen cannot read: a graphical UEFI setup, an
        installer, a desktop. Needs the device's agent API turned on, and the
        MJPEG codec.
        """
        return Image(data=device.frame_jpeg(), format="jpeg")

    @mcp.tool()
    def wait_for_screen_text(contains: str, timeout_seconds: int = 30) -> str:
        """
        Wait until the screen shows a piece of text, then return the screen.

        This is how to drive firmware reliably: wait for the words that are
        actually on the menu rather than guessing how long a machine takes and
        how many times to press down. Returns as soon as it matches.

        Args:
            contains: text to wait for, matched case-insensitively.
            timeout_seconds: give up after this long.
        """
        want = contains.lower()
        deadline = time.monotonic() + max(1, timeout_seconds)
        last = "nothing readable"
        while time.monotonic() < deadline:
            got = device.screen_text()
            if got:
                last = got["text"]
                if want in last.lower():
                    return f"Found {contains!r}. The screen now says:\n\n{last}"
            time.sleep(1.0)
        return (
            f"{contains!r} did not appear within {timeout_seconds}s. "
            f"The screen currently says:\n\n{last}"
        )

    @mcp.tool()
    def device_status() -> str:
        """How the KVM and its target are doing: video mode, codec, uptime, health."""
        v = device.video_status()
        s = device.system_info()
        signal = (
            f"{v['width']}x{v['height']} at {v['fps']:.0f} fps ({v['codec']})"
            if v.get("signal")
            else "no signal from the target"
        )
        out = (
            f"Target video: {signal}\n"
            f"Firmware {s.get('version')}, up {s.get('uptime', '?')}, "
            f"{s.get('tempC', '?')} C\n"
            f"Viewers: {v.get('viewers', 0)}"
        )
        p = device.profiles()
        if p:
            active = next((x for x in p["profiles"] if x["id"] == p["active"]), None)
            how = "" if p["active"] == 0 else (" (by hand)" if p.get("manual") else " (auto)")
            out += f"\nDevice profile: {active['name'] if active else '?'}{how}"
        return out

    # ---- acting ----------------------------------------------------------

    if allow_input:

        @mcp.tool()
        def press_key(key: str, modifiers: list[str] | None = None) -> str:
            """
            Press one key on the target, with optional modifiers held.

            Args:
                key: a name like f2, del, enter, esc, up, pagedown, a, 7 - or a
                    raw HID usage such as 0x3b.
                modifiers: any of ctrl, shift, alt, gui, altgr.
            """
            usage = keymap.parse(key)
            mod = keymap.parse_modifiers(modifiers)
            device.json("POST", "/api/v1/hid/key", json={"keys": [usage], "modifier": mod})
            return f"pressed {key}"

        @mcp.tool()
        def type_text(text: str) -> str:
            """
            Type text on the target, as a keyboard would.

            The characters land according to the keyboard layout the target has
            active, which the device's kbd_layout setting has to match.
            """
            # The device caps one request at 80 characters, so pace it here
            # rather than making the caller think about it.
            for i in range(0, len(text), 80):
                device.json("POST", "/api/v1/hid/type", json={"text": text[i : i + 80]})
            return f"typed {len(text)} characters"

        @mcp.tool()
        def click(x: float, y: float, button: str = "left") -> str:
            """
            Click somewhere on the target's screen.

            Args:
                x: horizontal position, 0.0 at the left edge to 1.0 at the right.
                y: vertical position, 0.0 at the top to 1.0 at the bottom.
                button: left, right or middle.
            """
            device.json(
                "POST",
                "/api/v1/hid/click",
                json={
                    "x": int(max(0.0, min(1.0, x)) * ABS_MAX),
                    "y": int(max(0.0, min(1.0, y)) * ABS_MAX),
                    "button": button,
                },
            )
            return f"clicked {button} at {x:.3f},{y:.3f}"

        @mcp.tool()
        def move_pointer(x: float, y: float) -> str:
            """Move the target's pointer without clicking. Coordinates as in click()."""
            device.json(
                "POST",
                "/api/v1/hid/move",
                json={
                    "x": int(max(0.0, min(1.0, x)) * ABS_MAX),
                    "y": int(max(0.0, min(1.0, y)) * ABS_MAX),
                },
            )
            return f"moved to {x:.3f},{y:.3f}"

        @mcp.tool()
        def select_profile(profile: str) -> str:
            """
            Switch the device profile: the pointer mode, gamepad and video
            settings kept for one target (a Steam Deck wants a relative pointer,
            a Switch a gamepad). The device usually picks it by itself from the
            attached target; this picks by hand until another target comes.

            Args:
                profile: a profile's name as device_status or the console shows it,
                    "Default" for the settings shared by every target.
            """
            p = device.profiles()
            if not p:
                raise DeviceError("this firmware has no device profiles")
            found = next((x for x in p["profiles"] if x["name"].lower() == profile.lower()), None)
            if not found:
                names = ", ".join(x["name"] for x in p["profiles"])
                raise DeviceError(f"no profile named {profile!r}; there are: {names}")
            r = device.json("POST", "/api/v1/profiles/select", json={"id": found["id"]})
            if r and r.get("reboot"):
                return (f"profile {found['name']} selected; its gamepad or EDID setting "
                        "applies after the device restarts")
            return f"profile {found['name']} selected"

    if allow_power:

        @mcp.tool()
        def power(action: str) -> str:
            """
            Power the target.

            Args:
                action: "click" taps the power button, "hold" holds it for a
                    hard power off, "reset" taps reset, "wake" sends a
                    Wake-on-LAN packet. All of these can lose the target's
                    unsaved work - say what you are about to do first.
            """
            if action not in ("click", "hold", "reset", "wake"):
                raise DeviceError("action must be click, hold, reset or wake")
            path = "/api/v1/power/wake" if action == "wake" else f"/api/v1/power/{action}"
            device.json("POST", path)
            return f"power {action} sent"

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Serve an ESP-KVM to an MCP client.",
        epilog="The device is configured with ESPKVM_URL, ESPKVM_USER, "
        "ESPKVM_PASSWORD and either ESPKVM_CA or ESPKVM_INSECURE=1.",
    )
    ap.add_argument(
        "--allow-input",
        action="store_true",
        help="offer the keyboard and pointer tools (the device's agent API must "
        "also be on). Without this the server can only look.",
    )
    ap.add_argument(
        "--allow-power",
        action="store_true",
        help="offer power and reset. These can cost the target unsaved work.",
    )
    args = ap.parse_args()

    device = Device(Config.from_env())
    build(device, args.allow_input, args.allow_power).run("stdio")


if __name__ == "__main__":
    main()
