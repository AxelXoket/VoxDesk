"""
VoxDesk — Capture, WebSocket Manager, Isolation, Hotkey, Tray Tests
Alt sistemlerin unit testleri — hardware gerektirmez.
"""

import os
import time
import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch
from collections import deque

from src.capture import CapturedFrame, ScreenCapture
from src.websocket_manager import ConnectionManager
from src.hotkey import HotkeyManager
from src.tray import TrayIcon


# ══════════════════════════════════════════════════════════════
#  Capture Tests
# ══════════════════════════════════════════════════════════════

class TestCapturedFrame:
    """Frame veri yapısı testleri."""

    def test_basic_creation(self):
        frame = CapturedFrame(
            image_bytes=b"\xff\xd8\xff",
            timestamp=time.time(),
            width=1920,
            height=1080,
        )
        assert frame.width == 1920
        assert frame.height == 1080
        assert len(frame.image_bytes) == 3

    def test_defaults(self):
        frame = CapturedFrame(image_bytes=b"test", timestamp=0.0)
        assert frame.width == 0
        assert frame.height == 0

    def test_timestamp_stored(self):
        ts = 1714123456.789
        frame = CapturedFrame(image_bytes=b"x", timestamp=ts)
        assert frame.timestamp == ts


class TestScreenCapture:
    """ScreenCapture logic testleri (dxcam mock'lanır)."""

    def test_init_defaults(self):
        sc = ScreenCapture()
        assert sc.interval == 1.0
        assert sc.buffer_size == 30
        assert sc.jpeg_quality == 85
        assert sc.resize_width == 1920
        assert sc.is_running is False
        assert sc.buffer_count == 0

    def test_custom_init(self):
        sc = ScreenCapture(
            interval=0.5, buffer_size=10,
            jpeg_quality=60, resize_width=1280,
        )
        assert sc.interval == 0.5
        assert sc.buffer_size == 10
        assert sc.jpeg_quality == 60
        assert sc.resize_width == 1280

    def test_buffer_maxlen(self):
        sc = ScreenCapture(buffer_size=3)
        for i in range(5):
            sc._buffer.append(CapturedFrame(
                image_bytes=f"frame_{i}".encode(),
                timestamp=float(i),
            ))
        assert sc.buffer_count == 3
        # İlk 2 frame silinmiş olmalı
        assert sc._buffer[0].image_bytes == b"frame_2"

    def test_get_latest_frame_empty(self):
        sc = ScreenCapture()
        assert sc.get_latest_frame() is None

    def test_get_latest_frame(self):
        sc = ScreenCapture()
        sc._buffer.append(CapturedFrame(image_bytes=b"old", timestamp=1.0))
        sc._buffer.append(CapturedFrame(image_bytes=b"new", timestamp=2.0))
        latest = sc.get_latest_frame()
        assert latest.image_bytes == b"new"
        assert latest.timestamp == 2.0

    def test_get_recent_frames(self):
        sc = ScreenCapture()
        for i in range(10):
            sc._buffer.append(CapturedFrame(
                image_bytes=f"f{i}".encode(), timestamp=float(i),
            ))
        recent = sc.get_recent_frames(count=3)
        assert len(recent) == 3
        assert recent[0].timestamp == 7.0
        assert recent[-1].timestamp == 9.0

    def test_get_recent_frames_fewer_than_count(self):
        sc = ScreenCapture()
        sc._buffer.append(CapturedFrame(image_bytes=b"only", timestamp=1.0))
        recent = sc.get_recent_frames(count=5)
        assert len(recent) == 1

    def test_get_recent_frames_exact_count(self):
        """Tam count kadar frame varsa hepsini döndürmeli."""
        sc = ScreenCapture()
        for i in range(3):
            sc._buffer.append(CapturedFrame(
                image_bytes=f"f{i}".encode(), timestamp=float(i),
            ))
        recent = sc.get_recent_frames(count=3)
        assert len(recent) == 3

    def test_stop_without_start(self):
        """Başlatılmadan stop → crash olmamalı."""
        sc = ScreenCapture()
        sc.stop()  # crash olmamalı
        assert sc.is_running is False


# ══════════════════════════════════════════════════════════════
#  WebSocket Manager Tests
# ══════════════════════════════════════════════════════════════

class TestConnectionManager:
    """WebSocket bağlantı yönetimi testleri."""

    def test_initial_channels(self):
        mgr = ConnectionManager()
        assert mgr.get_connection_count() == 0
        assert mgr.get_connection_count("chat") == 0
        assert mgr.get_connection_count("screen") == 0
        assert mgr.get_connection_count("voice") == 0
        # Sprint 2: voice_v2 is now initialized at startup
        assert mgr.get_connection_count("voice_v2") == 0

    def test_unknown_channel_count(self):
        """Olmayan kanal → 0."""
        mgr = ConnectionManager()
        assert mgr.get_connection_count("nonexistent") == 0

    @pytest.mark.asyncio
    async def test_connect_and_count(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "chat")
        assert mgr.get_connection_count("chat") == 1
        ws.accept.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_custom_channel(self):
        """Tanımlı olmayan kanal oluşturulabilmeli."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "custom_channel")
        assert mgr.get_connection_count("custom_channel") == 1

    @pytest.mark.asyncio
    async def test_voice_v2_connect_disconnect(self):
        """Sprint 2: voice_v2 channel connect/disconnect lifecycle."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        # voice_v2 starts at 0
        assert mgr.get_connection_count("voice_v2") == 0
        # connect
        await mgr.connect(ws, "voice_v2")
        assert mgr.get_connection_count("voice_v2") == 1
        # disconnect
        mgr.disconnect(ws, "voice_v2")
        assert mgr.get_connection_count("voice_v2") == 0

    @pytest.mark.asyncio
    async def test_multiple_connections_same_channel(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        ws3 = AsyncMock()
        await mgr.connect(ws1, "chat")
        await mgr.connect(ws2, "chat")
        await mgr.connect(ws3, "chat")
        assert mgr.get_connection_count("chat") == 3

    @pytest.mark.asyncio
    async def test_disconnect(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "chat")
        mgr.disconnect(ws, "chat")
        assert mgr.get_connection_count("chat") == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent(self):
        """Var olmayan WS disconnect → hata vermemeli."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        mgr.disconnect(ws, "chat")
        assert mgr.get_connection_count("chat") == 0

    @pytest.mark.asyncio
    async def test_disconnect_wrong_channel(self):
        """Yanlış kanaldan disconnect → orijinal kanal etkilenmemeli."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "chat")
        mgr.disconnect(ws, "screen")  # yanlış kanal
        assert mgr.get_connection_count("chat") == 1

    @pytest.mark.asyncio
    async def test_send_json(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "chat")
        await mgr.send_json(ws, {"type": "test"})
        ws.send_json.assert_awaited_once_with({"type": "test"})

    @pytest.mark.asyncio
    async def test_send_text(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "chat")
        await mgr.send_text(ws, "hello")
        ws.send_text.assert_awaited_once_with("hello")

    @pytest.mark.asyncio
    async def test_send_bytes(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        await mgr.connect(ws, "voice")
        await mgr.send_bytes(ws, b"\x00\x01\x02")
        ws.send_bytes.assert_awaited_once_with(b"\x00\x01\x02")

    @pytest.mark.asyncio
    async def test_send_json_error_handled(self):
        """Gönderim hatası exception fırlatmamalı."""
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = Exception("connection lost")
        await mgr.send_json(ws, {"test": True})

    @pytest.mark.asyncio
    async def test_send_text_error_handled(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("broken pipe")
        await mgr.send_text(ws, "test")

    @pytest.mark.asyncio
    async def test_send_bytes_error_handled(self):
        mgr = ConnectionManager()
        ws = AsyncMock()
        ws.send_bytes.side_effect = Exception("disconnected")
        await mgr.send_bytes(ws, b"data")

    @pytest.mark.asyncio
    async def test_broadcast_json(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "screen")
        await mgr.connect(ws2, "screen")

        await mgr.broadcast_json("screen", {"type": "frame"})
        ws1.send_json.assert_awaited_once()
        ws2.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_broadcast_bytes(self):
        mgr = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1, "voice")
        await mgr.connect(ws2, "voice")

        data = b"\xff\xd8\xff"
        await mgr.broadcast_bytes("voice", data)
        ws1.send_bytes.assert_awaited_once_with(data)
        ws2.send_bytes.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        mgr = ConnectionManager()
        alive = AsyncMock()
        dead = AsyncMock()
        dead.send_json.side_effect = Exception("dead")

        await mgr.connect(alive, "chat")
        await mgr.connect(dead, "chat")
        assert mgr.get_connection_count("chat") == 2

        await mgr.broadcast_json("chat", {"msg": "hello"})
        assert mgr.get_connection_count("chat") == 1

    @pytest.mark.asyncio
    async def test_broadcast_bytes_removes_dead(self):
        mgr = ConnectionManager()
        alive = AsyncMock()
        dead = AsyncMock()
        dead.send_bytes.side_effect = Exception("dead")

        await mgr.connect(alive, "voice")
        await mgr.connect(dead, "voice")
        await mgr.broadcast_bytes("voice", b"data")
        assert mgr.get_connection_count("voice") == 1

    @pytest.mark.asyncio
    async def test_broadcast_empty_channel(self):
        """Boş kanala broadcast → hata yok."""
        mgr = ConnectionManager()
        await mgr.broadcast_json("chat", {"x": 1})  # crash olmamalı

    @pytest.mark.asyncio
    async def test_total_connection_count(self):
        mgr = ConnectionManager()
        await mgr.connect(AsyncMock(), "chat")
        await mgr.connect(AsyncMock(), "screen")
        await mgr.connect(AsyncMock(), "voice")
        assert mgr.get_connection_count() == 3


# ══════════════════════════════════════════════════════════════
#  Isolation Tests
# ══════════════════════════════════════════════════════════════

class TestIsolation:
    """Environment guard testleri."""

    def test_env_guards_set(self):
        from src.isolation import _set_env_guards
        _set_env_guards()
        assert os.environ.get("HF_HUB_OFFLINE") == "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"

    def test_env_guards_idempotent(self):
        """İki kez çağrılsa bile aynı sonuç."""
        from src.isolation import _set_env_guards
        _set_env_guards()
        _set_env_guards()
        assert os.environ.get("HF_HUB_OFFLINE") == "1"

    def test_verify_isolation_returns_dict(self):
        from src.isolation import verify_isolation
        report = verify_isolation()
        assert isinstance(report, dict)
        assert "env_guards_set" in report
        assert "internet_blocked" in report
        assert "status" in report
        assert report["env_guards_set"] is True
        assert report["status"] in ("OK", "WARNING")

    def test_verify_isolation_required_keys(self):
        """Rapor tam 3 anahtar içermeli."""
        from src.isolation import verify_isolation
        report = verify_isolation()
        assert set(report.keys()) == {"env_guards_set", "internet_blocked", "status"}


# ══════════════════════════════════════════════════════════════
#  Hotkey Manager Tests
# ══════════════════════════════════════════════════════════════

class TestHotkeyManager:
    """Hotkey parsing ve callback testleri."""

    def test_default_keys(self):
        hk = HotkeyManager()
        assert hk.activate_key == "ctrl+shift+space"
        assert hk.toggle_listen_key == "ctrl+shift+v"
        assert hk.push_to_talk_key == "ctrl+shift+b"

    def test_custom_keys(self):
        hk = HotkeyManager(
            activate_key="f1",
            toggle_listen_key="f2",
            push_to_talk_key="f3",
        )
        assert hk.activate_key == "f1"
        assert hk.toggle_listen_key == "f2"
        assert hk.push_to_talk_key == "f3"

    def test_not_running_on_init(self):
        hk = HotkeyManager()
        assert hk._running is False

    def test_set_callback(self):
        hk = HotkeyManager()
        called = []
        hk.set_callback("activate", lambda: called.append("activated"))
        hk._fire("activate")
        assert called == ["activated"]

    def test_set_multiple_callbacks(self):
        hk = HotkeyManager()
        results = []
        hk.set_callback("activate", lambda: results.append("a"))
        hk.set_callback("toggle_listen", lambda: results.append("t"))
        hk._fire("activate")
        hk._fire("toggle_listen")
        assert results == ["a", "t"]

    def test_callback_overwrite(self):
        """Aynı action'a yeni callback → eski yerine geçmeli."""
        hk = HotkeyManager()
        results = []
        hk.set_callback("activate", lambda: results.append("old"))
        hk.set_callback("activate", lambda: results.append("new"))
        hk._fire("activate")
        assert results == ["new"]

    def test_fire_without_callback(self):
        """Callback atanmadan fire → hata vermemeli."""
        hk = HotkeyManager()
        hk._fire("activate")

    def test_fire_unknown_action(self):
        """Bilinmeyen action fire → hata vermemeli."""
        hk = HotkeyManager()
        hk._fire("nonexistent_action")

    def test_fire_with_error_in_callback(self):
        """Callback hata verirse fire crash olmamalı."""
        hk = HotkeyManager()
        hk.set_callback("activate", lambda: 1 / 0)
        hk._fire("activate")

    def test_ptt_key_parsing(self):
        """Push-to-talk key son tuşu doğru parse edilmeli."""
        hk = HotkeyManager(push_to_talk_key="ctrl+alt+x")
        parts = hk.push_to_talk_key.split("+")
        assert parts[-1] == "x"
        assert parts[:-1] == ["ctrl", "alt"]

    def test_ptt_key_parsing_single_key(self):
        """Tek tuşlu PTT — modifier yok."""
        hk = HotkeyManager(push_to_talk_key="f5")
        parts = hk.push_to_talk_key.split("+")
        assert parts[-1] == "f5"
        assert parts[:-1] == []


# ══════════════════════════════════════════════════════════════
#  Tray Icon Tests
# ══════════════════════════════════════════════════════════════

class TestTrayIcon:
    """TrayIcon callback testleri."""

    def test_init_no_callbacks(self):
        tray = TrayIcon()
        assert tray.on_show is None
        assert tray.on_quit is None
        assert tray._icon is None

    def test_init_with_callbacks(self):
        show_fn = lambda: None
        quit_fn = lambda: None
        tray = TrayIcon(on_show=show_fn, on_quit=quit_fn)
        assert tray.on_show is show_fn
        assert tray.on_quit is quit_fn

    def test_quit_calls_callback(self):
        called = []
        tray = TrayIcon(on_quit=lambda: called.append(True))
        tray._quit()
        assert called == [True]

    def test_quit_without_callback(self):
        """Callback olmadan quit → hata vermemeli."""
        tray = TrayIcon()
        tray._quit()

    def test_stop_without_icon(self):
        """Icon oluşmadan stop → hata vermemeli."""
        tray = TrayIcon()
        tray.stop()

    def test_create_icon_image(self):
        """Tray ikonu oluşturulabilmeli (PIL gerektirir)."""
        tray = TrayIcon()
        img = tray._create_icon_image()
        assert img.size == (64, 64)
        assert img.mode == "RGBA"
