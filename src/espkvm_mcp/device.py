# SPDX-FileCopyrightText: 2026 ESP-KVM contributors
# SPDX-License-Identifier: Apache-2.0
"""
The HTTP side: one session against one ESP-KVM.

Nothing here knows about MCP. It signs in, keeps the cookie, and re-signs in
when the device forgets us - a KVM restarts more often than most services, and
an automation that dies on the first restart is not an automation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError


class DeviceError(ToolError):
    """Something the caller should be told about verbatim. A ToolError, so the
    model reads the message; any other exception reaches it only as "Error
    executing tool"."""


@dataclass
class Config:
    url: str
    user: str
    password: str
    verify: Any  # a CA bundle path, or False to accept the device's own cert
    session: str = ""  # a kvm_session cookie value, used instead of signing in

    @classmethod
    def from_env(cls) -> "Config":
        url = os.environ.get("ESPKVM_URL", "").rstrip("/")
        if not url:
            raise DeviceError(
                "set ESPKVM_URL to the device, for example https://espkvm.local"
            )
        ca = os.environ.get("ESPKVM_CA")
        insecure = os.environ.get("ESPKVM_INSECURE", "").lower() in ("1", "true", "yes")
        return cls(
            url=url,
            user=os.environ.get("ESPKVM_USER", "admin"),
            password=os.environ.get("ESPKVM_PASSWORD", ""),
            verify=(ca if ca else (False if insecure else True)),
            session=os.environ.get("ESPKVM_SESSION", ""),
        )


class Device:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        # The device refuses a write that carries neither JSON nor this header,
        # so a form on another page cannot drive it through somebody's browser.
        # Sending it on everything costs nothing and covers the calls with no
        # body at all, like power.
        self.http = httpx.Client(
            base_url=cfg.url,
            verify=cfg.verify,
            timeout=15.0,
            follow_redirects=True,
            headers={"X-ESP-KVM": "1"},
        )
        if cfg.session:
            # A person's own session, handed over: the only way in when
            # two-factor sign-in is on, since a password alone is not enough.
            self.http.cookies.set("kvm_session", cfg.session)

    # ---- plumbing --------------------------------------------------------

    def login(self) -> None:
        if self.cfg.session:
            raise DeviceError(
                "the session in ESPKVM_SESSION has ended (a restart ends every "
                "session) - export a fresh kvm_session cookie from the browser"
            )
        r = self.http.post(
            "/api/v1/auth/login",
            json={"user": self.cfg.user, "password": self.cfg.password},
        )
        if r.status_code == 401:
            try:
                need_code = bool(r.json().get("needCode"))
            except ValueError:
                need_code = False
            if need_code:
                raise DeviceError(
                    "two-factor sign-in is on, so a password alone cannot sign "
                    "in - set ESPKVM_SESSION to a kvm_session cookie from a "
                    "signed-in browser instead"
                )
            raise DeviceError("the device rejected ESPKVM_USER / ESPKVM_PASSWORD")
        r.raise_for_status()

    def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        r = self.http.request(method, path, **kw)
        if r.status_code == 401:
            self.login()
            r = self.http.request(method, path, **kw)
        return r

    def json(self, method: str, path: str, **kw: Any) -> Any:
        r = self.request(method, path, **kw)
        if r.status_code == 403:
            raise DeviceError(
                "the device refused: " + self._error(r) +
                ". Input and screenshots need the agent API, which is off by "
                "default - turn it on in Settings > Security."
            )
        if r.status_code == 409:
            raise DeviceError(self._error(r))
        r.raise_for_status()
        return r.json() if r.content else None

    @staticmethod
    def _error(r: httpx.Response) -> str:
        try:
            return str(r.json().get("error", r.text))
        except Exception:
            return r.text or f"HTTP {r.status_code}"

    # ---- what the tools use ---------------------------------------------

    def screen_text(self) -> dict | None:
        """The screen as characters, or None when it is showing a picture."""
        r = self.request("GET", "/api/v1/screen/text")
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return r.json()

    def frame_jpeg(self) -> bytes:
        r = self.request("GET", "/api/v1/video/frame.jpg")
        if r.status_code == 409:
            raise DeviceError(
                "the device is streaming H.264, which this endpoint cannot "
                "snapshot - switch the codec to MJPEG in Settings > Video"
            )
        if r.status_code == 403:
            raise DeviceError(
                "screenshots need the agent API, which is off by default - "
                "turn it on in Settings > Security"
            )
        r.raise_for_status()
        return r.content

    def video_status(self) -> dict:
        return self.json("GET", "/api/v1/video/status")

    def system_info(self) -> dict:
        return self.json("GET", "/api/v1/system/info")

    def profiles(self) -> dict | None:
        """The device profiles (0.72.0), or None on a firmware without them."""
        r = self.request("GET", "/api/v1/profiles")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
