"""
VoxDesk — Route & API Contract Tests
FastAPI endpoint modelleri, request/response formatları, audio decode, WS contracts.
Sunucu başlatmadan — sadece model ve helper doğrulaması.
"""

import pytest
import io
import base64
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch

from src.routes.chat import ChatRequest, ChatResponse
from src.audio_utils import decode_audio_raw_pcm, decode_audio_webm


# ══════════════════════════════════════════════════════════════
#  Request / Response Model Tests
# ══════════════════════════════════════════════════════════════

class TestChatModels:
    """Chat API request/response şemaları."""

    def test_chat_request_defaults(self):
        req = ChatRequest(message="test")
        assert req.message == "test"
        assert req.include_screen is True

    def test_chat_request_no_screen(self):
        req = ChatRequest(message="test", include_screen=False)
        assert req.include_screen is False

    def test_chat_request_empty_message(self):
        req = ChatRequest(message="")
        assert req.message == ""

    def test_chat_request_unicode(self):
        """Türkçe karakterler doğru taşınmalı."""
        req = ChatRequest(message="Hello world! 🌍")
        assert "world" in req.message
        assert "🌍" in req.message

    def test_chat_response(self):
        resp = ChatResponse(response="cevap", model="test-model")
        assert resp.response == "cevap"
        assert resp.model == "test-model"
        assert resp.has_image is False

    def test_chat_response_with_image(self):
        resp = ChatResponse(response="ok", model="m", has_image=True)
        assert resp.has_image is True

    def test_chat_response_serialization(self):
        """JSON'a dönüşebilmeli."""
        resp = ChatResponse(response="test", model="m")
        d = resp.model_dump()
        assert d["response"] == "test"
        assert d["has_image"] is False


# ══════════════════════════════════════════════════════════════
#  Audio Decode Tests
# ══════════════════════════════════════════════════════════════

class TestAudioDecode:
    """Audio decode helper fonksiyonları."""

    def test_decode_raw_pcm_valid(self):
        """Geçerli PCM S16LE data → normalized float32 numpy array."""
        original_int16 = np.array([3277, -16384, 29491], dtype=np.int16)
        raw_bytes = original_int16.tobytes()
        result = decode_audio_raw_pcm(raw_bytes)
        assert result is not None
        assert result.dtype == np.float32
        expected = original_int16.astype(np.float32) / 32768.0
        np.testing.assert_array_almost_equal(result, expected)

    def test_decode_raw_pcm_empty(self):
        """Boş bytes → boş array (crash değil)."""
        result = decode_audio_raw_pcm(b"")
        assert result is not None
        assert len(result) == 0

    def test_decode_raw_pcm_single_sample(self):
        """Tek sample."""
        single = np.array([13763], dtype=np.int16)  # ~0.42 normalized
        result = decode_audio_raw_pcm(single.tobytes())
        assert len(result) == 1
        assert abs(result[0] - 13763 / 32768.0) < 1e-5

    def test_decode_raw_pcm_preserves_negative(self):
        """Negatif değerler korunmalı."""
        neg = np.array([-32440, -16384, -328], dtype=np.int16)
        result = decode_audio_raw_pcm(neg.tobytes())
        expected = neg.astype(np.float32) / 32768.0
        np.testing.assert_array_almost_equal(result, expected)

    def test_decode_raw_pcm_silence(self):
        """Sıfır değerli ses."""
        silence = np.zeros(1000, dtype=np.int16)
        result = decode_audio_raw_pcm(silence.tobytes())
        assert len(result) == 1000
        assert np.all(result == 0.0)

    def test_decode_webm_import_guard(self):
        """decode_audio_webm geçersiz data → None döndürmeli."""
        # Geçersiz data → decode hatası → None
        result = decode_audio_webm(b"not_valid_webm_data")
        assert result is None


# ══════════════════════════════════════════════════════════════
#  WebSocket Message Contract Tests
# ══════════════════════════════════════════════════════════════

class TestWSMessageContracts:
    """Frontend ↔ Backend WS mesaj formatları tutarlı mı?"""

    def test_chat_send_format(self):
        """Frontend'in gönderdiği format."""
        msg = {"message": "Selam", "include_screen": True}
        assert "message" in msg
        assert isinstance(msg["include_screen"], bool)

    def test_chat_start_event(self):
        """Backend → Frontend: stream başlangıç."""
        event = {"type": "start", "model": "test-model"}
        assert event["type"] == "start"
        assert "model" in event

    def test_chat_token_event(self):
        """Backend → Frontend: streaming token."""
        event = {"type": "token", "content": "Mer"}
        assert event["type"] == "token"
        assert isinstance(event["content"], str)

    def test_chat_end_event(self):
        """Backend → Frontend: stream sonu."""
        event = {"type": "end", "full_response": "Hello there!"}
        assert event["type"] == "end"
        assert "full_response" in event

    def test_voice_audio_send_format(self):
        """Frontend → Backend: voice audio."""
        msg = {
            "type": "audio",
            "audio": base64.b64encode(b"fake_audio").decode(),
            "format": "webm",
        }
        assert msg["type"] == "audio"
        assert msg["format"] in ("webm", "pcm")
        decoded = base64.b64decode(msg["audio"])
        assert decoded == b"fake_audio"

    def test_voice_audio_pcm_format(self):
        """Frontend → Backend: PCM formatı."""
        msg = {"type": "audio", "audio": "AAAA", "format": "pcm"}
        assert msg["format"] == "pcm"

    def test_stt_result_event(self):
        """Backend → Frontend: STT sonucu."""
        event = {"type": "stt_result", "text": "Merhaba", "language": "tr"}
        assert event["type"] == "stt_result"
        assert isinstance(event["text"], str)
        assert isinstance(event["language"], str)

    def test_stt_empty_event(self):
        """Backend → Frontend: Boş ses algılandı."""
        event = {"type": "stt_empty"}
        assert event["type"] == "stt_empty"

    def test_llm_response_event(self):
        """Backend → Frontend: LLM cevabı."""
        event = {"type": "llm_response", "text": "Ekranını görüyorum!"}
        assert event["type"] == "llm_response"
        assert isinstance(event["text"], str)

    def test_tts_audio_event(self):
        """Backend → Frontend: TTS audio chunk."""
        event = {
            "type": "tts_audio",
            "audio": base64.b64encode(b"wav_data").decode(),
        }
        assert event["type"] == "tts_audio"
        decoded = base64.b64decode(event["audio"])
        assert decoded == b"wav_data"

    def test_screen_frame_event(self):
        """Backend → Frontend: screen capture frame."""
        event = {
            "type": "frame",
            "image": base64.b64encode(b"\xff\xd8").decode(),
            "timestamp": 1234567890.0,
            "width": 1920,
            "height": 1080,
        }
        assert event["type"] == "frame"
        assert event["width"] == 1920
        assert event["height"] == 1080
        assert isinstance(event["timestamp"], float)

    def test_all_event_types_unique(self):
        """Tüm event type'ları benzersiz olmalı."""
        types = [
            "start", "token", "end",          # chat stream
            "audio",                           # voice input
            "stt_result", "stt_empty",         # stt
            "stt_translated",                  # translator
            "llm_response",                    # llm
            "tts_audio",                       # tts
            "frame",                           # screen
            "voice_error",                     # error
        ]
        assert len(types) == len(set(types))


# ══════════════════════════════════════════════════════════════
#  Settings Model Tests
# ══════════════════════════════════════════════════════════════

class TestSettingsModels:
    """Settings API Pydantic modelleri."""

    def test_settings_response_model(self):
        from src.routes.settings import SettingsResponse
        resp = SettingsResponse(
            model="test",
            voice="af_heart",
            tts_speed=1.0,
            tts_enabled=True,
            capture_interval=1.0,
            personality="voxdesk",
            stt_language=None,
            voice_activation_enabled=False,
            voice_activation_threshold=-30.0,
            hotkeys={"activate": "ctrl+shift+space"},
        )
        assert resp.model == "test"
        assert resp.stt_language is None

    def test_settings_response_all_fields(self):
        """Tüm alanlar dump'ta görünmeli."""
        from src.routes.settings import SettingsResponse
        resp = SettingsResponse(
            model="m", voice="v", tts_speed=1.0, tts_enabled=True,
            capture_interval=1.0, personality="p", stt_language="tr",
            voice_activation_enabled=True, voice_activation_threshold=-25.0,
            hotkeys={},
        )
        d = resp.model_dump()
        expected_keys = {
            "model", "voice", "tts_speed", "tts_enabled",
            "capture_interval", "personality", "stt_language",
            "voice_activation_enabled", "voice_activation_threshold", "hotkeys",
        }
        assert set(d.keys()) == expected_keys

    def test_voice_update_request(self):
        from src.routes.settings import VoiceUpdateRequest
        req = VoiceUpdateRequest(voice="am_adam")
        assert req.voice == "am_adam"
        assert req.speed is None

    def test_voice_update_request_with_speed(self):
        from src.routes.settings import VoiceUpdateRequest
        req = VoiceUpdateRequest(voice="af_bella", speed=1.5)
        assert req.speed == 1.5

    def test_model_update_request(self):
        from src.routes.settings import ModelUpdateRequest
        req = ModelUpdateRequest(model="new-model:latest")
        assert req.model == "new-model:latest"


# ══════════════════════════════════════════════════════════════
#  Sprint 1 — /api/health and /api/status Contract Tests
# ══════════════════════════════════════════════════════════════

class TestHealthStatusEndpoints:
    """Sprint 1 Gap 1+2: Health stays minimal, Status has full shape."""

    @pytest.mark.regression
    def test_health_returns_minimal_fields(self):
        """Health must NOT include model or capture_running."""
        from src.main import health
        import asyncio
        result = asyncio.run(health())
        assert "status" in result
        assert "version" in result
        assert "uptime_seconds" in result
        assert "degraded" in result
        # Must NOT contain runtime state fields
        assert "model" not in result
        assert "capture_running" not in result
        assert "models" not in result
        assert "features" not in result

    @pytest.mark.regression
    def test_status_returns_expected_sections(self):
        """/api/status must have api/capture/connections/models/features/last_error."""
        from src.main import runtime_status
        import asyncio
        result = asyncio.run(runtime_status())
        assert "api" in result
        assert "capture" in result
        assert "connections" in result
        assert "models" in result
        assert "features" in result
        assert "last_error" in result

    @pytest.mark.regression
    def test_status_models_have_name_and_state(self):
        from src.main import runtime_status
        import asyncio
        result = asyncio.run(runtime_status())
        for key in ("stt", "llm", "tts", "translator"):
            assert "name" in result["models"][key]
            assert "state" in result["models"][key]

    @pytest.mark.regression
    def test_status_features_from_config(self):
        from src.main import runtime_status
        import asyncio
        result = asyncio.run(runtime_status())
        feats = result["features"]
        assert "enable_debug_metrics" in feats
        assert "enable_vram_unload" in feats
        assert isinstance(feats["enable_debug_metrics"], bool)

    @pytest.mark.regression
    def test_status_no_secrets_exposed(self):
        from src.main import runtime_status
        import asyncio
        import json
        result = asyncio.run(runtime_status())
        result_str = json.dumps(result)
        assert "API_KEY" not in result_str
        assert "TOKEN" not in result_str
        assert "password" not in result_str.lower()

    @pytest.mark.regression
    def test_status_connections_channels(self):
        from src.main import runtime_status
        import asyncio
        result = asyncio.run(runtime_status())
        conns = result["connections"]
        for ch in ("chat", "screen", "voice", "voice_v2"):
            assert ch in conns
            assert "count" in conns[ch]
            assert "state" in conns[ch]


class TestDebugMetricsFlag:
    """Sprint 1 Task 4: enable_debug_metrics enforcement."""

    @pytest.mark.regression
    def test_debug_metrics_disabled_returns_403(self):
        """Default enable_debug_metrics=false must raise 403."""
        from src.main import debug_metrics
        from fastapi import HTTPException
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(debug_metrics())
        assert exc_info.value.status_code == 403

    @pytest.mark.regression
    def test_debug_metrics_enabled_returns_report(self):
        """enable_debug_metrics=true must return full report dict."""
        from src.main import debug_metrics, get_app_state
        import asyncio
        state = get_app_state()
        original = state.config.features.enable_debug_metrics
        # Temporarily enable
        object.__setattr__(state.config.features, "enable_debug_metrics", True)
        try:
            result = asyncio.run(debug_metrics())
            assert isinstance(result, dict)
            assert "_scope" in result
        finally:
            object.__setattr__(state.config.features, "enable_debug_metrics", original)


# ══════════════════════════════════════════════════════════════
#  Sprint 1 — WebSocket Origin Validation Tests
# ══════════════════════════════════════════════════════════════

class TestCheckOrigin:
    """Sprint 1 Task 5: check_origin allowlist helper."""

    @pytest.mark.regression
    def test_exact_origin_match(self):
        from src.websocket_manager import check_origin
        allowed = ["http://127.0.0.1:8765", "http://localhost:8765"]
        assert check_origin("http://127.0.0.1:8765", allowed) is True

    @pytest.mark.regression
    def test_wildcard_port_localhost(self):
        from src.websocket_manager import check_origin
        allowed = ["http://localhost:*"]
        assert check_origin("http://localhost:8765", allowed) is True
        assert check_origin("http://localhost:3000", allowed) is True

    @pytest.mark.regression
    def test_wildcard_port_127(self):
        from src.websocket_manager import check_origin
        allowed = ["http://127.0.0.1:*"]
        assert check_origin("http://127.0.0.1:8765", allowed) is True

    @pytest.mark.regression
    def test_disallowed_origin_rejected(self):
        from src.websocket_manager import check_origin
        allowed = ["http://127.0.0.1:*", "http://localhost:*"]
        assert check_origin("http://evil.com", allowed) is False
        assert check_origin("https://attacker.io:8765", allowed) is False

    @pytest.mark.regression
    def test_missing_origin_allowed(self):
        """Missing origin (None) = non-browser client, should pass."""
        from src.websocket_manager import check_origin
        allowed = ["http://127.0.0.1:*"]
        assert check_origin(None, allowed) is True

    @pytest.mark.regression
    def test_empty_origin_rejected(self):
        """Empty string origin = suspicious, should be rejected."""
        from src.websocket_manager import check_origin
        allowed = ["http://127.0.0.1:*"]
        assert check_origin("", allowed) is False


# ══════════════════════════════════════════════════════════════
#  Sprint 1 — VRAM Feature Flag Tests
# ══════════════════════════════════════════════════════════════

class TestVRAMFeatureFlag:
    """Sprint 1 Task 8: VRAM monitor respects enable_vram_unload."""

    @pytest.mark.regression
    def test_vram_manager_not_running_by_default(self):
        """VRAMManager._running should start as False (monitor is not started in constructor)."""
        from src.vram_manager import VRAMManager
        vm = VRAMManager()
        assert vm._running is False

    @pytest.mark.regression
    def test_vram_manager_idle_timeout_zero_no_unload(self):
        """idle_timeout_seconds=0 means unload disabled."""
        from src.vram_manager import VRAMManager
        vm = VRAMManager(idle_timeout_seconds=0.0)
        assert vm.idle_timeout_seconds == 0.0
        # No models registered, get_report should work
        report = vm.get_report()
        assert report["monitor_running"] is False
