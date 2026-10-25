# SPDX-FileCopyrightText: 2026 ESP-KVM contributors
# SPDX-License-Identifier: Apache-2.0
"""
Key names to USB HID usage codes.

The device's API speaks HID usages, because that is what a keyboard sends. A
model should not have to know that F2 is 0x3B, so the names people actually use
are translated here. This is the standard HID keyboard/keypad page.
"""

from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

MODIFIERS = {
    "ctrl": 0x01,
    "control": 0x01,
    "shift": 0x02,
    "alt": 0x04,
    "gui": 0x08,
    "win": 0x08,
    "windows": 0x08,
    "cmd": 0x08,
    "meta": 0x08,
    "altgr": 0x40,
    "rightalt": 0x40,
}

KEYS: dict[str, int] = {
    "enter": 0x28, "return": 0x28,
    "esc": 0x29, "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "minus": 0x2D, "equal": 0x2E,
    "leftbracket": 0x2F, "rightbracket": 0x30,
    "backslash": 0x31, "semicolon": 0x33, "quote": 0x34,
    "grave": 0x35, "comma": 0x36, "period": 0x37, "slash": 0x38,
    "capslock": 0x39,
    "printscreen": 0x46, "scrolllock": 0x47, "pause": 0x48,
    "insert": 0x49, "home": 0x4A, "pageup": 0x4B,
    "delete": 0x4C, "del": 0x4C,
    "end": 0x4D, "pagedown": 0x4E,
    "right": 0x4F, "left": 0x50, "down": 0x51, "up": 0x52,
    "numlock": 0x53,
    "menu": 0x65, "application": 0x65,
}
for _i in range(26):  # a..z
    KEYS[chr(ord("a") + _i)] = 0x04 + _i
for _i, _d in enumerate("123456789"):  # 1..9 then 0
    KEYS[_d] = 0x1E + _i
KEYS["0"] = 0x27
for _i in range(1, 13):  # F1..F12
    KEYS[f"f{_i}"] = 0x3A + _i - 1


class UnknownKey(ToolError, ValueError):
    """A key name the map does not know; the message lists what it does."""


def parse(name: str) -> int:
    """One key name to its HID usage. Raises UnknownKey with a usable message."""
    key = name.strip().lower()
    if key in KEYS:
        return KEYS[key]
    if key.startswith("0x"):
        return int(key, 16)
    raise UnknownKey(
        f"unknown key {name!r}. Names are like: f2, del, enter, esc, up, "
        f"pagedown, a, 7 - or a raw HID usage as 0x3b"
    )


def parse_modifiers(names: list[str] | None) -> int:
    mask = 0
    for n in names or []:
        key = n.strip().lower()
        if key not in MODIFIERS:
            raise UnknownKey(
                f"unknown modifier {n!r}. Use ctrl, shift, alt, gui or altgr"
            )
        mask |= MODIFIERS[key]
    return mask
