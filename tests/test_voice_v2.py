"""
VoxDesk — WebSocket Binary Handler Tests
voice_v2.py handler logic — handshake, binary dispatch, error responses.
Gerçek mikrofon KULLANILMAZ. FastAPI TestClient WebSocket mock.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from src.audio_protocol import (
    AudioSession,
    AudioConfig,
    AudioMessageType,
    BYTES_PER_CHUNK,
    MAX_FRAME_BYTES,
    validate_config,
    validate_binary_frame,
    build_config_ack,
    build_protocol_error,
)


# ══════════════════════════════════════════════════════════════
#  WebSocket Handler Logic — Unit Tests
#  (Handler'ı doğrudan çağırmak yerine logic'i test ederiz)
# ══════════════════════════════════════════════════════════════

class TestHandshakeLogic:
    """Handshake validation logic."""

    @pytest.mark.unit
    def test_valid_handshake_returns_ack(self):
        """Geçerli audio_config → accepted ack."""
        data = {
            "type": "audio_config",
            "protocol_version": 1,
            "encoding": "pcm_s16le",
            "sample_rate": 16000,
            "channels": 1,
        }
        config, err = validate_config(data)
        assert config is not None
        assert err is None

        ack = build_config_ack(config)
        assert ack["type"] == "audio_config_ack"
        assert ack["accepted"] is True

    @pytest.mark.unit
    def test_invalid_version_returns_error(self):
        """Geçersiz protocol_version → protocol_error."""
        data = {"protocol_version": 99}
        config, err = validate_config(data)
        assert config is None
        assert err is not None

        error_resp = build_protocol_error(err, "invalid_config")
        assert error_resp["type"] == "protocol_error"
        assert error_resp["code"] == "invalid_config"


class TestBinaryDispatch:
    """Binary frame dispatch logic."""

    @pytest.mark.unit
    def test_binary_before_handshake_detected(self):
        """Handshake öncesi binary frame tespit edilmeli."""
        session = AudioSession()
        assert session.handshake_done is False

    @pytest.mark.unit
    def test_binary_after_handshake_accepted(self):
        """Handshake sonrası binary frame kabul edilmeli."""
        session = AudioSession()
        session.accept_handshake(AudioConfig())
        assert session.handshake_done is True

        # Valid frame
        data = b"\x00" * BYTES_PER_CHUNK
        valid, err = validate_binary_frame(data)
        assert valid is True

    @pytest.mark.unit
    def test_oversized_binary_rejected(self):
        """Oversized binary frame reddedilmeli."""
        data = b"\x00" * (MAX_FRAME_BYTES + 2)
        valid, err = validate_binary_frame(data)
        assert valid is False

    @pytest.mark.unit
    def test_odd_byte_binary_rejected(self):
        """Tek byte sayılı frame reddedilmeli."""
        data = b"\x00" * 641
        valid, err = validate_binary_frame(data)
        assert valid is False


class TestSessionManagement:
    """Audio session state management."""

    @pytest.mark.unit
    def test_audio_end_resets_counters(self):
        """audio_end session counter'ları sıfırlamalı."""
        session = AudioSession()
        session.accept_handshake(AudioConfig())
        session.record_chunk(640)
        session.record_chunk(640)
        assert session.total_chunks == 2

        session.reset()
        assert session.total_chunks == 0
        assert session.sequence == 0
        assert session.handshake_done is True  # Session devam eder

    @pytest.mark.unit
    def test_audio_cancel_clears_state(self):
        """audio_cancel counter'ları sıfırlamalı."""
        session = AudioSession()
        session.accept_handshake(AudioConfig())
        session.record_chunk(640)
        session.reset()
        assert session.total_chunks == 0


# ══════════════════════════════════════════════════════════════
#  Frontend External URL Guard
# ══════════════════════════════════════════════════════════════

class TestFrontendSecurity:
    """Frontend dosyalarında external URL olmamalı."""

    @pytest.mark.regression
    def test_no_external_urls_in_frontend_js(self):
        """Frontend JS dosyalarında external URL olmamalı."""
        import re

        frontend_dir = Path(__file__).parent.parent / "frontend"
        if not frontend_dir.exists():
            pytest.skip("frontend dizini yok")

        url_pattern = re.compile(
            r'(?:https?://|wss?://)'
            r'(?!(?:localhost|127\.0\.0\.1|0\.0\.0\.0))'
            r'[a-zA-Z0-9]'
        )

        violations = []
        for js_file in frontend_dir.rglob("*.js"):
            content = js_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n"), 1):
                # Yorum satırlarını skip et
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if url_pattern.search(line):
                    violations.append(f"{js_file.name}:{i}: {line.strip()[:80]}")

        assert not violations, \
            f"Frontend'te external URL bulundu:\n" + \
            "\n".join(f"  - {v}" for v in violations)

    @pytest.mark.regression
    def test_no_external_urls_in_frontend_html(self):
        """Frontend HTML dosyalarında external URL olmamalı."""
        import re

        frontend_dir = Path(__file__).parent.parent / "frontend"
        if not frontend_dir.exists():
            pytest.skip("frontend dizini yok")

        url_pattern = re.compile(
            r'(?:src|href|action)=["\']'
            r'(?:https?://|//)'
            r'(?!(?:localhost|127\.0\.0\.1))'
        )

        violations = []
        for html_file in frontend_dir.rglob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n"), 1):
                if url_pattern.search(line):
                    violations.append(f"{html_file.name}:{i}: {line.strip()[:80]}")

        assert not violations, \
            f"Frontend HTML'de external URL bulundu:\n" + \
            "\n".join(f"  - {v}" for v in violations)

    @pytest.mark.regression
    def test_no_cdn_script_in_frontend(self):
        """Frontend'te CDN script/style yüklemesi olmamalı."""
        frontend_dir = Path(__file__).parent.parent / "frontend"
        if not frontend_dir.exists():
            pytest.skip("frontend dizini yok")

        cdn_patterns = [
            "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com",
            "unpkg.com",
            "googleapis.com",
            "fonts.googleapis.com",
            "stackpath.bootstrapcdn.com",
        ]

        violations = []
        for file in frontend_dir.rglob("*"):
            if file.is_file() and file.suffix in (".html", ".js", ".css"):
                content = file.read_text(encoding="utf-8")
                for cdn in cdn_patterns:
                    if cdn in content:
                        violations.append(f"{file.name}: {cdn}")

        assert not violations, \
            f"Frontend'te CDN kullanımı bulundu:\n" + \
            "\n".join(f"  - {v}" for v in violations)


# ══════════════════════════════════════════════════════════════
#  Route File Guard — voice_v2 src.registry import etmemeli
# ══════════════════════════════════════════════════════════════

class TestVoiceV2RouteGuard:
    """voice_v2.py route dosyası doğru guard'lara sahip olmalı."""

    @pytest.mark.regression
    def test_voice_v2_does_not_import_registry(self):
        """voice_v2.py doğrudan registry import etmemeli."""
        route_file = Path(__file__).parent.parent / "src" / "routes" / "voice_v2.py"
        content = route_file.read_text(encoding="utf-8")
        assert "from src.registry" not in content

    @pytest.mark.regression
    def test_voice_v2_uses_get_app_state(self):
        """voice_v2.py get_app_state() kullanmalı."""
        route_file = Path(__file__).parent.parent / "src" / "routes" / "voice_v2.py"
        content = route_file.read_text(encoding="utf-8")
        assert "get_app_state" in content
