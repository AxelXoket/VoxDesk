"""
VoxDesk — Image Metadata
Tüm image source'lar için ortak metadata yapısı.
Upload, capture, pinned frame, voice screen aynı formatta metadata üretir.

Design:
  - ImageMetadata: immutable dataclass — source, resolution, format, hash
  - build_image_metadata(): factory helper
  - log_image_context(): inference öncesi safe log
  - export_debug_frame(): debug frame export (flag-gated)
"""

from __future__ import annotations

import hashlib
import io
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("voxdesk.image_metadata")


@dataclass(frozen=True)
class ImageMetadata:
    """Modele giden bir image'ın diagnostic metadata'sı."""
    source: str                          # "upload", "latest_frame", "pinned_frame", "voice_screen"
    original_width: int | None = None    # Resize öncesi (biliniyorsa)
    original_height: int | None = None
    normalized_width: int = 0            # Resize sonrası (modele giden)
    normalized_height: int = 0
    image_format: str = "jpeg"           # "jpeg", "png", "webp"
    jpeg_quality: int | None = None      # Capture pipeline quality (upload'da frontend quality)
    byte_size: int = 0                   # len(image_bytes)
    frame_id: int | None = None          # Ring buffer index (capture only)
    captured_at: float = 0.0             # time.time() timestamp
    hash_prefix: str = ""                # SHA256 ilk 8 hex
    age_ms: float = 0.0                  # Capture'dan bu ana kadar geçen ms


def _compute_hash_prefix(data: bytes, length: int = 8) -> str:
    """SHA256 hash'in ilk N hex karakteri — deterministic, hızlı."""
    return hashlib.sha256(data).hexdigest()[:length]


def _detect_image_format(data: bytes) -> str:
    """Magic bytes'tan image formatını tespit et."""
    if data[:2] == b'\xff\xd8':
        return "jpeg"
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "png"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "webp"
    return "unknown"


def _get_image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Image bytes'tan width/height çıkar (PIL ile)."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        return img.size  # (width, height)
    except Exception:
        return None


def build_image_metadata(
    source: str,
    image_bytes: bytes,
    original_size: tuple[int, int] | None = None,
    normalized_size: tuple[int, int] | None = None,
    image_format: str | None = None,
    jpeg_quality: int | None = None,
    frame_id: int | None = None,
    captured_at: float | None = None,
) -> ImageMetadata:
    """
    Tüm image source'lar için ortak metadata oluştur.

    Args:
        source: "upload", "latest_frame", "pinned_frame", "voice_screen"
        image_bytes: Modele gönderilecek ham bytes
        original_size: (width, height) resize öncesi (biliniyorsa)
        normalized_size: (width, height) resize sonrası (biliniyorsa, yoksa detect)
        image_format: "jpeg"/"png"/"webp" (None ise magic bytes'tan detect)
        jpeg_quality: JPEG quality (capture config'den)
        frame_id: Ring buffer index (capture source'larda)
        captured_at: Yakalanma zamanı (time.time)
    """
    # Auto-detect format
    if image_format is None:
        image_format = _detect_image_format(image_bytes)

    # Auto-detect normalized dimensions
    nw, nh = 0, 0
    if normalized_size:
        nw, nh = normalized_size
    else:
        dims = _get_image_dimensions(image_bytes)
        if dims:
            nw, nh = dims

    # Timestamp
    now = time.time()
    cap_time = captured_at or now
    age_ms = (now - cap_time) * 1000

    return ImageMetadata(
        source=source,
        original_width=original_size[0] if original_size else None,
        original_height=original_size[1] if original_size else None,
        normalized_width=nw,
        normalized_height=nh,
        image_format=image_format,
        jpeg_quality=jpeg_quality,
        byte_size=len(image_bytes),
        frame_id=frame_id,
        captured_at=cap_time,
        hash_prefix=_compute_hash_prefix(image_bytes),
        age_ms=age_ms,
    )


def log_image_context(meta: ImageMetadata) -> None:
    """
    LLM inference öncesi image context logla.
    Safe: path/secret/env leak yok — sadece metadata.
    """
    orig = (
        f"{meta.original_width}x{meta.original_height}"
        if meta.original_width and meta.original_height
        else "unknown"
    )
    logger.info(
        f"Using image context:\n"
        f"  source={meta.source}\n"
        f"  original={orig}\n"
        f"  normalized={meta.normalized_width}x{meta.normalized_height}\n"
        f"  format={meta.image_format}\n"
        f"  quality={meta.jpeg_quality}\n"
        f"  bytes={meta.byte_size}\n"
        f"  age_ms={meta.age_ms:.0f}\n"
        f"  hash={meta.hash_prefix}"
    )


def export_debug_frame(
    image_bytes: bytes,
    source: str,
    export_dir: str | Path = "data/debug_frames",
) -> str | None:
    """
    Debug frame export — modele giden gerçek bytes'ı diske yaz.
    Caller enable_debug_capture_export flag'i kontrol etmeli.

    Returns:
        Yazılan dosya adı (basename only — path leak yok), veya None.
    """
    try:
        export_path = Path(export_dir)
        export_path.mkdir(parents=True, exist_ok=True)

        # Detect format for extension
        fmt = _detect_image_format(image_bytes)
        ext = "jpg" if fmt == "jpeg" else fmt if fmt != "unknown" else "bin"
        filename = f"{source}_model_input.{ext}"
        filepath = export_path / filename

        filepath.write_bytes(image_bytes)
        logger.debug(f"Debug frame exported: {filename} ({len(image_bytes)} bytes)")
        return filename
    except Exception as e:
        logger.error(f"Debug frame export failed: {e}")
        return None
