"""
VoxDesk — Sprint 5.3 Part 3 Tests
Capture/Upload Quality Parity: preview vs inference profiles.
"""

import time
import pytest

from src.config import CaptureConfig
from src.capture import CapturedFrame, ScreenCapture


# ── Config Tests ────────────────────────────────────────────────

class TestCaptureConfigBackwardCompat:
    """Eski config alanları çalışmaya devam etmeli."""

    def test_legacy_defaults(self):
        cfg = CaptureConfig()
        assert cfg.jpeg_quality == 85
        assert cfg.resize_width == 1920

    def test_legacy_only_fallback(self):
        """preview/inference yoksa legacy'ye fallback."""
        cfg = CaptureConfig(resize_width=1280, jpeg_quality=85)
        assert cfg.effective_preview_resize_width == 1280
        assert cfg.effective_preview_jpeg_quality == 85
        assert cfg.effective_inference_resize_width == 1280
        assert cfg.effective_inference_jpeg_quality == 85

    def test_explicit_profiles(self):
        cfg = CaptureConfig(
            resize_width=1280,
            jpeg_quality=85,
            preview_resize_width=1280,
            preview_jpeg_quality=85,
            inference_resize_width=1920,
            inference_jpeg_quality=92,
        )
        assert cfg.effective_preview_resize_width == 1280
        assert cfg.effective_preview_jpeg_quality == 85
        assert cfg.effective_inference_resize_width == 1920
        assert cfg.effective_inference_jpeg_quality == 92

    def test_partial_override(self):
        """Sadece inference override, preview legacy'den."""
        cfg = CaptureConfig(
            resize_width=1280,
            jpeg_quality=85,
            inference_resize_width=1920,
        )
        assert cfg.effective_preview_resize_width == 1280
        assert cfg.effective_inference_resize_width == 1920
        assert cfg.effective_inference_jpeg_quality == 85  # fallback


# ── ScreenCapture Profile Tests ─────────────────────────────────

class TestScreenCaptureProfiles:

    def _make_capture(self):
        return ScreenCapture(
            jpeg_quality=85,
            resize_width=1280,
            preview_resize_width=1280,
            preview_jpeg_quality=85,
            inference_resize_width=1920,
            inference_jpeg_quality=92,
        )

    def test_preview_profile_values(self):
        sc = self._make_capture()
        assert sc.preview_resize_width == 1280
        assert sc.preview_jpeg_quality == 85

    def test_inference_profile_values(self):
        sc = self._make_capture()
        assert sc.inference_resize_width == 1920
        assert sc.inference_jpeg_quality == 92

    def test_fallback_when_none(self):
        sc = ScreenCapture(jpeg_quality=85, resize_width=1280)
        assert sc.preview_resize_width == 1280
        assert sc.preview_jpeg_quality == 85
        assert sc.inference_resize_width == 1280
        assert sc.inference_jpeg_quality == 85

    def test_encode_frame_preview(self):
        """_encode_frame with preview profile uses preview quality."""
        from PIL import Image
        sc = self._make_capture()
        img = Image.new("RGB", (2560, 1440), (100, 100, 100))
        frame = sc._encode_frame(img, profile="preview", source="capture")
        assert frame.width == 1280  # resized to preview width
        assert frame.jpeg_quality == 85
        assert frame.original_width == 2560
        assert frame.source == "capture"

    def test_encode_frame_inference(self):
        """_encode_frame with inference profile uses inference quality."""
        from PIL import Image
        sc = self._make_capture()
        img = Image.new("RGB", (2560, 1440), (100, 100, 100))
        frame = sc._encode_frame(img, profile="inference", source="grab_now")
        assert frame.width == 1920  # resized to inference width
        assert frame.jpeg_quality == 92
        assert frame.original_width == 2560
        assert frame.source == "grab_now"

    def test_encode_no_resize_when_smaller(self):
        """Image already smaller than target → no resize."""
        from PIL import Image
        sc = self._make_capture()
        img = Image.new("RGB", (800, 600), (50, 50, 50))
        frame = sc._encode_frame(img, profile="inference")
        assert frame.width == 800
        assert frame.original_width == 800

    def test_inference_bytes_larger_than_preview(self):
        """Inference frame should have more bytes (higher quality)."""
        from PIL import Image
        sc = self._make_capture()
        img = Image.new("RGB", (2560, 1440), (100, 150, 200))
        preview = sc._encode_frame(img, profile="preview")
        inference = sc._encode_frame(img, profile="inference")
        # Higher resolution + quality → larger bytes
        assert len(inference.image_bytes) >= len(preview.image_bytes)


# ── Artifact Metadata Compat ────────────────────────────────────

class TestArtifactMetadataInference:

    def test_artifact_from_inference_frame(self):
        """Artifact from inference frame carries correct quality metadata."""
        from PIL import Image
        from src.image_artifact import build_artifact_from_frame

        sc = ScreenCapture(
            jpeg_quality=85, resize_width=1280,
            inference_resize_width=1920, inference_jpeg_quality=92,
        )
        img = Image.new("RGB", (2560, 1440), (80, 80, 80))
        frame = sc._encode_frame(img, profile="inference", source="grab_now")
        art = build_artifact_from_frame(frame)

        assert art.metadata.jpeg_quality == 92
        assert art.metadata.normalized_width == 1920
        assert art.metadata.original_width == 2560
        assert art.source == "latest_frame"

    def test_artifact_from_preview_frame(self):
        from PIL import Image
        from src.image_artifact import build_artifact_from_frame

        sc = ScreenCapture(
            jpeg_quality=85, resize_width=1280,
            preview_resize_width=1280, preview_jpeg_quality=85,
        )
        img = Image.new("RGB", (2560, 1440), (80, 80, 80))
        frame = sc._encode_frame(img, profile="preview", source="capture")
        art = build_artifact_from_frame(frame)

        assert art.metadata.jpeg_quality == 85
        assert art.metadata.normalized_width == 1280


# ── Upload Path Unchanged ───────────────────────────────────────

class TestUploadUnchanged:

    def test_upload_no_recompress(self):
        """Upload bytes are not modified by artifact creation."""
        from PIL import Image
        from src.image_artifact import build_artifact_from_upload
        import io

        img = Image.new("RGB", (1920, 1080), (200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        original = buf.getvalue()

        art = build_artifact_from_upload(original, jpeg_quality=92)
        assert art.image_bytes is original  # identity — no recompress


# ── History Policy ──────────────────────────────────────────────

class TestHistoryNoImage:

    def test_no_base64_in_history(self):
        from src.llm.history import ConversationHistory
        h = ConversationHistory()
        h.add_user_message("describe my screen")
        h.add_assistant_message("I see an IDE with code")
        for msg in h.export():
            assert "base64" not in msg["content"].lower()


# ── Debug Export Compat ─────────────────────────────────────────

class TestDebugExportStillDefault:

    def test_default_disabled(self):
        from src.config import FeaturesConfig
        assert FeaturesConfig().enable_debug_capture_export is False
