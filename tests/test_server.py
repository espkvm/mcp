# SPDX-FileCopyrightText: 2026 ESP-KVM contributors
# SPDX-License-Identifier: Apache-2.0
"""
The tools, against a stand-in for the device.

The point of these is the contract: what the firmware answers, and what each
tool makes of it. A stub server is enough for that and needs no hardware, which
means the whole thing can be checked before a KVM is anywhere near it.

    python3 tests/test_server.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from espkvm_mcp.device import Config, Device  # noqa: E402
from espkvm_mcp.server import build  # noqa: E402

SCREEN = {
    "cols": 80,
    "rows": 25,
    "cellWidth": 9,
    "cellHeight": 16,
    "confidence": 100,
    "ageMs": 140,
    "text": "Aptio Setup Utility\n\n  Boot Option #1  [UEFI: Samsung SSD]\n"
            "  Serial Number   5CG9382KJ7",
}

state = {"text": True, "posts": []}

PROFILES = {
    "active": 1, "manual": False, "max": 8, "presets": [],
    "profiles": [{"id": 0, "name": "Default"},
                 {"id": 1, "name": "Steam Deck", "match": {}, "set": {"mouse_mode": 1}}],
}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):  # keep the test output clean
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        if body:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/v1/screen/text":
            if not state["text"]:
                return self._send(204)
            return self._send(200, json.dumps(SCREEN).encode())
        if self.path == "/api/v1/video/frame.jpg":
            return self._send(200, b"\xff\xd8\xff\xd9", "image/jpeg")
        if self.path == "/api/v1/video/status":
            return self._send(200, json.dumps(
                {"signal": True, "width": 720, "height": 400, "fps": 24.0,
                 "codec": "mjpeg", "viewers": 1}).encode())
        if self.path == "/api/v1/profiles":
            return self._send(200, json.dumps(PROFILES).encode())
        if self.path == "/api/v1/system/info":
            return self._send(200, json.dumps(
                {"version": "0.28.0", "uptime": "3h", "tempC": 44.1}).encode())
        self._send(404, b'{"error":"no such route"}')

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        state["posts"].append((self.path, body))
        if self.path == "/api/v1/auth/login":
            self.send_response(200)
            self.send_header("Set-Cookie", "kvm_session=abc; Path=/")
            self.send_header("Content-Length", "2")
            self.end_headers()
            return self.wfile.write(b"{}")
        if self.path == "/api/v1/profiles/select":
            return self._send(200, json.dumps({**PROFILES, "reboot": False}).encode())
        self._send(200, b"{}")


def call(mcp, name, **args):
    """Run a tool and flatten what it returned. A refused call comes back as its
    message, which is what an MCP client shows the model."""
    try:
        res = asyncio.run(mcp.call_tool(name, args))
    except Exception as e:  # ToolError and anything a tool raised
        return str(e)
    parts = []
    for c in res.content:
        parts.append(getattr(c, "text", None) or getattr(c, "mime_type", "?"))
    return "\n".join(p for p in parts if p)


failures = 0


def check(ok, what):
    global failures
    print(f"{what:<56} {'ok' if ok else 'FAIL'}")
    if not ok:
        failures += 1


def main() -> int:
    logging.disable(logging.INFO)  # httpx narrates every request otherwise
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]

    cfg = Config(url=f"http://127.0.0.1:{port}", user="admin", password="admin", verify=False)
    mcp = build(Device(cfg), allow_input=True, allow_power=True)

    out = call(mcp, "read_screen")
    check("5CG9382KJ7" in out, "read_screen returns the screen text")
    check("25x80 characters" in out, "read_screen reports the grid")

    state["text"] = False
    out = call(mcp, "read_screen")
    check("not made of text" in out and "screenshot()" in out,
          "a picture is reported as a picture, with a way forward")
    state["text"] = True

    out = call(mcp, "screenshot")
    check("image/jpeg" in out, "screenshot comes back as an image")

    out = call(mcp, "wait_for_screen_text", contains="boot option", timeout_seconds=5)
    check("Found" in out, "wait_for_screen_text matches, case-insensitively")

    out = call(mcp, "device_status")
    check("720x400" in out and "0.28.0" in out, "device_status summarises both halves")
    check("Device profile: Steam Deck (auto)" in out, "device_status names the profile")

    state["posts"].clear()
    out = call(mcp, "select_profile", profile="default")
    check(state["posts"] == [("/api/v1/profiles/select", {"id": 0})] and "Default" in out,
          "select_profile finds a profile by name, any case")
    out = call(mcp, "select_profile", profile="Switch")
    check("there are: Default, Steam Deck" in out, "an unknown profile lists the real ones")

    state["posts"].clear()
    call(mcp, "press_key", key="F2")
    check(state["posts"] == [("/api/v1/hid/key", {"keys": [0x3B], "modifier": 0})],
          "press_key sends the right HID usage")

    state["posts"].clear()
    call(mcp, "press_key", key="del", modifiers=["ctrl", "alt"])
    check(state["posts"][0][1] == {"keys": [0x4C], "modifier": 0x05},
          "modifiers are combined into the mask")

    out = call(mcp, "press_key", key="wibble")
    check("unknown key" in out, "an unknown key name explains itself")

    state["posts"].clear()
    call(mcp, "type_text", text="x" * 195)
    check([p[0] for p in state["posts"]] == ["/api/v1/hid/type"] * 3
          and len(state["posts"][0][1]["text"]) == 80,
          "type_text is split to the device's 80-character limit")

    state["posts"].clear()
    call(mcp, "click", x=0.5, y=1.0, button="right")
    check(state["posts"][0][1] == {"x": 16383, "y": 32767, "button": "right"},
          "click maps 0..1 onto the absolute range")

    state["posts"].clear()
    call(mcp, "power", action="reset")
    check(state["posts"][0][0] == "/api/v1/power/reset", "power reaches the right route")
    out = call(mcp, "power", action="explode")
    check("must be click" in out, "an unknown power action is refused")

    tools = asyncio.run(build(Device(cfg), False, False).list_tools())
    names = {t.name for t in tools}
    check("press_key" not in names and "power" not in names and "select_profile" not in names
          and "read_screen" in names,
          "without the flags, the server can only look")

    srv.shutdown()
    print("\n" + ("FAILURES" if failures else "all good"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
