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
    width: int = 0
    height: int = 0


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
    ):
        self.interval = interval
        self.buffer_size = buffer_size
        self.jpeg_quality = jpeg_quality
        self.resize_width = resize_width

        self._buffer: deque[CapturedFrame] = deque(maxlen=buffer_size)
        self._camera = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _init_camera(self):
        """dxcam kamerasını başlat."""
        try:
            import dxcam
            self._camera = dxcam.create()
            logger.info(f"✅ dxcam başlatıldı — ekran yakalama hazır")
        except Exception as e:
            logger.error(f"❌ dxcam başlatılamadı: {e}")
            raise

    def _capture_frame(self) -> CapturedFrame | None:
        """Tek bir frame yakala ve JPEG olarak sıkıştır."""
        try:
            frame = self._camera.grab()
            if frame is None:
                return None

            # NumPy array -> PIL Image
            img = Image.fromarray(frame)

            # Resize (LLM için optimize)
            if img.width > self.resize_width:
                ratio = self.resize_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((self.resize_width, new_height), Image.LANCZOS)

            # JPEG sıkıştırma -> bytes (bellekte, diske yazmaz)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=self.jpeg_quality)
            jpeg_bytes = buffer.getvalue()

            return CapturedFrame(
                image_bytes=jpeg_bytes,
                timestamp=time.time(),
                width=img.width,
                height=img.height,
            )
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
            del self._camera
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

    def grab_now(self) -> CapturedFrame | None:
        """Anlık frame yakala (buffer'dan değil, canlı)."""
        if not self._camera:
            self._init_camera()
        return self._capture_frame()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def buffer_count(self) -> int:
        with self._lock:
            return len(self._buffer)
