"""
VoxDesk — Canonical Image Artifact
Turn-scoped, validated image container for LLM inference.
All image sources (upload, capture, pin, voice) produce the same artifact.

Design:
  - CanonicalImageArtifact: validated, turn-scoped container
  - build_artifact_from_frame(): CapturedFrame → artifact
  - build_artifact_from_upload(): raw upload bytes → artifact
  - build_artifact_from_bytes(): generic bytes → artifact (backward compat)
  - validate_image(): MIME, size, dimension checks
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from src.image_metadata import (
    ImageMetadata,
    build_image_metadata,
    _detect_image_format,
)

logger = logging.getLogger("voxdesk.image_artifact")

# ── Validation Constants (hard-coded; config-based in Part 3) ────
MAX_IMAGE_BYTES = 20 * 1024 * 1024       # 20 MB
MAX_IMAGE_DIMENSION = 4096               # px per axis
ALLOWED_FORMATS = {"jpeg", "png", "webp"}
MIME_MAP = {
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


class ImageValidationError(ValueError):
    """Image doğrulama hatası — invalid format, size, dimension."""
    def __init__(self, message: str, code: str = "IMAGE_DECODE_FAILED"):
        super().__init__(message)
        self.code = code


@dataclass
class CanonicalImageArtifact:
    """
    Turn-scoped validated image container for LLM inference.
    Tüm image source'lar bu yapıyı üretir; provider sadece bunu tüketir.
    """
    source: str                          # "upload", "pinned_frame", "latest_frame", "voice_screen"
    image_bytes: bytes                   # Modele giden raw bytes (değiştirilmemiş)
    metadata: ImageMetadata              # Part 1.5 metadata
    mime_type: str                       # "image/jpeg" etc.
    format: str                          # "jpeg", "png", "webp"
    has_exif_orientation: bool = False   # EXIF orientation tag var mı (Part 2: sadece flag)
    stale: bool = False                  # Frame yaşı yüksek mi
    turn_scoped: bool = True             # Her turn'de yeniden oluşturulmalı


# ── Validation ───────────────────────────────────────────────────

def _check_exif_orientation(image_bytes: bytes) -> bool:
    """EXIF orientation tag var mı kontrol et. Auto-normalize YAPMAZ."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        return 274 in exif and exif[274] != 1
    except Exception:
        return False


def validate_image(
    image_bytes: bytes,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_dimension: int = MAX_IMAGE_DIMENSION,
) -> tuple[bool, str | None]:
    """
    Image bytes doğrula: MIME, size, dimension.
    Returns (valid, error_message).
    """
    if len(image_bytes) < 8:
        return False, "Image too small: less than 8 bytes"

    if len(image_bytes) > max_bytes:
        return False, f"Image too large: {len(image_bytes)} bytes > {max_bytes} limit"

    fmt = _detect_image_format(image_bytes)
    if fmt not in ALLOWED_FORMATS:
        return False, f"Unsupported image format: {fmt}"

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if w > max_dimension or h > max_dimension:
            return False, f"Image dimensions too large: {w}x{h} > {max_dimension}px"
        if w < 1 or h < 1:
            return False, f"Invalid image dimensions: {w}x{h}"
    except Exception as e:
        return False, f"Cannot decode image: {e}"

    return True, None


# ── Factory: CapturedFrame → Artifact ────────────────────────────

def build_artifact_from_frame(frame, source_override: str | None = None) -> CanonicalImageArtifact:
    """CapturedFrame → CanonicalImageArtifact."""
    source_map = {"capture": "latest_frame", "grab_now": "latest_frame", "pin": "pinned_frame"}
    source = source_override or source_map.get(frame.source, frame.source)

    original_size = None
    if frame.original_width and frame.original_height:
        original_size = (frame.original_width, frame.original_height)

    metadata = build_image_metadata(
        source=source,
        image_bytes=frame.image_bytes,
        original_size=original_size,
        normalized_size=(frame.width, frame.height),
        image_format="jpeg",
        jpeg_quality=frame.jpeg_quality,
        frame_id=frame.frame_id,
        captured_at=frame.timestamp,
    )

    fmt = _detect_image_format(frame.image_bytes)
    return CanonicalImageArtifact(
        source=source,
        image_bytes=frame.image_bytes,
        metadata=metadata,
        mime_type=MIME_MAP.get(fmt, "image/jpeg"),
        format=fmt,
        has_exif_orientation=False,  # Screen captures have no EXIF
    )


# ── Factory: Upload → Artifact ───────────────────────────────────

def build_artifact_from_upload(
    image_bytes: bytes,
    jpeg_quality: int | None = None,
) -> CanonicalImageArtifact:
    """
    Upload image bytes → CanonicalImageArtifact.
    Recompress YAPMAZ — orijinal bytes korunur.
    EXIF detect edilir ama auto-normalize yapılmaz (Part 2 kararı).
    """
    valid, err = validate_image(image_bytes)
    if not valid:
        raise ImageValidationError(err or "Invalid upload image", "IMAGE_DECODE_FAILED")

    fmt = _detect_image_format(image_bytes)
    has_exif = _check_exif_orientation(image_bytes)
    if has_exif:
        logger.info("Upload image has EXIF orientation tag — not auto-normalized (Part 2 flag only)")

    metadata = build_image_metadata(
        source="upload",
        image_bytes=image_bytes,
        jpeg_quality=jpeg_quality,
    )

    return CanonicalImageArtifact(
        source="upload",
        image_bytes=image_bytes,
        metadata=metadata,
        mime_type=MIME_MAP.get(fmt, f"image/{fmt}"),
        format=fmt,
        has_exif_orientation=has_exif,
    )


# ── Factory: Generic bytes → Artifact (backward compat) ─────────

def build_artifact_from_bytes(
    image_bytes: bytes,
    source: str = "unknown",
    jpeg_quality: int | None = None,
    captured_at: float | None = None,
    original_size: tuple[int, int] | None = None,
    frame_id: int | None = None,
) -> CanonicalImageArtifact:
    """
    Generic bytes → CanonicalImageArtifact.
    Provider backward compat: image_bytes verilen ama artifact olmayan calllar için.
    """
    valid, err = validate_image(image_bytes)
    if not valid:
        raise ImageValidationError(err or "Invalid image", "IMAGE_DECODE_FAILED")

    fmt = _detect_image_format(image_bytes)
    has_exif = _check_exif_orientation(image_bytes) if source == "upload" else False

    metadata = build_image_metadata(
        source=source,
        image_bytes=image_bytes,
        original_size=original_size,
        jpeg_quality=jpeg_quality,
        frame_id=frame_id,
        captured_at=captured_at,
    )

    return CanonicalImageArtifact(
        source=source,
        image_bytes=image_bytes,
        metadata=metadata,
        mime_type=MIME_MAP.get(fmt, f"image/{fmt}"),
        format=fmt,
        has_exif_orientation=has_exif,
    )
