"""
VoxDesk — Audio Binary Protocol v1
WebSocket üzerinden PCM audio transfer protokolü.

v1 özellikleri:
- Encoding: pcm_s16le (signed 16-bit little-endian)
- Sample rate: 16000 Hz
- Channels: 1 (mono)
- Chunk duration: 20ms (320 samples = 640 bytes)
- Server-side sequence counter (client timestamp yok)
- Protocol version: 1

Güvenlik:
- max_frame_bytes ile oversized frame koruması
- even byte count doğrulaması (16-bit alignment)
- handshake zorunlu — binary before handshake reject
- Tüm iletişim localhost — dış domain yok
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np

logger = logging.getLogger("voxdesk.audio_protocol")


# ══════════════════════════════════════════════════════════════
#  Protocol Constants
# ══════════════════════════════════════════════════════════════

PROTOCOL_VERSION = 1
ENCODING = "pcm_s16le"
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_MS = 20
BYTES_PER_SAMPLE = 2  # 16-bit = 2 bytes

# Derived
SAMPLES_PER_CHUNK = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 320
BYTES_PER_CHUNK = SAMPLES_PER_CHUNK * BYTES_PER_SAMPLE   # 640

# Limits — backed by SecurityConfig (see src/config.py)
def _get_security_config():
    """Lazy config read — avoids import cycle."""
    try:
        from src.config import get_config
        return get_config().security
    except Exception:
        return None

def get_max_frame_bytes() -> int:
    """Max single WS binary frame size."""
    sec = _get_security_config()
    return sec.max_ws_frame_bytes if sec else 64 * 1024

def get_max_json_message_bytes() -> int:
    """Max single WS JSON message size."""
    sec = _get_security_config()
    return sec.max_json_message_bytes if sec else 64 * 1024

MAX_FRAME_BYTES = 64 * 1024      # 64KB — fallback default (config overrides at runtime)
MAX_BASE64_BYTES = 256 * 1024    # 256KB — legacy base64 limit
MIN_FRAME_BYTES = 2              # At least 1 sample


# ══════════════════════════════════════════════════════════════
#  Message Types
# ══════════════════════════════════════════════════════════════

class AudioMessageType(str, Enum):
    """WebSocket text frame message types."""
    AUDIO_CONFIG = "audio_config"
    AUDIO_CONFIG_ACK = "audio_config_ack"
    AUDIO_END = "audio_end"
    AUDIO_CANCEL = "audio_cancel"
    PROTOCOL_ERROR = "protocol_error"


# ══════════════════════════════════════════════════════════════
#  Handshake Config
# ══════════════════════════════════════════════════════════════

@dataclass
class AudioConfig:
    """Client → Server handshake yapılandırması."""
    protocol_version: int = PROTOCOL_VERSION
    encoding: str = ENCODING
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    chunk_ms: int = CHUNK_MS


# ══════════════════════════════════════════════════════════════
#  Validation Functions
# ══════════════════════════════════════════════════════════════

def validate_config(data: dict) -> tuple[AudioConfig | None, str | None]:
    """
    Client audio_config mesajını doğrula.

    Returns:
        (AudioConfig, None) if valid
        (None, error_message) if invalid
    """
    # Protocol version
    version = data.get("protocol_version")
    if version != PROTOCOL_VERSION:
        return None, f"Desteklenmeyen protocol_version: {version} (beklenen: {PROTOCOL_VERSION})"

    # Encoding
    encoding = data.get("encoding", ENCODING)
    if encoding != ENCODING:
        return None, f"Desteklenmeyen encoding: {encoding} (beklenen: {ENCODING})"

    # Sample rate
    sample_rate = data.get("sample_rate", SAMPLE_RATE)
    if not isinstance(sample_rate, int) or sample_rate not in (8000, 16000, 44100, 48000):
        return None, f"Geçersiz sample_rate: {sample_rate}"

    # Channels
    channels = data.get("channels", CHANNELS)
    if channels != 1:
        return None, f"Sadece mono destekleniyor, channels={channels}"

    return AudioConfig(
        protocol_version=version,
        encoding=encoding,
        sample_rate=sample_rate,
        channels=channels,
        chunk_ms=data.get("chunk_ms", CHUNK_MS),
    ), None


def validate_binary_frame(data: bytes) -> tuple[bool, str | None]:
    """
    Binary PCM frame doğrulaması.

    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    if len(data) < MIN_FRAME_BYTES:
        return False, f"Frame çok küçük: {len(data)} bytes (min: {MIN_FRAME_BYTES})"

    if len(data) > get_max_frame_bytes():
        max_bytes = get_max_frame_bytes()
        return False, f"Frame çok büyük: {len(data)} bytes (max: {max_bytes})"

    if len(data) % BYTES_PER_SAMPLE != 0:
        return False, f"Tek byte sayısı: {len(data)} — 16-bit alignment gerekli"

    return True, None


def decode_pcm_s16le(data: bytes) -> np.ndarray:
    """
    PCM S16LE bytes → float32 numpy array.
    Caller must validate_binary_frame first.
    """
    samples = np.frombuffer(data, dtype="<i2")
    return samples.astype(np.float32) / 32768.0


# ══════════════════════════════════════════════════════════════
#  Response Builders
# ══════════════════════════════════════════════════════════════

def build_config_ack(config: AudioConfig) -> dict:
    """audio_config_ack response oluştur."""
    return {
        "type": AudioMessageType.AUDIO_CONFIG_ACK.value,
        "accepted": True,
        "protocol_version": config.protocol_version,
        "encoding": config.encoding,
        "sample_rate": config.sample_rate,
    }


def build_protocol_error(reason: str, code: str = "protocol_error") -> dict:
    """protocol_error response oluştur."""
    return {
        "type": AudioMessageType.PROTOCOL_ERROR.value,
        "error": reason,
        "code": code,
    }


# ══════════════════════════════════════════════════════════════
#  Session State
# ══════════════════════════════════════════════════════════════

@dataclass
class AudioSession:
    """
    Per-connection audio session state.
    WebSocket handler tarafından yönetilir.
    """
    handshake_done: bool = False
    config: AudioConfig | None = None
    sequence: int = 0
    total_bytes: int = 0
    total_chunks: int = 0

    def accept_handshake(self, config: AudioConfig) -> None:
        """Handshake tamamla."""
        self.handshake_done = True
        self.config = config
        self.sequence = 0
        self.total_bytes = 0
        self.total_chunks = 0

    def record_chunk(self, byte_count: int) -> int:
        """Chunk kaydet, sequence döndür."""
        self.sequence += 1
        self.total_bytes += byte_count
        self.total_chunks += 1
        return self.sequence

    def reset(self) -> None:
        """Session sıfırla (audio_cancel)."""
        self.sequence = 0
        self.total_bytes = 0
        self.total_chunks = 0
