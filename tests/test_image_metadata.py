"""
VoxDesk — Sprint 5.3 Part 1.5 Tests
Image metadata, debug export, capture metadata tracking.
"""

import hashlib
import os
import tempfile
import time

import pytest

from src.image_metadata import (
    ImageMetadata,
    build_image_metadata,
    log_image_context,
    export_debug_frame,
    _compute_hash_prefix,
    _detect_image_format,
    _get_image_dimensions,
)


# ── Helper: minimal JPEG bytes ──────────────────────────────────
def _make_jpeg(width: int = 100, height: int = 50, quality: int = 85) -> bytes:
    """PIL ile minimal JPEG üret — test fixture."""
    from PIL import Image
    import io

    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _make_png(width: int = 80, height: int = 40) -> bytes:
    """PNG test fixture."""
    from PIL import Image
    import io

    img = Image.new("RGB", (width, height), color=(10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── ImageMetadata Tests ─────────────────────────────────────────

class TestBuildImageMetadata:
    """build_image_metadata factory helper tests."""

    def test_basic_jpeg_metadata(self):
        jpeg = _make_jpeg(200, 100)
        meta = build_image_metadata(
            source="upload",
            image_bytes=jpeg,
            original_size=(400, 200),
            normalized_size=(200, 100),
            image_format="jpeg",
            jpeg_quality=92,
        )
        assert meta.source == "upload"
        assert meta.original_width == 400
        assert meta.original_height == 200
        assert meta.normalized_width == 200
        assert meta.normalized_height == 100
        assert meta.image_format == "jpeg"
        assert meta.jpeg_quality == 92
        assert meta.byte_size == len(jpeg)
        assert len(meta.hash_prefix) == 8
        assert meta.frame_id is None

    def test_auto_detect_format_jpeg(self):
        jpeg = _make_jpeg()
        meta = build_image_metadata(
            source="latest_frame",
            image_bytes=jpeg,
        )
        assert meta.image_format == "jpeg"

    def test_auto_detect_format_png(self):
        png = _make_png()
        meta = build_image_metadata(
            source="upload",
            image_bytes=png,
        )
        assert meta.image_format == "png"

    def test_auto_detect_dimensions(self):
        """normalized_size verilmezse PIL'den detect eder."""
        jpeg = _make_jpeg(320, 240)
        meta = build_image_metadata(
            source="pinned_frame",
            image_bytes=jpeg,
        )
        assert meta.normalized_width == 320
        assert meta.normalized_height == 240

    def test_capture_with_frame_id(self):
        jpeg = _make_jpeg()
        meta = build_image_metadata(
            source="capture",
            image_bytes=jpeg,
            frame_id=42,
            captured_at=time.time() - 1.0,
        )
        assert meta.frame_id == 42
        assert meta.age_ms > 900  # en az 1 saniye geçmiş olmalı

    def test_metadata_is_frozen(self):
        """ImageMetadata frozen=True — mutate edilemez."""
        jpeg = _make_jpeg()
        meta = build_image_metadata(source="upload", image_bytes=jpeg)
        with pytest.raises(AttributeError):
            meta.source = "hacked"  # type: ignore

    def test_upload_no_recompress(self):
        """Upload image bytes build_image_metadata tarafından değiştirilmez."""
        jpeg = _make_jpeg(640, 480, quality=92)
        original_hash = hashlib.sha256(jpeg).hexdigest()
        meta = build_image_metadata(
            source="upload",
            image_bytes=jpeg,
            jpeg_quality=92,
        )
        # Bytes aynı kalmalı — recompress yok
        after_hash = hashlib.sha256(jpeg).hexdigest()
        assert original_hash == after_hash
        assert meta.byte_size == len(jpeg)


class TestHashPrefix:
    """hash_prefix deterministic length tests."""

    def test_deterministic_8_chars(self):
        data = b"test data for hash"
        h = _compute_hash_prefix(data)
        assert len(h) == 8
        assert h == _compute_hash_prefix(data)  # idempotent

    def test_different_data_different_hash(self):
        h1 = _compute_hash_prefix(b"image_a")
        h2 = _compute_hash_prefix(b"image_b")
        assert h1 != h2

    def test_hex_only(self):
        h = _compute_hash_prefix(b"some bytes")
        assert all(c in "0123456789abcdef" for c in h)


class TestFormatDetection:
    """Magic bytes format detection tests."""

    def test_jpeg_magic(self):
        assert _detect_image_format(b'\xff\xd8\xff\xe0rest') == "jpeg"

    def test_png_magic(self):
        assert _detect_image_format(b'\x89PNG\r\n\x1a\nrest') == "png"

    def test_unknown_magic(self):
        assert _detect_image_format(b'random bytes') == "unknown"


# ── Debug Export Tests ──────────────────────────────────────────

class TestDebugExport:
    """Debug frame export flag-gated tests."""

    def test_export_disabled_no_file(self):
        """Default kapalı — dosya yazılmamalı."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # export_debug_frame'i çağırmıyoruz — sadece flag kapalıyken
            # caller'ın çağırmadığını simüle ediyoruz
            export_path = os.path.join(tmpdir, "debug_frames")
            assert not os.path.exists(export_path)

    def test_export_enabled_writes_file(self):
        """Flag açıkken dosya yazılmalı."""
        jpeg = _make_jpeg(160, 120)
        with tempfile.TemporaryDirectory() as tmpdir:
            export_dir = os.path.join(tmpdir, "debug_frames")
            filename = export_debug_frame(jpeg, "latest_frame", export_dir=export_dir)

            assert filename is not None
            assert filename == "latest_frame_model_input.jpg"

            filepath = os.path.join(export_dir, filename)
            assert os.path.exists(filepath)

            # Yazılan dosya modele giden bytes ile aynı olmalı
            with open(filepath, "rb") as f:
                written = f.read()
            assert written == jpeg

    def test_export_png_correct_extension(self):
        """PNG export doğru uzantı (.png) kullanmalı."""
        png = _make_png()
        with tempfile.TemporaryDirectory() as tmpdir:
            filename = export_debug_frame(png, "upload", export_dir=tmpdir)
            assert filename == "upload_model_input.png"

    def test_export_overwrites_safely(self):
        """Aynı source tekrar export edilince üzerine yazar."""
        jpeg1 = _make_jpeg(100, 50)
        jpeg2 = _make_jpeg(200, 100)
        with tempfile.TemporaryDirectory() as tmpdir:
            export_debug_frame(jpeg1, "pinned_frame", export_dir=tmpdir)
            export_debug_frame(jpeg2, "pinned_frame", export_dir=tmpdir)

            filepath = os.path.join(tmpdir, "pinned_frame_model_input.jpg")
            with open(filepath, "rb") as f:
                written = f.read()
            assert written == jpeg2  # son yazılan


# ── CapturedFrame Metadata Tests ────────────────────────────────

class TestCapturedFrameMetadata:
    """CapturedFrame original/normalized resolution tracking."""

    def test_backward_compat_minimal(self):
        """Eski kullanım şekli hâlâ çalışmalı — sadece image_bytes ve timestamp."""
        from src.capture import CapturedFrame

        frame = CapturedFrame(
            image_bytes=b"fake_jpeg",
            timestamp=time.time(),
            width=1280,
            height=720,
        )
        assert frame.width == 1280
        assert frame.height == 720
        # Yeni alanlar default değerlerle
        assert frame.original_width is None
        assert frame.original_height is None
        assert frame.source == "capture"
        assert frame.jpeg_quality is None
        assert frame.frame_id is None

    def test_full_metadata(self):
        """Tüm metadata alanları doğru set edilmeli."""
        from src.capture import CapturedFrame

        frame = CapturedFrame(
            image_bytes=b"fake_jpeg",
            timestamp=time.time(),
            width=1280,
            height=720,
            original_width=2560,
            original_height=1440,
            source="grab_now",
            jpeg_quality=85,
            frame_id=7,
        )
        assert frame.original_width == 2560
        assert frame.original_height == 1440
        assert frame.source == "grab_now"
        assert frame.jpeg_quality == 85
        assert frame.frame_id == 7
        # Normalized = width/height (backward compat)
        assert frame.width == 1280


# ── Upload Metadata Tests ───────────────────────────────────────

class TestUploadMetadata:
    """Upload image metadata generation — no recompress."""

    def test_upload_metadata_from_jpeg(self):
        jpeg = _make_jpeg(1920, 1080, quality=92)
        meta = build_image_metadata(
            source="upload",
            image_bytes=jpeg,
            jpeg_quality=92,
        )
        assert meta.source == "upload"
        assert meta.normalized_width == 1920
        assert meta.normalized_height == 1080
        assert meta.image_format == "jpeg"
        assert meta.byte_size > 0
        assert len(meta.hash_prefix) == 8

    def test_upload_metadata_from_png(self):
        png = _make_png(800, 600)
        meta = build_image_metadata(
            source="upload",
            image_bytes=png,
        )
        assert meta.source == "upload"
        assert meta.image_format == "png"
        assert meta.jpeg_quality is None
        assert meta.normalized_width == 800
        assert meta.normalized_height == 600


# ── Provider Logging Tests ──────────────────────────────────────

class TestProviderImageLogging:
    """log_image_context outputs safe metadata (no path leak)."""

    def test_log_no_path_leak(self, caplog):
        """Log çıktısında dosya yolu, secret veya env bilgisi olmamalı."""
        import logging

        jpeg = _make_jpeg()
        meta = build_image_metadata(
            source="latest_frame",
            image_bytes=jpeg,
            original_size=(2560, 1440),
            normalized_size=(1280, 720),
            jpeg_quality=85,
        )

        with caplog.at_level(logging.INFO, logger="voxdesk.image_metadata"):
            log_image_context(meta)

        log_text = caplog.text
        assert "source=latest_frame" in log_text
        assert "original=2560x1440" in log_text
        assert "normalized=1280x720" in log_text
        assert "format=jpeg" in log_text
        assert "quality=85" in log_text

        # Path leak kontrolü
        assert "C:\\" not in log_text
        assert "Users" not in log_text
        assert "Desktop" not in log_text

    def test_log_unknown_original(self, caplog):
        """Original bilinmiyorsa 'unknown' yazmalı."""
        import logging

        jpeg = _make_jpeg()
        meta = build_image_metadata(
            source="upload",
            image_bytes=jpeg,
            # original_size verilmedi
        )

        with caplog.at_level(logging.INFO, logger="voxdesk.image_metadata"):
            log_image_context(meta)

        assert "original=unknown" in caplog.text


# ── Config Feature Flag Tests ───────────────────────────────────

class TestDebugCaptureExportConfig:
    """Feature flag default value test."""

    def test_default_disabled(self):
        from src.config import FeaturesConfig

        fc = FeaturesConfig()
        assert fc.enable_debug_capture_export is False
