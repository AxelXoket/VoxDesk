"""
VoxDesk — Audio Decode Utilities
WebM/Opus ve raw PCM decode fonksiyonları.
chat.py ve voice_v2.py tarafından paylaşılır.

Sprint 3: cross-import kırılganlığını gidermek için extract edildi.
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("voxdesk.audio_utils")


def decode_audio_webm(audio_bytes: bytes) -> "np.ndarray | None":
    """
    WebM/Opus audio'yu float32 16kHz PCM numpy array'e dönüştür.
    PyAV (libavcodec) kullanır — ffmpeg CLI çağırmaz.
    """
    import numpy as np

    try:
        import av

        # BytesIO ile in-memory decode
        container = av.open(io.BytesIO(audio_bytes))
        audio_stream = container.streams.audio[0]

        # 16kHz mono s16 PCM olarak resample
        resampler = av.audio.resampler.AudioResampler(
            format='s16',
            layout='mono',
            rate=16000,
        )

        frames = []
        for frame in container.decode(audio_stream):
            resampled = resampler.resample(frame)
            for rf in resampled:
                arr = rf.to_ndarray()
                frames.append(arr)

        container.close()

        if not frames:
            return None

        # s16 -> float32 normalize (-1.0 ~ 1.0)
        audio_data = np.concatenate(frames, axis=1).flatten()
        return audio_data.astype(np.float32) / 32768.0

    except ImportError:
        logger.error("PyAV yüklü değil! pip install av")
        return None
    except Exception as e:
        logger.error(f"Audio decode hatası: {e}")
        return None


def decode_audio_raw_pcm(audio_bytes: bytes) -> "np.ndarray | None":
    """
    Raw PCM S16LE data → float32 numpy array.
    AudioWorklet (audio-processor.js) Int16 PCM gönderir.
    int16 → float32 normalize (-1.0 ~ 1.0) yapılır.
    """
    import numpy as np
    try:
        pcm_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
        return pcm_int16.astype(np.float32) / 32768.0
    except Exception:
        return None
