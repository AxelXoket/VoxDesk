"""
VoxDesk — Screen Capture Module
dxcam ile yüksek performanslı ekran yakalama.
Ring buffer ile son N frame bellekte tutulur.
"""

from __future__ import annotations

import io
import time
import threading
import logging
from collections import deque
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger("voxdesk.capture")


@dataclass
class CapturedFrame:
    """Yakalanan bir frame'in metadata'sı ile birlikte saklanması."""
    image_bytes: bytes       # JPEG sıkıştırılmış bytes
    timestamp: float         # Yakalanma zamanı
    width: int = 0           # Normalized (resize sonrası) genişlik
    height: int = 0          # Normalized (resize sonrası) yükseklik
    # ── Part 1.5: Original resolution tracking ──────────────
    original_width: int | None = None   # Resize öncesi orijinal genişlik
    original_height: int | None = None  # Resize öncesi orijinal yükseklik
    source: str = "capture"             # "capture", "grab_now", "pin"
    jpeg_quality: int | None = None     # Encode sırasında kullanılan JPEG quality
    frame_id: int | None = None         # Ring buffer sequence counter


class ScreenCapture:
    """
    dxcam ile ekran yakalama yöneticisi.
    Ring buffer ile son N frame'i bellekte tutar.
    """

    def __init__(
        self,
        interval: float = 1.0,
        buffer_size: int = 30,
        jpeg_quality: int = 85,
        resize_width: int = 1920,
        # Part 3: Preview / Inference quality profiles
        preview_resize_width: int | None = None,
        preview_jpeg_quality: int | None = None,
        inference_resize_width: int | None = None,
        inference_jpeg_quality: int | None = None,
    ):
        self.interval = interval
        self.buffer_size = buffer_size
        self.jpeg_quality = jpeg_quality
        self.resize_width = resize_width

        # Effective profile values (fallback to legacy)
        self.preview_resize_width = preview_resize_width if preview_resize_width is not None else resize_width
        self.preview_jpeg_quality = preview_jpeg_quality if preview_jpeg_quality is not None else jpeg_quality
        self.inference_resize_width = inference_resize_width if inference_resize_width is not None else resize_width
        self.inference_jpeg_quality = inference_jpeg_quality if inference_jpeg_quality is not None else jpeg_quality

        self._buffer: deque[CapturedFrame] = deque(maxlen=buffer_size)
        self._camera = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_counter: int = 0  # Part 1.5: monotonic frame ID
        # Pin mechanism — hotkey ile yakalanan frame
        self._pinned_frame: CapturedFrame | None = None
        self._pin_lock = threading.Lock()

    def _init_camera(self):
        """dxcam kamerasını başlat."""
        try:
            import dxcam
            self._camera = dxcam.create()
            logger.info(f"✅ dxcam başlatıldı — ekran yakalama hazır")
        except Exception as e:
            logger.error(f"❌ dxcam başlatılamadı: {e}")
            raise

    def _encode_frame(
        self,
        img: Image.Image,
        profile: str = "preview",
        source: str = "capture",
    ) -> CapturedFrame:
        """
        PIL Image → CapturedFrame (resize + JPEG encode).
        profile: "preview" (1280/Q85) veya "inference" (1920/Q92).
        """
        orig_w, orig_h = img.width, img.height

        if profile == "inference":
            rw = self.inference_resize_width
            jq = self.inference_jpeg_quality
        else:
            rw = self.preview_resize_width
            jq = self.preview_jpeg_quality

        # Resize — 0 = no resize
        if rw > 0 and img.width > rw:
            ratio = rw / img.width
            new_height = int(img.height * ratio)
            img = img.resize((rw, new_height), Image.LANCZOS)

        # JPEG encode → bytes (bellekte, diske yazmaz)
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=jq)
        jpeg_bytes = buffer.getvalue()

        self._frame_counter += 1
        return CapturedFrame(
            image_bytes=jpeg_bytes,
            timestamp=time.time(),
            width=img.width,
            height=img.height,
            original_width=orig_w,
            original_height=orig_h,
            source=source,
            jpeg_quality=jq,
            frame_id=self._frame_counter,
        )

    def _capture_frame(self) -> CapturedFrame | None:
        """Tek bir frame yakala — PREVIEW profili (ring buffer için)."""
        try:
            frame = self._camera.grab()
            if frame is None:
                return None
            img = Image.fromarray(frame)
            return self._encode_frame(img, profile="preview", source="capture")
        except Exception as e:
            logger.error(f"Frame yakalama hatası: {e}")
            return None

    def _capture_loop(self):
        """Arka planda sürekli frame yakalama döngüsü — drift-free."""
        logger.info(f"🖥️ Capture döngüsü başladı — interval: {self.interval}s")
        while self._running:
            t0 = time.monotonic()
            frame = self._capture_frame()
            if frame:
                with self._lock:
                    self._buffer.append(frame)
            elapsed = time.monotonic() - t0
            sleep_time = max(0, self.interval - elapsed)
            time.sleep(sleep_time)

    def start(self):
        """Ekran yakalamayı başlat (arka plan thread)."""
        if self._running:
            return

        self._init_camera()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("🟢 Screen capture aktif")

    def stop(self):
        """Ekran yakalamayı durdur."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self._camera:
            try:
                if hasattr(self._camera, 'release'):
                    self._camera.release()
                else:
                    del self._camera
            except Exception as e:
                logger.warning(f"Camera release hatası: {e}")
            self._camera = None
        logger.info("🔴 Screen capture durduruldu")

    def get_latest_frame(self) -> CapturedFrame | None:
        """En son yakalanan frame'i döndür."""
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def get_recent_frames(self, count: int = 5) -> list[CapturedFrame]:
        """Son N frame'i döndür."""
        with self._lock:
            frames = list(self._buffer)
            return frames[-count:] if len(frames) >= count else frames

    def grab_now(self, profile: str = "inference") -> CapturedFrame | None:
        """
        Anlık frame yakala — CPU tabanlı (PIL ImageGrab).
        Default: inference profili (1920/Q92) — LLM inference için.
        profile="preview" ile düşük kalite de alınabilir.
        """
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            return self._encode_frame(img, profile=profile, source="grab_now")
        except Exception as e:
            logger.error(f"CPU grab failed: {e}")
            # Fallback to ring buffer
            return self.get_latest_frame()

    # ── Pin Mechanism ─────────────────────────────────────────
    # Hotkey ile mevcut frame'i "pinle" — sekme değişince kaybolmasın

    def pin_current_frame(self) -> CapturedFrame | None:
        """
        Mevcut ekranı anlık yakala ve pinle — INFERENCE profili.
        Hotkey callback'inden çağrılır.
        Returns: Pinlenen frame, veya None (capture başarısızsa)
        """
        frame = self.grab_now(profile="inference")
        if frame:
            with self._pin_lock:
                self._pinned_frame = frame
            logger.info(f"📌 Ekran pinlendi — inference ({frame.width}x{frame.height}, Q{frame.jpeg_quality})")
        return frame

    def get_pinned_frame(self) -> CapturedFrame | None:
        """Pinlenmiş frame'i döndür (varsa)."""
        with self._pin_lock:
            return self._pinned_frame

    def clear_pin(self) -> None:
        """Pin'i temizle (kullanıldıktan sonra çağrılır)."""
        with self._pin_lock:
            self._pinned_frame = None
        logger.debug("📌 Pin temizlendi")

    def get_best_frame(self) -> CapturedFrame | None:
        """
        Mesaj gönderiminde en iyi frame'i seç.
        Öncelik: pinned > latest from ring buffer
        Pin varsa kullanır ve temizler.
        """
        pinned = self.get_pinned_frame()
        if pinned:
            self.clear_pin()
            return pinned
        return self.get_latest_frame()

    @property
    def has_pin(self) -> bool:
        with self._pin_lock:
            return self._pinned_frame is not None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def buffer_count(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ── Protocol Compliance ───────────────────────────────────

    def health(self) -> dict:
        """Capture subsystem health report."""
        with self._lock:
            buf_count = len(self._buffer)
        return {
            "running": self._running,
            "buffer_count": buf_count,
            "buffer_size": self.buffer_size,
            "interval": self.interval,
            "has_camera": self._camera is not None,
            "has_pin": self.has_pin,
        }

    def close(self) -> None:
        """
        Full cleanup — stop capture, release camera, clear buffers.
        Safe to call multiple times.
        """
        self.stop()
        # Clear buffers
        with self._lock:
            self._buffer.clear()
        # Clear pin
        with self._pin_lock:
            self._pinned_frame = None
        logger.info("🔴 Screen capture closed & buffers cleared")
