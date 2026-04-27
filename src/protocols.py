"""
VoxDesk — Engine Protocols
Structural typing contracts for all pluggable engine backends.
Implementations satisfy these protocols implicitly (duck typing).

Protocol'ler mevcut engine class'larından türetilmiştir:
  - SpeechRecognizer → STTEngine
  - VoiceSynth → TTSEngine
  - LlamaCppProvider → LLMProvider
  - ScreenCapture → CaptureBackend

Her Protocol'de:
  - Core methods (engine'in asıl işi)
  - health() — monitoring için durum raporu
  - close() / aclose() — resource cleanup
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Iterator, Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class STTEngine(Protocol):
    """Speech-to-Text engine contract."""

    def transcribe_audio(self, audio_data: np.ndarray) -> dict:
        """
        Ses verisini metne çevir.
        Input: float32 numpy array, 16kHz mono
        Returns: {"text": str, "language": str, "segments": list}
        """
        ...

    def check_voice_activation(self, audio_chunk: np.ndarray) -> bool:
        """Ses seviyesi aktivasyon eşiğinin üstünde mi?"""
        ...

    def health(self) -> dict:
        """Engine durum raporu."""
        ...

    def close(self) -> None:
        """Kaynakları serbest bırak (model, stream, buffer)."""
        ...

    @property
    def is_listening(self) -> bool:
        """Mikrofon aktif olarak dinleniyor mu?"""
        ...


@runtime_checkable
class TTSEngine(Protocol):
    """Text-to-Speech engine contract."""

    def synthesize(self, text: str) -> bytes | None:
        """Metni WAV formatında ses verisine çevir."""
        ...

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        """
        Streaming sentez — chunk chunk numpy array yield et.
        Her chunk raw PCM float32 audio.
        """
        ...

    def set_voice(self, voice: str) -> None:
        """Ses profilini değiştir."""
        ...

    def health(self) -> dict:
        """Engine durum raporu."""
        ...

    def close(self) -> None:
        """Pipeline ve cache kaynakları serbest bırak."""
        ...

    @property
    def sample_rate(self) -> int:
        """Output sample rate (Hz)."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """LLM chat provider contract."""

    async def chat(
        self,
        message: str,
        image_bytes: bytes | None = None,
    ) -> str:
        """Async tek-seferlik chat yanıtı."""
        ...

    async def chat_stream(
        self,
        message: str,
        image_bytes: bytes | None = None,
    ) -> AsyncGenerator[str, None]:
        """Async streaming chat — token token yield."""
        ...

    def get_history(self) -> list:
        """Konuşma geçmişini döndür."""
        ...

    def clear_history(self) -> None:
        """Konuşma geçmişini temizle."""
        ...

    def health(self) -> dict:
        """Provider durum raporu."""
        ...

    async def aclose(self) -> None:
        """Async resource cleanup (HTTP client, connection pool)."""
        ...


@runtime_checkable
class CaptureBackend(Protocol):
    """Screen capture backend contract."""

    def start(self) -> None:
        """Yakalama döngüsünü başlat."""
        ...

    def stop(self) -> None:
        """Yakalama döngüsünü durdur."""
        ...

    def get_latest_frame(self) -> Any | None:
        """En son yakalanan frame'i döndür. None = henüz frame yok."""
        ...

    def health(self) -> dict:
        """Backend durum raporu."""
        ...

    def close(self) -> None:
        """Kamera ve thread kaynaklarını serbest bırak."""
        ...

    @property
    def is_running(self) -> bool:
        """Yakalama döngüsü aktif mi?"""
        ...
