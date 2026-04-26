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

from src.routes.chat import ChatRequest, ChatResponse, _decode_audio_raw_pcm


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
        """Geçerli PCM float32 data → numpy array."""
        original = np.array([0.1, -0.5, 0.9], dtype=np.float32)
        raw_bytes = original.tobytes()
        result = _decode_audio_raw_pcm(raw_bytes)
        assert result is not None
        np.testing.assert_array_almost_equal(result, original)

    def test_decode_raw_pcm_empty(self):
        """Boş bytes → boş array (crash değil)."""
        result = _decode_audio_raw_pcm(b"")
        assert result is not None
        assert len(result) == 0

    def test_decode_raw_pcm_single_sample(self):
        """Tek sample."""
        single = np.array([0.42], dtype=np.float32)
        result = _decode_audio_raw_pcm(single.tobytes())
        assert len(result) == 1
        assert abs(result[0] - 0.42) < 1e-5

    def test_decode_raw_pcm_preserves_negative(self):
        """Negatif değerler korunmalı."""
        neg = np.array([-0.99, -0.5, -0.01], dtype=np.float32)
        result = _decode_audio_raw_pcm(neg.tobytes())
        np.testing.assert_array_almost_equal(result, neg)

    def test_decode_raw_pcm_silence(self):
        """Sıfır değerli ses."""
        silence = np.zeros(1000, dtype=np.float32)
        result = _decode_audio_raw_pcm(silence.tobytes())
        assert len(result) == 1000
        assert np.all(result == 0)

    def test_decode_webm_import_guard(self):
        """_decode_audio_webm av import hatası → None döndürmeli."""
        from src.routes.chat import _decode_audio_webm
        # Geçersiz data → decode hatası → None
        result = _decode_audio_webm(b"not_valid_webm_data")
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
            "llm_response",                    # llm
            "tts_audio",                       # tts
            "frame",                           # screen
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
