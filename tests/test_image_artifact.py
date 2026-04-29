"""
VoxDesk — Sprint 5.3 Part 2 Tests
Canonical Image Artifact: validation, factories, provider integration.
"""

import time
import pytest

from src.image_artifact import (
    CanonicalImageArtifact,
    ImageValidationError,
    build_artifact_from_frame,
    build_artifact_from_upload,
    build_artifact_from_bytes,
    validate_image,
    _check_exif_orientation,
)
from src.capture import CapturedFrame


# ── Helpers ──────────────────────────────────────────────────────

def _jpeg(w=100, h=50, q=85):
    from PIL import Image
    import io
    img = Image.new("RGB", (w, h), (128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=q)
    return buf.getvalue()


def _png(w=80, h=40):
    from PIL import Image
    import io
    img = Image.new("RGB", (w, h), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_frame(w=1280, h=720, orig_w=2560, orig_h=1440, source="capture"):
    return CapturedFrame(
        image_bytes=_jpeg(w, h),
        timestamp=time.time(),
        width=w,
        height=h,
        original_width=orig_w,
        original_height=orig_h,
        source=source,
        jpeg_quality=85,
        frame_id=1,
    )


# ── Validation Tests ────────────────────────────────────────────

class TestValidation:

    def test_valid_jpeg(self):
        ok, err = validate_image(_jpeg())
        assert ok is True
        assert err is None

    def test_valid_png(self):
        ok, err = validate_image(_png())
        assert ok is True

    def test_too_small(self):
        ok, err = validate_image(b"abc")
        assert ok is False
        assert "too small" in err

    def test_unknown_format(self):
        ok, err = validate_image(b"x" * 100)
        assert ok is False
        assert "Unsupported" in err

    def test_too_large(self):
        ok, err = validate_image(_jpeg(), max_bytes=10)
        assert ok is False
        assert "too large" in err

    def test_oversized_dimension(self):
        ok, err = validate_image(_jpeg(200, 200), max_dimension=100)
        assert ok is False
        assert "dimensions too large" in err


# ── Factory: Frame → Artifact ───────────────────────────────────

class TestArtifactFromFrame:

    def test_latest_frame(self):
        frame = _make_frame(source="capture")
        art = build_artifact_from_frame(frame)
        assert art.source == "latest_frame"
        assert art.format == "jpeg"
        assert art.mime_type == "image/jpeg"
        assert art.image_bytes == frame.image_bytes
        assert art.metadata.original_width == 2560
        assert art.metadata.normalized_width == 1280
        assert art.metadata.jpeg_quality == 85
        assert art.has_exif_orientation is False
        assert art.turn_scoped is True

    def test_pinned_frame(self):
        frame = _make_frame(source="grab_now")
        art = build_artifact_from_frame(frame, source_override="pinned_frame")
        assert art.source == "pinned_frame"

    def test_voice_screen(self):
        frame = _make_frame(source="grab_now")
        art = build_artifact_from_frame(frame, source_override="voice_screen")
        assert art.source == "voice_screen"

    def test_grab_now_default_source(self):
        frame = _make_frame(source="grab_now")
        art = build_artifact_from_frame(frame)
        assert art.source == "latest_frame"


# ── Factory: Upload → Artifact ──────────────────────────────────

class TestArtifactFromUpload:

    def test_jpeg_upload(self):
        jpeg = _jpeg(1920, 1080, 92)
        art = build_artifact_from_upload(jpeg, jpeg_quality=92)
        assert art.source == "upload"
        assert art.format == "jpeg"
        assert art.metadata.jpeg_quality == 92
        assert art.image_bytes == jpeg  # no recompress
        assert art.turn_scoped is True

    def test_png_upload(self):
        png = _png()
        art = build_artifact_from_upload(png)
        assert art.source == "upload"
        assert art.format == "png"
        assert art.mime_type == "image/png"

    def test_no_recompress(self):
        """Upload bytes are preserved exactly — no re-encoding."""
        jpeg = _jpeg(640, 480, 92)
        art = build_artifact_from_upload(jpeg)
        assert art.image_bytes is jpeg  # identity check

    def test_invalid_upload_raises(self):
        with pytest.raises(ImageValidationError) as exc_info:
            build_artifact_from_upload(b"not an image at all")
        assert exc_info.value.code == "IMAGE_DECODE_FAILED"

    def test_large_dimension_caught_by_validation(self):
        """Oversized images caught by validate_image before artifact creation."""
        ok, err = validate_image(_jpeg(200, 200), max_dimension=100)
        assert ok is False
        assert "dimensions too large" in err


# ── Factory: Bytes → Artifact (backward compat) ─────────────────

class TestArtifactFromBytes:

    def test_basic(self):
        jpeg = _jpeg()
        art = build_artifact_from_bytes(jpeg, source="unknown")
        assert art.source == "unknown"
        assert art.format == "jpeg"

    def test_invalid_raises(self):
        with pytest.raises(ImageValidationError):
            build_artifact_from_bytes(b"bad")

    def test_with_metadata(self):
        jpeg = _jpeg()
        art = build_artifact_from_bytes(
            jpeg, source="latest_frame",
            jpeg_quality=85, frame_id=5,
        )
        assert art.metadata.jpeg_quality == 85
        assert art.metadata.frame_id == 5


# ── EXIF Detection ──────────────────────────────────────────────

class TestExifDetection:

    def test_no_exif_in_synthetic(self):
        """PIL-generated images have no EXIF orientation."""
        assert _check_exif_orientation(_jpeg()) is False

    def test_no_exif_in_png(self):
        assert _check_exif_orientation(_png()) is False


# ── History / Turn Scope ────────────────────────────────────────

class TestHistoryPolicy:

    def test_history_no_image_stored(self):
        """Conversation history stores only text — no image/base64."""
        from src.llm.history import ConversationHistory
        h = ConversationHistory()
        h.add_user_message("test with image")
        h.add_assistant_message("I see code on screen")
        exported = h.export()
        for msg in exported:
            assert "base64" not in msg["content"].lower()
            assert "image_bytes" not in str(msg)

    def test_artifact_turn_scoped(self):
        art = build_artifact_from_upload(_jpeg())
        assert art.turn_scoped is True


# ── Debug Export Still Works ────────────────────────────────────

class TestDebugExportCompat:

    def test_default_disabled(self):
        from src.config import FeaturesConfig
        fc = FeaturesConfig()
        assert fc.enable_debug_capture_export is False


# ── Part 1.5 Metadata Compat ───────────────────────────────────

class TestMetadataCompat:

    def test_artifact_metadata_matches_part15(self):
        """Artifact metadata uses Part 1.5 ImageMetadata structure."""
        from src.image_metadata import ImageMetadata
        jpeg = _jpeg(320, 240)
        art = build_artifact_from_upload(jpeg, jpeg_quality=92)
        assert isinstance(art.metadata, ImageMetadata)
        assert art.metadata.source == "upload"
        assert art.metadata.byte_size == len(jpeg)
        assert len(art.metadata.hash_prefix) == 8
