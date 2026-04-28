"""
VoxDesk — Speech-to-Text Module
faster-whisper ile Türkçe+İngilizce ses tanıma.
Push-to-talk, toggle continuous, voice activation destekli.
ManagedModel lifecycle entegrasyonu ile güvenli VRAM yönetimi.
"""

from __future__ import annotations

import logging
import queue
import numpy as np

from src.model_state import ManagedModel

logger = logging.getLogger("voxdesk.stt")

# Ses yakalama sabitleri
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


class SpeechRecognizer:
    """
    faster-whisper ile lokal ses tanıma.
    3 mod: push-to-talk, toggle continuous, voice activation.
    ManagedModel lifecycle ile VRAM-safe.
    """

    def __init__(
        self,
        model_name: str = "large-v3-turbo",
        model_path: str | None = None,
        device: str = "cuda",
        compute_type: str = "float16",
        language: str | None = None,
        vad_enabled: bool = True,
        activation_threshold_db: float = -30.0,
        initial_prompt: str | None = None,
        min_loaded_seconds: float = 30.0,
        unload_cooldown_seconds: float = 10.0,
        keep_warm: bool = False,
    ):
        self.model_name = model_name
        self.model_path = model_path  # Local CTranslate2 path (overrides hub)
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.vad_enabled = vad_enabled
        self.activation_threshold_db = activation_threshold_db
        self.initial_prompt = initial_prompt  # Domain vocabulary for Whisper

        self._model = None
        self._audio_queue: queue.Queue = queue.Queue()
        self._is_listening = False
        self._stream = None

        # Lifecycle — ManagedModel composition
        self._lifecycle = _STTLifecycle(
            owner=self,
            name="stt",
            min_loaded_seconds=min_loaded_seconds,
            unload_cooldown_seconds=unload_cooldown_seconds,
            keep_warm=keep_warm,
        )

    def transcribe_audio(self, audio_data: np.ndarray) -> dict:
        """
        Ses verisini metne çevir.

        Args:
            audio_data: float32 numpy array, 16kHz mono

        Returns:
            dict: {"text": str, "language": str, "segments": list}
        """
        # Ref count guard — aktif transcribe sırasında unload engellensin
        if not self._lifecycle.acquire():
            logger.error("STT model hazır değil — transcribe iptal")
            return {"text": "", "language": "error", "segments": []}

        try:
            segments, info = self._model.transcribe(
                audio_data,
                language=self.language,  # None = auto-detect
                vad_filter=self.vad_enabled,
                initial_prompt=self.initial_prompt,  # Domain vocabulary
                vad_parameters=dict(
                    min_silence_duration_ms=500,
                    speech_pad_ms=200,
                ),
            )

            text_parts = []
            segment_list = []
            for segment in segments:
                text_parts.append(segment.text)
                segment_list.append({
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                })

            full_text = " ".join(text_parts).strip()
            detected_lang = info.language if info else "unknown"

            logger.info(f"🎤 STT: [{detected_lang}] {full_text[:80]}...")

            return {
                "text": full_text,
                "language": detected_lang,
                "segments": segment_list,
            }

        except Exception as e:
            logger.error(f"Transcribe hatası: {e}")
            return {"text": "", "language": "error", "segments": []}
        finally:
            self._lifecycle.release()

    def _audio_callback(self, indata, frames, time_info, status):
        """sounddevice stream callback — ses verisini kuyruğa ekle."""
        if status:
            logger.warning(f"Ses stream durumu: {status}")
        self._audio_queue.put(indata.copy())

    def start_listening(self):
        """Mikrofonu aç ve dinlemeye başla."""
        if self._is_listening:
            return

        try:
            import sounddevice as sd

            self._is_listening = True
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                callback=self._audio_callback,
                blocksize=int(SAMPLE_RATE * 0.5),  # 500ms bloklar
            )
            self._stream.start()
            logger.info("🎤 Mikrofon dinleme başladı")
        except Exception as e:
            logger.error(f"Mikrofon başlatılamadı: {e}")
            self._is_listening = False

    def stop_listening(self) -> np.ndarray | None:
        """
        Dinlemeyi durdur ve toplanan ses verisini döndür.
        Returns None if no audio was captured.
        """
        if not self._is_listening:
            return None

        self._is_listening = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        # Kuyruktaki tüm ses verilerini birleştir
        chunks = []
        while not self._audio_queue.empty():
            try:
                chunks.append(self._audio_queue.get_nowait())
            except queue.Empty:
                break

        if not chunks:
            return None

        audio_data = np.concatenate(chunks, axis=0).flatten()
        logger.info(f"🎤 Ses yakalandı: {len(audio_data) / SAMPLE_RATE:.1f} saniye")
        return audio_data

    def listen_and_transcribe(self) -> dict:
        """Dinlemeyi durdur, ses verisini çevir ve sonucu döndür."""
        audio_data = self.stop_listening()
        if audio_data is None or len(audio_data) < SAMPLE_RATE * 0.3:
            return {"text": "", "language": "none", "segments": []}
        return self.transcribe_audio(audio_data)

    def check_voice_activation(self, audio_chunk: np.ndarray) -> bool:
        """Ses seviyesi eşiğin üstünde mi kontrol et."""
        if len(audio_chunk) == 0:
            return False
        rms = np.sqrt(np.mean(audio_chunk ** 2))
        db = 20 * np.log10(max(rms, 1e-10))
        return db > self.activation_threshold_db

    def set_initial_prompt(self, prompt: str | None) -> None:
        """Domain vocabulary'yi güncelle — personality değişiminde çağrılır."""
        self.initial_prompt = prompt or None
        logger.info(f"STT initial_prompt güncellendi: {str(self.initial_prompt)[:80]}")

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    # ── Lifecycle Methods (ManagedModel proxy) ───────────────

    def safe_unload(self) -> bool:
        """Model VRAM'den güvenli şekilde kaldır."""
        return self._lifecycle.safe_unload()

    def close(self) -> None:
        """Shutdown cleanup — model + stream + queue."""
        self.stop_listening()
        self._lifecycle.close()

    def health(self) -> dict:
        """Engine durum raporu."""
        h = self._lifecycle.health()
        h["is_listening"] = self._is_listening
        return h

    def acquire(self) -> bool:
        """Ref count artır — aktif kullanım başlıyor."""
        return self._lifecycle.acquire()

    def release(self) -> None:
        """Ref count azalt — aktif kullanım bitti."""
        self._lifecycle.release()


# ── Internal ManagedModel subclass ───────────────────────────

class _STTLifecycle(ManagedModel):
    """SpeechRecognizer'ın model lifecycle yöneticisi."""

    def __init__(self, owner: SpeechRecognizer, **kwargs):
        super().__init__(**kwargs)
        self._owner = owner

    def _do_load(self):
        """Whisper modelini yükle (lokal dosyadan veya hub'dan)."""
        from faster_whisper import WhisperModel

        # Local path varsa onu kullan, yoksa hub model adı
        model_id = self._owner.model_path or self._owner.model_name

        model = WhisperModel(
            model_id,
            device=self._owner.device,
            compute_type=self._owner.compute_type,
            local_files_only=True,
        )
        self._owner._model = model
        logger.info(
            f"✅ Whisper modeli yüklendi: "
            f"{model_id} ({self._owner.device})"
        )
        return model

    def _do_unload(self):
        """Whisper modelini ve VRAM'i serbest bırak."""
        self._owner._model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info(f"🗑️ Whisper modeli unload edildi")
