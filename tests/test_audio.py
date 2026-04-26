"""
VoxDesk — STT & TTS Module Tests
Ses işleme mantığı, threshold, voice profil yönetimi.
Gerçek model yüklenmez — sadece logic test edilir.
"""

import pytest
import numpy as np

from src.stt import SpeechRecognizer, SAMPLE_RATE
from src.tts import VoiceSynth, VOICE_PROFILES


# ══════════════════════════════════════════════════════════════
#  STT Tests
# ══════════════════════════════════════════════════════════════

class TestSpeechRecognizerInit:
    """STT başlangıç parametreleri doğru mu?"""

    def test_default_params(self):
        stt = SpeechRecognizer()
        assert stt.model_name == "large-v3-turbo"
        assert stt.device == "cuda"
        assert stt.compute_type == "float16"
        assert stt.language is None
        assert stt.vad_enabled is True
        assert stt.activation_threshold_db == -30.0

    def test_custom_params(self):
        stt = SpeechRecognizer(
            model_name="base",
            device="cpu",
            compute_type="int8",
            language="tr",
            vad_enabled=False,
            activation_threshold_db=-25.0,
        )
        assert stt.model_name == "base"
        assert stt.device == "cpu"
        assert stt.compute_type == "int8"
        assert stt.language == "tr"
        assert stt.vad_enabled is False
        assert stt.activation_threshold_db == -25.0

    def test_model_not_loaded_on_init(self):
        """Model init'te yüklenmemeli — lazy loading."""
        stt = SpeechRecognizer()
        assert stt._model is None

    def test_not_listening_on_init(self):
        stt = SpeechRecognizer()
        assert stt.is_listening is False

    def test_audio_queue_empty_on_init(self):
        stt = SpeechRecognizer()
        assert stt._audio_queue.empty()

    def test_stream_none_on_init(self):
        stt = SpeechRecognizer()
        assert stt._stream is None


class TestVoiceActivation:
    """Ses seviyesi eşik kontrolü — dB hesaplama doğruluğu."""

    def test_silence_below_threshold(self):
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        # 1e-4 RMS → 20*log10(1e-4) = -80dB → -30'un çok altında
        silent = np.zeros(1600, dtype=np.float32) + 1e-4
        assert stt.check_voice_activation(silent) == False

    def test_loud_above_threshold(self):
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        # 0.5 RMS → 20*log10(0.5) ≈ -6dB → -30'un üstünde
        loud = np.ones(1600, dtype=np.float32) * 0.5
        assert stt.check_voice_activation(loud) == True

    def test_empty_audio_returns_false(self):
        stt = SpeechRecognizer()
        empty = np.array([], dtype=np.float32)
        assert stt.check_voice_activation(empty) is False

    def test_threshold_edge_case(self):
        """Tam eşikte — crash olmamalı."""
        stt = SpeechRecognizer(activation_threshold_db=-20.0)
        # 0.1 RMS → 20*log10(0.1) = -20dB
        edge_audio = np.ones(1600, dtype=np.float32) * 0.1
        result = stt.check_voice_activation(edge_audio)
        assert result == True or result == False

    def test_very_different_thresholds(self):
        """Farklı threshold'larda aynı ses farklı sonuç vermeli."""
        audio = np.ones(1600, dtype=np.float32) * 0.05  # ~-26dB
        strict = SpeechRecognizer(activation_threshold_db=-20.0)
        lenient = SpeechRecognizer(activation_threshold_db=-40.0)
        assert strict.check_voice_activation(audio) == False
        assert lenient.check_voice_activation(audio) == True

    def test_single_sample_audio(self):
        """Tek sample ile crash olmamalı."""
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        single = np.array([0.5], dtype=np.float32)
        result = stt.check_voice_activation(single)
        assert result == True or result == False


class TestSTTListening:
    """Listening state yönetimi."""

    def test_stop_listening_when_not_listening(self):
        """Dinlemiyorken stop → None döndürmeli."""
        stt = SpeechRecognizer()
        result = stt.stop_listening()
        assert result is None

    def test_stop_listening_double_call(self):
        """İki kez stop → ikisi de None, crash yok."""
        stt = SpeechRecognizer()
        assert stt.stop_listening() is None
        assert stt.stop_listening() is None

    def test_listen_and_transcribe_no_audio(self):
        """Ses yokken transcribe → boş result."""
        stt = SpeechRecognizer()
        result = stt.listen_and_transcribe()
        assert result["text"] == ""
        assert result["language"] == "none"
        assert result["segments"] == []


# ══════════════════════════════════════════════════════════════
#  TTS Tests
# ══════════════════════════════════════════════════════════════

class TestVoiceSynthInit:
    """TTS başlangıç parametreleri."""

    def test_default_params(self):
        tts = VoiceSynth()
        assert tts.voice == "af_heart"
        assert tts.speed == 1.0
        assert tts.lang_code == "a"
        assert tts.enabled is True
        assert tts.sample_rate == 24000

    def test_custom_params(self):
        tts = VoiceSynth(voice="am_adam", speed=1.5, lang_code="b", enabled=False)
        assert tts.voice == "am_adam"
        assert tts.speed == 1.5
        assert tts.lang_code == "b"
        assert tts.enabled is False

    def test_pipeline_not_loaded_on_init(self):
        """Pipeline init'te yüklenmemeli — lazy loading."""
        tts = VoiceSynth()
        assert tts._pipeline is None


class TestVoiceProfiles:
    """Ses profil kataloğu doğru mu?"""

    def test_all_categories_exist(self):
        voices = VoiceSynth.get_available_voices()
        assert "American Female" in voices
        assert "American Male" in voices
        assert "British Female" in voices
        assert "British Male" in voices

    def test_af_heart_exists(self):
        voices = VoiceSynth.get_available_voices()
        assert "af_heart" in voices["American Female"]

    def test_all_voices_have_correct_prefix(self):
        """Her voice kendi kategorisi prefix'iyle başlamalı."""
        voices = VoiceSynth.get_available_voices()
        prefix_map = {
            "American Female": "af_",
            "American Male": "am_",
            "British Female": "bf_",
            "British Male": "bm_",
        }
        for category, prefix in prefix_map.items():
            for voice in voices[category]:
                assert voice.startswith(prefix), \
                    f"{voice} should start with {prefix}"

    def test_no_duplicate_voices(self):
        """Tüm voice'lar unique olmalı."""
        voices = VoiceSynth.get_available_voices()
        all_voices = []
        for v_list in voices.values():
            all_voices.extend(v_list)
        assert len(all_voices) == len(set(all_voices))

    def test_voice_count(self):
        """En az 27 ses profili olmalı."""
        voices = VoiceSynth.get_available_voices()
        total = sum(len(v) for v in voices.values())
        assert total >= 27

    def test_get_voices_returns_copy(self):
        """Farklı dict nesneleri döndürmeli."""
        v1 = VoiceSynth.get_available_voices()
        v2 = VoiceSynth.get_available_voices()
        assert v1 is not v2

    def test_constant_matches_static_method(self):
        """VOICE_PROFILES sabiti ile method aynı datayı döndürmeli."""
        from_method = VoiceSynth.get_available_voices()
        assert from_method == VOICE_PROFILES


class TestVoiceSynthSettings:
    """Ses ayarları runtime'da değiştirilebilmeli."""

    def test_set_voice(self):
        tts = VoiceSynth()
        tts.set_voice("am_adam")
        assert tts.voice == "am_adam"

    def test_set_speed_normal(self):
        tts = VoiceSynth()
        tts.set_speed(1.5)
        assert tts.speed == 1.5

    def test_set_speed_boundary_min(self):
        """Tam 0.5 kabul edilmeli."""
        tts = VoiceSynth()
        tts.set_speed(0.5)
        assert tts.speed == 0.5

    def test_set_speed_boundary_max(self):
        """Tam 2.0 kabul edilmeli."""
        tts = VoiceSynth()
        tts.set_speed(2.0)
        assert tts.speed == 2.0

    def test_set_speed_clamped_min(self):
        """0.5'in altına inmemeli."""
        tts = VoiceSynth()
        tts.set_speed(0.1)
        assert tts.speed == 0.5

    def test_set_speed_clamped_max(self):
        """2.0'ın üstüne çıkmamalı."""
        tts = VoiceSynth()
        tts.set_speed(5.0)
        assert tts.speed == 2.0

    def test_set_speed_zero(self):
        """0 → 0.5'e clamp edilmeli."""
        tts = VoiceSynth()
        tts.set_speed(0.0)
        assert tts.speed == 0.5

    def test_set_speed_negative(self):
        """Negatif → 0.5'e clamp edilmeli."""
        tts = VoiceSynth()
        tts.set_speed(-1.0)
        assert tts.speed == 0.5

    def test_set_lang_code_resets_pipeline(self):
        """Dil değişince pipeline sıfırlanmalı."""
        tts = VoiceSynth()
        tts._pipeline = "fake_pipeline"
        tts.set_lang_code("b")
        assert tts.lang_code == "b"
        assert tts._pipeline is None

    def test_synthesize_disabled_returns_none(self):
        """TTS kapalıyken synthesize → None."""
        tts = VoiceSynth(enabled=False)
        result = tts.synthesize("test")
        assert result is None

    def test_synthesize_empty_text_returns_none(self):
        """Boş metin → None."""
        tts = VoiceSynth()
        result = tts.synthesize("   ")
        assert result is None

    def test_synthesize_stream_disabled_returns_empty(self):
        """TTS kapalıyken synthesize_stream → hiç yield etmemeli."""
        tts = VoiceSynth(enabled=False)
        chunks = list(tts.synthesize_stream("test text"))
        assert chunks == []

    def test_synthesize_stream_empty_text_returns_empty(self):
        """Boş metin → hiç yield etmemeli."""
        tts = VoiceSynth()
        chunks = list(tts.synthesize_stream("   "))
        assert chunks == []
