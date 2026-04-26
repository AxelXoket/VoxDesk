"""
VoxDesk — Global Hotkey Manager
3 ayrı kısayol: activate, toggle continuous, push-to-talk.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger("voxdesk.hotkey")


class HotkeyManager:
    """
    Global keyboard kısayol yöneticisi.
    3 ayrı kısayol: activate, toggle_listen, push_to_talk.
    """

    def __init__(
        self,
        activate_key: str = "ctrl+shift+space",
        toggle_listen_key: str = "ctrl+shift+v",
        push_to_talk_key: str = "ctrl+shift+b",
    ):
        self.activate_key = activate_key
        self.toggle_listen_key = toggle_listen_key
        self.push_to_talk_key = push_to_talk_key

        self._callbacks: dict[str, Callable] = {}
        self._ptt_release_callback: Callable | None = None
        self._running = False

    def set_callback(self, action: str, callback: Callable) -> None:
        """
        Bir aksiyona callback ata.
        action: "activate", "toggle_listen", "ptt_press", "ptt_release"
        """
        self._callbacks[action] = callback

    def start(self) -> None:
        """Hotkey dinlemeyi başlat (arka plan thread)."""
        if self._running:
            return

        self._running = True
        thread = threading.Thread(target=self._register_hotkeys, daemon=True)
        thread.start()
        logger.info(
            f"⌨️ Hotkeys aktif — "
            f"Activate: {self.activate_key}, "
            f"Toggle: {self.toggle_listen_key}, "
            f"PTT: {self.push_to_talk_key}"
        )

    def _register_hotkeys(self) -> None:
        """keyboard kütüphanesi ile kısayolları kaydet."""
        try:
            import keyboard

            # Activate — toggle UI
            keyboard.add_hotkey(
                self.activate_key,
                lambda: self._fire("activate"),
                suppress=True,
            )

            # Toggle continuous listening
            keyboard.add_hotkey(
                self.toggle_listen_key,
                lambda: self._fire("toggle_listen"),
                suppress=True,
            )

            # Push-to-talk — modifier + key combo ile çalışır
            # Sadece son tuşa basmak yetmez, tüm modifier'lar basılı olmalı
            self._ptt_active = False

            def _check_ptt_press(e):
                import keyboard as kb
                # Tüm modifier'ları kontrol et
                parts = self.push_to_talk_key.split("+")
                modifiers = parts[:-1]  # ['ctrl', 'shift']
                all_pressed = all(
                    kb.is_pressed(mod) for mod in modifiers
                )
                if all_pressed and not self._ptt_active:
                    self._ptt_active = True
                    self._fire("ptt_press")

            def _check_ptt_release(e):
                if self._ptt_active:
                    self._ptt_active = False
                    self._fire("ptt_release")

            last_key = self.push_to_talk_key.split("+")[-1]
            keyboard.on_press_key(
                last_key,
                _check_ptt_press,
                suppress=False,
            )
            keyboard.on_release_key(
                last_key,
                _check_ptt_release,
                suppress=False,
            )

            # Thread'i canlı tut
            keyboard.wait()

        except Exception as e:
            logger.error(f"Hotkey kayıt hatası: {e}")

    def _fire(self, action: str) -> None:
        """Callback'i tetikle."""
        cb = self._callbacks.get(action)
        if cb:
            try:
                cb()
            except Exception as e:
                logger.error(f"Hotkey callback hatası [{action}]: {e}")
        else:
            logger.debug(f"Hotkey tetiklendi ama callback yok: {action}")

    def stop(self) -> None:
        """Hotkey dinlemeyi durdur."""
        self._running = False
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        logger.info("⌨️ Hotkeys durduruldu")
