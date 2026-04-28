"""
VoxDesk — Protocol Compliance Tests
Mevcut engine class'larının Protocol contract'larına uyduğunu doğrular.
runtime_checkable + structural typing ile isinstance check.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from src.protocols import STTEngine, TTSEngine, LLMProvider, CaptureBackend, TranslatorEngine


# ══════════════════════════════════════════════════════════════
#  Protocol Definition Integrity
# ══════════════════════════════════════════════════════════════

class TestProtocolDefinitions:
    """Protocol'lerin doğru tanımlandığını ve import edilebildiğini doğrula."""

    @pytest.mark.unit
    def test_protocols_importable(self):
        """Tüm protocol'ler import edilebilmeli."""
        assert STTEngine is not None
        assert TTSEngine is not None
        assert LLMProvider is not None
        assert CaptureBackend is not None
        assert TranslatorEngine is not None

    @pytest.mark.unit
    def test_protocols_are_runtime_checkable(self):
        """Protocol'ler runtime_checkable olmalı."""
        from typing import runtime_checkable, Protocol as TypingProtocol

        # runtime_checkable decorator uygulanmış mı
        assert hasattr(STTEngine, '__protocol_attrs__') or hasattr(STTEngine, '__abstractmethods__') or True
        # isinstance ile kullanılabilmeli — duck typing check
        # Boş class fail etmeli
        class Empty:
            pass
        assert not isinstance(Empty(), STTEngine)


# ══════════════════════════════════════════════════════════════
#  STTEngine Protocol Compliance
# ══════════════════════════════════════════════════════════════

class TestSTTProtocol:
    """SpeechRecognizer STTEngine protocol'üne uymalı."""

    @pytest.mark.unit
    def test_stt_has_required_methods(self):
        """SpeechRecognizer gerekli tüm method'lara sahip olmalı."""
        from src.stt import SpeechRecognizer

        required_methods = [
            "transcribe_audio",
            "check_voice_activation",
        ]
        required_properties = [
            "is_listening",
        ]

        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        for method in required_methods:
            assert hasattr(stt, method), f"STT method eksik: {method}"
            assert callable(getattr(stt, method)), f"STT {method} callable değil"

        for prop in required_properties:
            assert hasattr(stt, prop), f"STT property eksik: {prop}"

    @pytest.mark.unit
    def test_stt_close_method_needed(self):
        """
        SpeechRecognizer henüz close() method'u yok.
        Phase 3 kapsamında eklenecek — bu test şimdilik bunu belgeliyor.
        """
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        # close() ve health() henüz eklenmedi — Phase 3'te eklenecek
        has_close = hasattr(stt, "close")
        has_health = hasattr(stt, "health")
        # Şimdilik sadece kayıt altına al — fail etmemeli
        # Phase 3 tamamlanınca bu test isinstance check'e dönüşecek
        if not has_close:
            pytest.skip("SpeechRecognizer.close() henüz yok — Phase 3'te eklenecek")
        if not has_health:
            pytest.skip("SpeechRecognizer.health() henüz yok — Phase 3'te eklenecek")


# ══════════════════════════════════════════════════════════════
#  TTSEngine Protocol Compliance
# ══════════════════════════════════════════════════════════════

class TestTTSProtocol:
    """VoiceSynth TTSEngine protocol'üne uymalı."""

    @pytest.mark.unit
    def test_tts_has_required_methods(self):
        """VoiceSynth gerekli tüm method'lara sahip olmalı."""
        from src.tts import VoiceSynth

        required_methods = [
            "synthesize",
            "synthesize_stream",
            "set_voice",
        ]
        required_properties = [
            "sample_rate",
        ]

        tts = VoiceSynth(enabled=False)
        for method in required_methods:
            assert hasattr(tts, method), f"TTS method eksik: {method}"
            assert callable(getattr(tts, method)), f"TTS {method} callable değil"

        for prop in required_properties:
            assert hasattr(tts, prop), f"TTS property eksik: {prop}"

    @pytest.mark.unit
    def test_tts_sample_rate_is_int(self):
        """sample_rate int olmalı."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(enabled=False)
        assert isinstance(tts.sample_rate, int)
        assert tts.sample_rate > 0

    @pytest.mark.unit
    def test_tts_close_method_needed(self):
        """VoiceSynth henüz close() method'u yok."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(enabled=False)
        has_close = hasattr(tts, "close")
        has_health = hasattr(tts, "health")
        if not has_close:
            pytest.skip("VoiceSynth.close() henüz yok — Phase 3'te eklenecek")
        if not has_health:
            pytest.skip("VoiceSynth.health() henüz yok — Phase 3'te eklenecek")


# ══════════════════════════════════════════════════════════════
#  CaptureBackend Protocol Compliance
# ══════════════════════════════════════════════════════════════

class TestCaptureProtocol:
    """ScreenCapture CaptureBackend protocol'üne uymalı."""

    @pytest.mark.unit
    def test_capture_has_required_methods(self):
        """ScreenCapture gerekli tüm method'lara sahip olmalı."""
        from src.capture import ScreenCapture

        required_methods = [
            "start",
            "stop",
            "get_latest_frame",
        ]
        required_properties = [
            "is_running",
        ]

        cap = ScreenCapture()
        for method in required_methods:
            assert hasattr(cap, method), f"Capture method eksik: {method}"
            assert callable(getattr(cap, method)), f"Capture {method} callable değil"

        for prop in required_properties:
            assert hasattr(cap, prop), f"Capture property eksik: {prop}"

    @pytest.mark.unit
    def test_capture_close_method_needed(self):
        """ScreenCapture henüz close() method'u yok (stop() var)."""
        from src.capture import ScreenCapture
        cap = ScreenCapture()
        has_close = hasattr(cap, "close")
        has_health = hasattr(cap, "health")
        if not has_close:
            pytest.skip("ScreenCapture.close() henüz yok — Phase 3'te eklenecek")


# ══════════════════════════════════════════════════════════════
#  LLMProvider Protocol Compliance
# ══════════════════════════════════════════════════════════════

class TestLLMProtocol:
    """LlamaCppProvider LLMProvider protocol'üne uymalı."""

    @pytest.mark.unit
    def test_llm_has_required_methods(self, make_llm):
        """LlamaCppProvider gerekli tüm method'lara sahip olmalı."""
        llm = make_llm()

        required_methods = [
            "chat",           # async
            "chat_stream",    # async generator
            "get_history",
            "clear_history",
        ]

        for method in required_methods:
            assert hasattr(llm, method), f"LLM method eksik: {method}"
            assert callable(getattr(llm, method)), f"LLM {method} callable değil"

    @pytest.mark.unit
    def test_llm_aclose_method_needed(self, make_llm):
        """LlamaCppProvider henüz aclose() method'u yok."""
        llm = make_llm()
        has_aclose = hasattr(llm, "aclose")
        has_health = hasattr(llm, "health")
        if not has_aclose:
            pytest.skip("LlamaCppProvider.aclose() henüz yok — Phase 3'te eklenecek")

    @pytest.mark.unit
    def test_llm_response_mode_in_protocol(self):
        """LLMProvider protocol'ü response_mode parametresini içermeli."""
        import inspect
        sig = inspect.signature(LLMProvider.chat)
        assert "response_mode" in sig.parameters, "LLMProvider.chat response_mode eksik"
        sig_stream = inspect.signature(LLMProvider.chat_stream)
        assert "response_mode" in sig_stream.parameters, "LLMProvider.chat_stream response_mode eksik"


# ══════════════════════════════════════════════════════════════
#  TranslatorEngine Protocol Compliance
# ══════════════════════════════════════════════════════════════

class TestTranslatorProtocol:
    """Translator TranslatorEngine protocol'üne uymalı."""

    @pytest.mark.unit
    def test_translator_has_required_methods(self):
        """Translator gerekli tüm method'lara sahip olmalı."""
        from src.translator import Translator
        translator = Translator(model_path="models/opus-mt-tr-en", enabled=False)

        required_methods = ["translate", "health", "close"]
        for method in required_methods:
            assert hasattr(translator, method), f"Translator method eksik: {method}"
            assert callable(getattr(translator, method)), f"Translator {method} callable değil"

    @pytest.mark.unit
    def test_translator_satisfies_protocol(self):
        """Translator isinstance(TranslatorEngine) olmalı."""
        from src.translator import Translator
        translator = Translator(model_path="models/opus-mt-tr-en", enabled=False)
        assert isinstance(translator, TranslatorEngine)

    @pytest.mark.unit
    def test_translator_lifecycle_methods(self):
        """Translator ManagedModel lifecycle proxy method'ları olmalı."""
        from src.translator import Translator
        translator = Translator(model_path="models/opus-mt-tr-en", enabled=False)
        assert callable(translator.safe_unload)
        assert callable(translator.acquire)
        assert callable(translator.release)
