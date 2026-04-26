"""
VoxDesk — Text-to-Speech Module
Kokoro TTS ile İngilizce ses sentezi.
28+ ses profili, ses karıştırma, streaming chunk desteği.
ManagedModel lifecycle entegrasyonu ile güvenli VRAM yönetimi.
"""

from __future__ import annotations

import io
import logging
import numpy as np

from src.model_state import ManagedModel

logger = logging.getLogger("voxdesk.tts")

# Kokoro ses profilleri
VOICE_PROFILES = {
    "American Female": [
        "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
        "af_nova", "af_alloy", "af_aoede", "af_jessica", "af_kore", "af_river",
    ],
    "American Male": [
        "am_adam", "am_michael", "am_echo", "am_eric",
        "am_fenrir", "am_liam", "am_onyx", "am_puck",
    ],
    "British Female": ["bf_emma", "bf_isabella", "bf_alice", "bf_lily"],
    "British Male": ["bm_george", "bm_lewis", "bm_daniel", "bm_fable"],
}


class VoiceSynth:
    """
    Kokoro TTS ile ses sentezi.
    Ses profili seçimi, karıştırma, streaming chunk üretimi.
    ManagedModel lifecycle ile VRAM-safe.
    """

    def __init__(
        self,
        voice: str = "af_heart",
        speed: float = 1.0,
        lang_code: str = "a",
        enabled: bool = True,
        min_loaded_seconds: float = 30.0,
        unload_cooldown_seconds: float = 10.0,
        keep_warm: bool = False,
    ):
        self.voice = voice
        self.speed = speed
        self.lang_code = lang_code
        self.enabled = enabled

        self._pipeline = None
        self._sample_rate = 24000

        # Lifecycle — ManagedModel composition
        self._lifecycle = _TTSLifecycle(
            owner=self,
            name="tts",
            min_loaded_seconds=min_loaded_seconds,
            unload_cooldown_seconds=unload_cooldown_seconds,
            keep_warm=keep_warm,
        )

    def _init_pipeline(self):
        """Kokoro pipeline'ı başlat."""
        if self._pipeline is not None:
            return

        try:
            from kokoro import KPipeline

            self._pipeline = KPipeline(lang_code=self.lang_code)
            logger.info(f"✅ Kokoro TTS başlatıldı — ses: {self.voice}, lang: {self.lang_code}")
        except Exception as e:
            logger.error(f"❌ Kokoro TTS başlatılamadı: {e}")
            raise

    def synthesize(self, text: str) -> bytes | None:
        """
        Metni sese çevir ve WAV bytes olarak döndür.

        Args:
            text: Sentezlenecek metin

        Returns:
            WAV format audio bytes veya None
        """
        if not self.enabled or not text.strip():
            return None

        # Ref count guard
        if not self._lifecycle.acquire():
            logger.error("TTS model hazır değil — sentez iptal")
            return None

        try:
            import soundfile as sf

            audio_chunks = []
            for _gs, _ps, audio in self._pipeline(
                text, voice=self.voice, speed=self.speed
            ):
                if audio is not None:
                    audio_chunks.append(audio)

            if not audio_chunks:
                return None

            # Tüm chunk'ları birleştir
            full_audio = np.concatenate(audio_chunks)

            # WAV formatına çevir (bellekte)
            buffer = io.BytesIO()
            sf.write(buffer, full_audio, self._sample_rate, format="WAV")
            return buffer.getvalue()

        except Exception as e:
            logger.error(f"TTS sentez hatası: {e}")
            return None
        finally:
            self._lifecycle.release()

    def synthesize_stream(self, text: str):
        """
        Streaming ses sentezi — chunk chunk yield et.
        Düşük latency için ilk chunk hemen gönderilir.

        Yields:
            numpy array audio chunks
        """
        if not self.enabled or not text.strip():
            return

        # Ref count guard
        if not self._lifecycle.acquire():
            logger.error("TTS model hazır değil — stream iptal")
            return

        try:
            for _gs, _ps, audio in self._pipeline(
                text, voice=self.voice, speed=self.speed
            ):
                if audio is not None:
                    yield audio
        except Exception as e:
            logger.error(f"TTS stream hatası: {e}")
        finally:
            self._lifecycle.release()

    def set_voice(self, voice: str) -> None:
        """Ses profilini değiştir."""
        self.voice = voice
        logger.info(f"Ses profili değiştirildi: {voice}")

    def set_speed(self, speed: float) -> None:
        """Ses hızını değiştir."""
        self.speed = max(0.5, min(2.0, speed))
        logger.info(f"Ses hızı: {self.speed}")

    def set_lang_code(self, lang_code: str) -> None:
        """Dil kodunu değiştir (pipeline yeniden oluşturulur)."""
        self.lang_code = lang_code
        self._pipeline = None  # Yeniden başlat
        self._lifecycle.close()  # Lifecycle da sıfırla
        logger.info(f"TTS dil kodu: {lang_code}")

    @staticmethod
    def get_available_voices() -> dict[str, list[str]]:
        """Tüm mevcut ses profillerini döndür."""
        return VOICE_PROFILES.copy()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    # ── Lifecycle Methods (ManagedModel proxy) ───────────────

    def safe_unload(self) -> bool:
        """Pipeline VRAM'den güvenli şekilde kaldır."""
        return self._lifecycle.safe_unload()

    def close(self) -> None:
        """Shutdown cleanup — pipeline + cache."""
        self._lifecycle.close()

    def health(self) -> dict:
        """Engine durum raporu."""
        h = self._lifecycle.health()
        h["enabled"] = self.enabled
        h["voice"] = self.voice
        return h

    def acquire(self) -> bool:
        """Ref count artır — aktif kullanım başlıyor."""
        return self._lifecycle.acquire()

    def release(self) -> None:
        """Ref count azalt — aktif kullanım bitti."""
        self._lifecycle.release()


# ── Internal ManagedModel subclass ───────────────────────────

class _TTSLifecycle(ManagedModel):
    """VoiceSynth'ın model lifecycle yöneticisi."""

    def __init__(self, owner: VoiceSynth, **kwargs):
        super().__init__(**kwargs)
        self._owner = owner

    def _do_load(self):
        """Kokoro pipeline'ı başlat."""
        from kokoro import KPipeline

        pipeline = KPipeline(lang_code=self._owner.lang_code)
        self._owner._pipeline = pipeline
        logger.info(
            f"✅ Kokoro TTS başlatıldı — "
            f"ses: {self._owner.voice}, lang: {self._owner.lang_code}"
        )
        return pipeline

    def _do_unload(self):
        """Kokoro pipeline'ı serbest bırak."""
        self._owner._pipeline = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info(f"🗑️ Kokoro TTS unload edildi")
