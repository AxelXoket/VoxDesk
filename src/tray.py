"""
VoxDesk — System Tray Icon
Arka planda çalışma, sağ-tık menüsü.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger("voxdesk.tray")


class TrayIcon:
    """System tray ikonu ve menü yönetimi."""

    def __init__(
        self,
        on_show: Callable | None = None,
        on_quit: Callable | None = None,
    ):
        self.on_show = on_show
        self.on_quit = on_quit
        self._icon = None

    def _create_icon_image(self):
        """Basit bir tray ikonu oluştur."""
        from PIL import Image, ImageDraw

        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Cyan circle — VoxDesk brand color
        draw.ellipse([4, 4, 60, 60], fill=(0, 245, 255, 255))
        # İç daire
        draw.ellipse([16, 16, 48, 48], fill=(0, 0, 0, 255))
        # Göz (küçük nokta)
        draw.ellipse([26, 26, 38, 38], fill=(0, 245, 255, 255))

        return img

    def start(self):
        """System tray ikonunu başlat (arka plan thread)."""
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()
        logger.info("🔔 System tray aktif")

    def _run(self):
        """pystray ile tray ikonu oluştur ve çalıştır."""
        try:
            import pystray
            from pystray import MenuItem

            icon_image = self._create_icon_image()

            menu = pystray.Menu(
                MenuItem("Show VoxDesk", lambda icon, item: self.on_show() if self.on_show else None),
                MenuItem("Quit", lambda icon, item: self._quit()),
            )

            self._icon = pystray.Icon("voxdesk", icon_image, "VoxDesk — AI Assistant", menu)
            self._icon.run()

        except Exception as e:
            logger.error(f"Tray ikonu hatası: {e}")

    def _quit(self):
        """Uygulamayı kapat."""
        if self.on_quit:
            self.on_quit()
        if self._icon:
            self._icon.stop()

    def stop(self):
        """Tray ikonunu durdur."""
        if self._icon:
            self._icon.stop()
