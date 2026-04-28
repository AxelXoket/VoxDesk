"""
VoxDesk — Model State Machine
STT/TTS gibi GPU-bound modellerin güvenli lifecycle yönetimi.

Tek otorite: self._lock
Tüm state mutation (_state, _ref_count, _last_used, _loaded_at) bu lock altında.

State transitions:
    UNLOADED → LOADING → LOADED → IN_USE → LOADED → UNLOADING → UNLOADED
                  ↓                                      ↓
                ERROR                                  ERROR

Kurallar:
    - ref_count > 0 iken unload YASAK
    - duplicate load ikinci model yaratmaz
    - min_loaded_seconds dolmadan unload yok
    - cooldown aktifken tekrar unload yok
    - keep_warm=True iken idle unload yok
    - Tüm transition'lar logged
    - ERROR state health degraded gösterir
"""

from __future__ import annotations

import time
import logging
import threading
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("voxdesk.model_state")


class ModelState(str, Enum):
    """GPU model lifecycle states."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    IN_USE = "in_use"
    UNLOADING = "unloading"
    ERROR = "error"


# Valid state transitions
_VALID_TRANSITIONS: dict[ModelState, set[ModelState]] = {
    ModelState.UNLOADED: {ModelState.LOADING},
    ModelState.LOADING: {ModelState.LOADED, ModelState.ERROR},
    ModelState.LOADED: {ModelState.IN_USE, ModelState.UNLOADING},
    ModelState.IN_USE: {ModelState.LOADED},  # ref_count drops to 0
    ModelState.UNLOADING: {ModelState.UNLOADED, ModelState.ERROR},
    ModelState.ERROR: {ModelState.UNLOADED, ModelState.LOADING},
}


class ManagedModel:
    """
    GPU model lifecycle manager — ref-counted state machine.

    Subclass'lar _do_load() ve _do_unload() implemente eder.
    Bu class state/lock/ref_count yönetir, model I/O yapmaz.

    Thread-safe: tüm mutation self._lock altında.
    """

    def __init__(
        self,
        name: str,
        min_loaded_seconds: float = 30.0,
        unload_cooldown_seconds: float = 10.0,
        keep_warm: bool = False,
    ):
        self.name = name
        self.min_loaded_seconds = min_loaded_seconds
        self.unload_cooldown_seconds = unload_cooldown_seconds
        self.keep_warm = keep_warm

        # Single lock — tek otorite
        self._lock = threading.Lock()
        # Event for load-wait coordination (set when not loading)
        self._load_event = threading.Event()
        self._load_event.set()  # Initially not loading

        # Protected state — sadece _lock altında mutate
        self._state = ModelState.UNLOADED
        self._ref_count: int = 0
        self._loaded_at: float | None = None
        self._last_used: float | None = None
        self._last_unload_attempt: float | None = None
        self._error: str | None = None
        self._model: Any = None

    # ── State Access (thread-safe) ───────────────────────────

    @property
    def state(self) -> ModelState:
        with self._lock:
            return self._state

    @property
    def ref_count(self) -> int:
        with self._lock:
            return self._ref_count

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._state in (ModelState.LOADED, ModelState.IN_USE)

    @property
    def is_idle(self) -> bool:
        """Model loaded ama hiç kullanılmıyor."""
        with self._lock:
            return self._state == ModelState.LOADED and self._ref_count == 0

    # ── State Transitions ────────────────────────────────────

    def _transition(self, new_state: ModelState) -> bool:
        """
        State transition — lock ALTINDA çağrılmalı (internal use).
        Returns True if transition is valid, False otherwise.
        """
        valid = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in valid:
            logger.warning(
                f"[{self.name}] geçersiz transition: "
                f"{self._state.value} → {new_state.value}"
            )
            return False

        old = self._state
        self._state = new_state
        logger.debug(f"[{self.name}] {old.value} → {new_state.value}")
        return True

    # ── Load / Unload ────────────────────────────────────────

    def load(self) -> bool:
        """
        Modeli yükle. Zaten yüklüyse no-op (True döner).
        Başka bir thread yüklüyorsa, bitmesini bekler.
        Returns True if model is now loaded, False if load failed.
        """
        should_wait = False
        should_load = False

        with self._lock:
            # Zaten yüklü — duplicate load protection
            if self._state in (ModelState.LOADED, ModelState.IN_USE):
                logger.debug(f"[{self.name}] zaten yüklü — skip")
                return True

            # Loading durumunda: bekle
            if self._state == ModelState.LOADING:
                logger.debug(f"[{self.name}] zaten yükleniyor — bekleniyor")
                should_wait = True

            elif not self._transition(ModelState.LOADING):
                return False
            else:
                # Bu thread yükleme sahipliğini aldı
                self._load_event.clear()
                should_load = True

        # Lock DIŞINDA — I/O blocking
        if should_load:
            try:
                model = self._do_load()
                with self._lock:
                    self._model = model
                    self._transition(ModelState.LOADED)
                    self._loaded_at = time.monotonic()
                    self._last_used = time.monotonic()
                    self._error = None
                return True
            except Exception as e:
                with self._lock:
                    self._transition(ModelState.ERROR)
                    self._error = str(e)
                logger.error(f"[{self.name}] load hatası: {e}")
                return False
            finally:
                self._load_event.set()  # Bekleyenleri uyandır

        if should_wait:
            # LOADING state'e geldik ama sahip biz değiliz — bekle
            logger.debug(f"[{self.name}] mevcut load işlemi bekleniyor...")
            self._load_event.wait(timeout=120.0)  # Max 2 dakika bekle

            with self._lock:
                if self._state in (ModelState.LOADED, ModelState.IN_USE):
                    logger.debug(f"[{self.name}] bekleme sonrası yüklü — OK")
                    return True
                logger.warning(f"[{self.name}] bekleme sonrası state: {self._state.value}")
                return False

        return False

    def safe_unload(self) -> bool:
        """
        Modeli güvenli şekilde unload et.

        Returns False (unload yapılmadı) eğer:
          - ref_count > 0 (aktif kullanım var)
          - min_loaded_seconds dolmadı
          - cooldown aktif
          - keep_warm=True
          - model zaten unloaded

        Returns True if successfully unloaded.
        """
        with self._lock:
            # Zaten unloaded
            if self._state == ModelState.UNLOADED:
                return True

            # Loaded veya in_use değilse unload anlamsız
            if self._state not in (ModelState.LOADED, ModelState.IN_USE):
                return False

            # REF COUNT GUARD — en kritik kural
            if self._ref_count > 0:
                logger.debug(
                    f"[{self.name}] unload reddedildi: "
                    f"ref_count={self._ref_count}"
                )
                return False

            # Keep warm guard
            if self.keep_warm:
                logger.debug(f"[{self.name}] unload reddedildi: keep_warm=True")
                return False

            # Min loaded time guard
            now = time.monotonic()
            if self._loaded_at is not None:
                elapsed = now - self._loaded_at
                if elapsed < self.min_loaded_seconds:
                    logger.debug(
                        f"[{self.name}] unload reddedildi: "
                        f"min_loaded {elapsed:.1f}s < {self.min_loaded_seconds}s"
                    )
                    return False

            # Cooldown guard
            if self._last_unload_attempt is not None:
                cooldown_elapsed = now - self._last_unload_attempt
                if cooldown_elapsed < self.unload_cooldown_seconds:
                    logger.debug(
                        f"[{self.name}] unload reddedildi: "
                        f"cooldown {cooldown_elapsed:.1f}s < "
                        f"{self.unload_cooldown_seconds}s"
                    )
                    return False

            self._last_unload_attempt = now

            if not self._transition(ModelState.UNLOADING):
                return False

        # Unload işlemi lock DIŞINDA
        try:
            self._do_unload()
            with self._lock:
                self._model = None
                self._transition(ModelState.UNLOADED)
                self._loaded_at = None
                self._ref_count = 0
                return True
        except Exception as e:
            with self._lock:
                self._transition(ModelState.ERROR)
                self._error = str(e)
            logger.error(f"[{self.name}] unload hatası: {e}")
            return False

    # ── Ref Count ────────────────────────────────────────────

    def acquire(self) -> bool:
        """
        Ref count artır — aktif kullanım başlıyor.
        Model loaded değilse otomatik load dener.
        Returns True if model is ready to use.
        """
        with self._lock:
            if self._state not in (ModelState.LOADED, ModelState.IN_USE):
                # Auto-load attempt
                pass
            else:
                self._ref_count += 1
                if self._state == ModelState.LOADED:
                    self._transition(ModelState.IN_USE)
                self._last_used = time.monotonic()
                return True

        # Lock dışında load dene
        if self.load():
            with self._lock:
                self._ref_count += 1
                if self._state == ModelState.LOADED:
                    self._transition(ModelState.IN_USE)
                self._last_used = time.monotonic()
                return True
        return False

    def release(self) -> None:
        """Ref count azalt — aktif kullanım bitti."""
        with self._lock:
            if self._ref_count > 0:
                self._ref_count -= 1
                self._last_used = time.monotonic()

            # Ref count 0'a düştü → IN_USE → LOADED
            if self._ref_count == 0 and self._state == ModelState.IN_USE:
                self._transition(ModelState.LOADED)

    # ── Health ───────────────────────────────────────────────

    def health(self) -> dict:
        """Model durum raporu."""
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "ref_count": self._ref_count,
                "keep_warm": self.keep_warm,
                "loaded_at": self._loaded_at,
                "last_used": self._last_used,
                "error": self._error,
            }

    # ── Close ────────────────────────────────────────────────

    def close(self) -> None:
        """Force cleanup — shutdown sırasında."""
        with self._lock:
            self._ref_count = 0  # Force clear
        try:
            self._do_unload()
        except Exception:
            pass
        with self._lock:
            self._model = None
            self._state = ModelState.UNLOADED
            self._loaded_at = None

    # ── Subclass Hooks ───────────────────────────────────────

    def _do_load(self) -> Any:
        """
        Modeli yükle ve döndür.
        Subclass'lar bunu implemente eder.
        RuntimeError raise ederse state → ERROR.
        """
        raise NotImplementedError("Subclass must implement _do_load()")

    def _do_unload(self) -> None:
        """
        Model kaynaklarını serbest bırak.
        Subclass'lar bunu implemente eder.
        """
        raise NotImplementedError("Subclass must implement _do_unload()")
