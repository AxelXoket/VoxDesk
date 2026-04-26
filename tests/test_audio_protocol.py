"""
VoxDesk — Audio Binary Protocol Tests
Protocol constants, validation, handshake, session state.
Gerçek mikrofon/audio KULLANILMAZ — pure unit tests.
"""

import json
import pytest
import numpy as np

from src.audio_protocol import (
    PROTOCOL_VERSION,
    ENCODING,
    SAMPLE_RATE,
    CHANNELS,
    CHUNK_MS,
    BYTES_PER_SAMPLE,
    SAMPLES_PER_CHUNK,
    BYTES_PER_CHUNK,
    MAX_FRAME_BYTES,
    MAX_BASE64_BYTES,
    MIN_FRAME_BYTES,
    AudioMessageType,
    AudioConfig,
    AudioSession,
    validate_config,
    validate_binary_frame,
    decode_pcm_s16le,
    build_config_ack,
    build_protocol_error,
)


# ══════════════════════════════════════════════════════════════
#  Protocol Constants
# ══════════════════════════════════════════════════════════════

class TestProtocolConstants:
    """Protocol sabitleri doğru olmalı."""

    @pytest.mark.unit
    def test_protocol_version(self):
        assert PROTOCOL_VERSION == 1

    @pytest.mark.unit
    def test_encoding(self):
        assert ENCODING == "pcm_s16le"

    @pytest.mark.unit
    def test_sample_rate(self):
        assert SAMPLE_RATE == 16000

    @pytest.mark.unit
    def test_channels(self):
        assert CHANNELS == 1

    @pytest.mark.unit
    def test_chunk_ms(self):
        assert CHUNK_MS == 20

    @pytest.mark.unit
    def test_derived_constants(self):
        """Derived sabitleri doğru hesaplanmalı."""
        assert SAMPLES_PER_CHUNK == 320  # 16000 * 20 / 1000
        assert BYTES_PER_CHUNK == 640    # 320 * 2

    @pytest.mark.unit
    def test_limits(self):
        assert MAX_FRAME_BYTES == 64 * 1024
        assert MAX_BASE64_BYTES == 256 * 1024
        assert MIN_FRAME_BYTES == 2


# ══════════════════════════════════════════════════════════════
#  Config Validation
# ══════════════════════════════════════════════════════════════

class TestConfigValidation:
    """audio_config handshake validation."""

    @pytest.mark.unit
    def test_valid_config(self):
        """Geçerli config kabul edilmeli."""
        data = {
            "type": "audio_config",
            "protocol_version": 1,
            "encoding": "pcm_s16le",
            "sample_rate": 16000,
            "channels": 1,
            "chunk_ms": 20,
        }
        config, err = validate_config(data)
        assert err is None
        assert config is not None
        assert config.protocol_version == 1
        assert config.encoding == "pcm_s16le"
        assert config.sample_rate == 16000

    @pytest.mark.unit
    def test_invalid_protocol_version(self):
        """Desteklenmeyen protocol_version reddedilmeli."""
        data = {"protocol_version": 99}
        config, err = validate_config(data)
        assert config is None
        assert "protocol_version" in err

    @pytest.mark.unit
    def test_unsupported_encoding(self):
        """Desteklenmeyen encoding reddedilmeli."""
        data = {"protocol_version": 1, "encoding": "opus"}
        config, err = validate_config(data)
        assert config is None
        assert "encoding" in err

    @pytest.mark.unit
    def test_invalid_sample_rate(self):
        """Geçersiz sample_rate reddedilmeli."""
        data = {"protocol_version": 1, "sample_rate": 22050}
        config, err = validate_config(data)
        assert config is None
        assert "sample_rate" in err

    @pytest.mark.unit
    def test_stereo_rejected(self):
        """Stereo (channels=2) reddedilmeli."""
        data = {"protocol_version": 1, "channels": 2}
        config, err = validate_config(data)
        assert config is None
        assert "mono" in err.lower() or "channels" in err

    @pytest.mark.unit
    def test_missing_protocol_version(self):
        """protocol_version eksikse reddedilmeli."""
        data = {"encoding": "pcm_s16le"}
        config, err = validate_config(data)
        assert config is None
        assert "protocol_version" in err


# ══════════════════════════════════════════════════════════════
#  Binary Frame Validation
# ══════════════════════════════════════════════════════════════

class TestBinaryFrameValidation:
    """Binary PCM frame doğrulaması."""

    @pytest.mark.unit
    def test_valid_frame(self):
        """640 bytes (1 chunk) geçerli olmalı."""
        data = b"\x00" * BYTES_PER_CHUNK
        valid, err = validate_binary_frame(data)
        assert valid is True
        assert err is None

    @pytest.mark.unit
    def test_odd_byte_count_rejected(self):
        """Tek byte sayısı reddedilmeli (16-bit alignment)."""
        data = b"\x00" * 641  # Odd
        valid, err = validate_binary_frame(data)
        assert valid is False
        assert "alignment" in err.lower() or "tek" in err.lower()

    @pytest.mark.unit
    def test_oversized_frame_rejected(self):
        """MAX_FRAME_BYTES'dan büyük frame reddedilmeli."""
        data = b"\x00" * (MAX_FRAME_BYTES + 2)
        valid, err = validate_binary_frame(data)
        assert valid is False
        assert "büyük" in err.lower() or "large" in err.lower()

    @pytest.mark.unit
    def test_empty_frame_rejected(self):
        """Boş frame reddedilmeli."""
        valid, err = validate_binary_frame(b"")
        assert valid is False

    @pytest.mark.unit
    def test_single_byte_rejected(self):
        """1 byte frame reddedilmeli."""
        valid, err = validate_binary_frame(b"\x00")
        assert valid is False

    @pytest.mark.unit
    def test_minimum_valid_frame(self):
        """2 bytes (1 sample) geçerli olmalı."""
        data = b"\x00\x00"
        valid, err = validate_binary_frame(data)
        assert valid is True

    @pytest.mark.unit
    def test_max_valid_frame(self):
        """MAX_FRAME_BYTES tam sınırda geçerli olmalı."""
        data = b"\x00" * MAX_FRAME_BYTES
        valid, err = validate_binary_frame(data)
        assert valid is True


# ══════════════════════════════════════════════════════════════
#  PCM Decode
# ══════════════════════════════════════════════════════════════

class TestPCMDecode:
    """PCM S16LE → float32 decode."""

    @pytest.mark.unit
    def test_silence_decodes_to_zero(self):
        """Sessizlik (all zeros) float32 sıfır olmalı."""
        data = b"\x00" * BYTES_PER_CHUNK
        audio = decode_pcm_s16le(data)
        assert audio.dtype == np.float32
        assert len(audio) == SAMPLES_PER_CHUNK
        assert np.all(audio == 0.0)

    @pytest.mark.unit
    def test_max_positive_sample(self):
        """0x7FFF → ~0.99997 olmalı."""
        data = b"\xFF\x7F"  # 32767 little-endian
        audio = decode_pcm_s16le(data)
        assert len(audio) == 1
        assert abs(audio[0] - (32767 / 32768.0)) < 1e-5

    @pytest.mark.unit
    def test_max_negative_sample(self):
        """0x8000 → -1.0 olmalı."""
        data = b"\x00\x80"  # -32768 little-endian
        audio = decode_pcm_s16le(data)
        assert len(audio) == 1
        assert abs(audio[0] - (-1.0)) < 1e-5

    @pytest.mark.unit
    def test_output_range(self):
        """Decode output [-1.0, ~1.0] aralığında olmalı."""
        # Random 16-bit samples
        rng = np.random.RandomState(42)
        samples = rng.randint(-32768, 32767, size=1000, dtype=np.int16)
        data = samples.tobytes()
        audio = decode_pcm_s16le(data)
        assert audio.min() >= -1.0
        assert audio.max() <= 1.0


# ══════════════════════════════════════════════════════════════
#  Response Builders
# ══════════════════════════════════════════════════════════════

class TestResponseBuilders:
    """Config ACK ve protocol error response'ları."""

    @pytest.mark.unit
    def test_config_ack(self):
        """audio_config_ack doğru formatta olmalı."""
        config = AudioConfig()
        ack = build_config_ack(config)
        assert ack["type"] == "audio_config_ack"
        assert ack["accepted"] is True
        assert ack["protocol_version"] == 1

    @pytest.mark.unit
    def test_protocol_error(self):
        """protocol_error doğru formatta olmalı."""
        err = build_protocol_error("test error")
        assert err["type"] == "protocol_error"
        assert err["error"] == "test error"
        assert err["code"] == "protocol_error"

    @pytest.mark.unit
    def test_protocol_error_custom_code(self):
        """protocol_error custom code desteklemeli."""
        err = build_protocol_error("bad frame", code="invalid_frame")
        assert err["code"] == "invalid_frame"


# ══════════════════════════════════════════════════════════════
#  Audio Session State
# ══════════════════════════════════════════════════════════════

class TestAudioSession:
    """Per-connection session state yönetimi."""

    @pytest.mark.unit
    def test_initial_state(self):
        """Yeni session handshake yapılmamış olmalı."""
        session = AudioSession()
        assert session.handshake_done is False
        assert session.config is None
        assert session.sequence == 0

    @pytest.mark.unit
    def test_accept_handshake(self):
        """Handshake sonrası state doğru olmalı."""
        session = AudioSession()
        config = AudioConfig()
        session.accept_handshake(config)
        assert session.handshake_done is True
        assert session.config is config
        assert session.sequence == 0

    @pytest.mark.unit
    def test_record_chunk_increments_sequence(self):
        """record_chunk sequence artırmalı."""
        session = AudioSession()
        session.accept_handshake(AudioConfig())

        seq = session.record_chunk(640)
        assert seq == 1
        assert session.total_bytes == 640
        assert session.total_chunks == 1

        seq = session.record_chunk(640)
        assert seq == 2
        assert session.total_bytes == 1280
        assert session.total_chunks == 2

    @pytest.mark.unit
    def test_reset_clears_counters(self):
        """reset sequence ve counter'ları sıfırlamalı."""
        session = AudioSession()
        session.accept_handshake(AudioConfig())
        session.record_chunk(640)
        session.record_chunk(640)

        session.reset()
        assert session.sequence == 0
        assert session.total_bytes == 0
        assert session.total_chunks == 0
        # handshake_done korunur — session devam eder

    @pytest.mark.unit
    def test_binary_before_handshake_detectable(self):
        """Handshake öncesi binary tespit edilebilir olmalı."""
        session = AudioSession()
        assert session.handshake_done is False
        # Handler bu durumda binary reject edecek
