"""
VoxDesk — WebSocket Connection Manager
Real-time chat, screen preview, voice streaming.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List
from fastapi import WebSocket

logger = logging.getLogger("voxdesk.ws")


class ConnectionManager:
    """WebSocket bağlantı yöneticisi."""

    def __init__(self):
        self._active: dict[str, list[WebSocket]] = {
            "chat": [],
            "screen": [],
            "voice": [],
            "voice_v2": [],
        }
        self._metrics = None  # Sprint 3: post-creation injection
        self._allowed_origins: List[str] | None = None  # Sprint 3.5: config-aware

    def set_metrics(self, metrics) -> None:
        """Post-creation metrics injection."""
        self._metrics = metrics

    def set_allowed_origins(self, origins: List[str]) -> None:
        """Sprint 3.5: Config-aware Origin enforcement.

        Tüm route'lar otomatik olarak bu allowlist'i kullanır.
        Route-level override hâlâ mümkün (parametre öncelikli).
        """
        self._allowed_origins = origins
        logger.info(f"WS Origin allowlist set: {origins}")

    async def connect(
        self,
        websocket: WebSocket,
        channel: str = "chat",
        allowed_origins: List[str] | None = None,
    ):
        """Yeni WebSocket bağlantısı kabul et — Origin validation ile."""
        # Sprint 3.5: Parametre-level override > instance-level default
        effective_origins = allowed_origins or self._allowed_origins
        if effective_origins is not None:
            origin = websocket.headers.get("origin")
            if origin is not None and not check_origin(origin, effective_origins):
                # Starlette requires accept before close
                await websocket.accept()
                await websocket.close(code=1008, reason="Origin not allowed")
                logger.warning(
                    f"WS Origin rejected [{channel}]: {origin}"
                )
                return False

        await websocket.accept()
        if channel not in self._active:
            self._active[channel] = []
        self._active[channel].append(websocket)
        logger.info(f"WS bağlandı [{channel}] — aktif: {len(self._active[channel])}")
        return True

    def disconnect(self, websocket: WebSocket, channel: str = "chat"):
        """WebSocket bağlantısını kaldır."""
        if channel in self._active and websocket in self._active[channel]:
            self._active[channel].remove(websocket)
        if self._metrics:
            self._metrics.increment("ws_disconnects_total")
        logger.info(f"WS ayrıldı [{channel}] — aktif: {len(self._active.get(channel, []))}")

    async def send_json(self, websocket: WebSocket, data: dict):
        """Tek bir client'a JSON gönder."""
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"WS gönderim hatası: {e}")

    async def send_text(self, websocket: WebSocket, text: str):
        """Tek bir client'a text gönder."""
        try:
            await websocket.send_text(text)
        except Exception as e:
            logger.error(f"WS text gönderim hatası: {e}")

    async def send_bytes(self, websocket: WebSocket, data: bytes):
        """Tek bir client'a binary data gönder (ses, frame vs.)."""
        try:
            await websocket.send_bytes(data)
        except Exception as e:
            logger.error(f"WS binary gönderim hatası: {e}")

    async def broadcast_json(self, channel: str, data: dict):
        """Bir kanaldaki tüm client'lara JSON gönder."""
        dead = []
        for ws in self._active.get(channel, []):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    async def broadcast_bytes(self, channel: str, data: bytes):
        """Bir kanaldaki tüm client'lara binary gönder."""
        dead = []
        for ws in self._active.get(channel, []):
            try:
                await ws.send_bytes(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    def get_connection_count(self, channel: str = None) -> int:
        """Aktif bağlantı sayısı."""
        if channel:
            return len(self._active.get(channel, []))
        return sum(len(v) for v in self._active.values())


def check_origin(origin: str, allowed: List[str]) -> bool:
    """
    Check if origin matches any pattern in the allowlist.
    Supports exact matches and wildcard port patterns (e.g. port replaced by *).

    Sprint 1 Task 5 — OWASP WebSocket Origin validation.
    """
    if not origin:
        return True  # Missing origin → non-browser client, allow

    for pattern in allowed:
        if "*" in pattern:
            # Wildcard port pattern: matches origin with any numeric port
            regex = re.escape(pattern).replace(r"\*", r"\d+")
            if re.fullmatch(regex, origin):
                return True
        else:
            if origin == pattern:
                return True
    return False
