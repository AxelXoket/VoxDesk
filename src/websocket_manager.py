"""
VoxDesk — WebSocket Connection Manager
Real-time chat, screen preview, voice streaming.
"""

from __future__ import annotations

import json
import logging
from fastapi import WebSocket

logger = logging.getLogger("voxdesk.ws")


class ConnectionManager:
    """WebSocket bağlantı yöneticisi."""

    def __init__(self):
        self._active: dict[str, list[WebSocket]] = {
            "chat": [],
            "screen": [],
            "voice": [],
        }

    async def connect(self, websocket: WebSocket, channel: str = "chat"):
        """Yeni WebSocket bağlantısı kabul et."""
        await websocket.accept()
        if channel not in self._active:
            self._active[channel] = []
        self._active[channel].append(websocket)
        logger.info(f"WS bağlandı [{channel}] — aktif: {len(self._active[channel])}")

    def disconnect(self, websocket: WebSocket, channel: str = "chat"):
        """WebSocket bağlantısını kaldır."""
        if channel in self._active and websocket in self._active[channel]:
            self._active[channel].remove(websocket)
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
