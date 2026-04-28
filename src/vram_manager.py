"""
VoxDesk — VRAM Manager
GPU bellek izleme ve model lifecycle koordinasyonu.
torch.cuda.is_available() guard — GPU yoksa crash yok, safe report döner.
Runtime model download YOK — local_files_only mantığı korunur.

Lives on app.state — NOT a singleton.
Metrics entegrasyonu MetricsCollector üzerinden.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.metrics import MetricsCollector
    from src.model_state import ManagedModel

logger = logging.getLogger("voxdesk.vram")


def _cuda_available() -> bool:
    """torch.cuda.is_available() — import failure'da False döner."""
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _get_vram_stats() -> dict:
    """
    PyTorch CUDA memory stats (process-local, NOT nvidia-smi).
    GPU yoksa safe empty dict döner.
    """
    if not _cuda_available():
        return {"cuda_available": False}

    try:
        import torch
        return {
            "cuda_available": True,
            "device_name": torch.cuda.get_device_name(0),
            "allocated_bytes": torch.cuda.memory_allocated(0),
            "reserved_bytes": torch.cuda.memory_reserved(0),
            "max_allocated_bytes": torch.cuda.max_memory_allocated(0),
        }
    except Exception as e:
        return {"cuda_available": False, "error": str(e)}


class VRAMManager:
    """
    GPU bellek izleme ve idle model unload koordinasyonu.

    Lifecycle:
        startup → start_monitor() → monitor loop çalışır
        shutdown → stop_monitor() → task cancel

    Monitor loop:
        - idle_timeout_seconds geçtikten sonra idle modelleri unload eder
        - Metrics'e VRAM durumunu raporlar
        - poll_interval_seconds ile çalışır
    """

    def __init__(
        self,
        metrics: MetricsCollector | None = None,
        idle_timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 30.0,
    ):
        self._metrics = metrics
        self.idle_timeout_seconds = idle_timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds

        self._models: dict[str, ManagedModel] = {}
        self._model_timeouts: dict[str, float] = {}  # per-model idle override
        self._lock = threading.Lock()
        self._monitor_task: asyncio.Task | None = None
        self._running = False

    # ── Model Registration ───────────────────────────────────

    def register_model(
        self,
        name: str,
        model: ManagedModel,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        """İzlenecek model kaydet. idle_timeout_seconds ile model bazlı timeout."""
        with self._lock:
            self._models[name] = model
            if idle_timeout_seconds is not None:
                self._model_timeouts[name] = idle_timeout_seconds
            logger.debug(f"VRAM: {name} modeli izlemeye alındı")

    def unregister_model(self, name: str) -> None:
        """Modeli izlemeden çıkar."""
        with self._lock:
            self._models.pop(name, None)
            self._model_timeouts.pop(name, None)

    # ── Monitor Lifecycle ────────────────────────────────────

    async def start_monitor(self) -> None:
        """Async monitor task başlat."""
        if self._running:
            return
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(
            f"VRAM monitor başlatıldı — "
            f"idle={self.idle_timeout_seconds}s, "
            f"poll={self.poll_interval_seconds}s"
        )

    async def stop_monitor(self) -> None:
        """Monitor task durdur."""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("VRAM monitor durduruldu")

    async def _monitor_loop(self) -> None:
        """
        Periyodik VRAM izleme döngüsü.
        idle_timeout_seconds geçtikten sonra idle modelleri unload eder.
        """
        import time

        while self._running:
            try:
                now = time.monotonic()

                with self._lock:
                    models_snapshot = dict(self._models)

                for name, model in models_snapshot.items():
                    # Idle check — model bazlı veya global timeout
                    timeout = self._model_timeouts.get(
                        name, self.idle_timeout_seconds
                    )
                    if model.is_idle:
                        h = model.health()
                        last_used = h.get("last_used")
                        if last_used is not None:
                            idle_secs = now - last_used
                            if idle_secs >= timeout:
                                logger.info(
                                    f"VRAM: {name} idle {idle_secs:.0f}s "
                                    f"≥ {timeout}s — unload"
                                )
                                # run_in_executor: safe_unload may block on GPU cleanup
                                loop = asyncio.get_running_loop()
                                await loop.run_in_executor(None, model.safe_unload)

                # Metrics güncelle
                self._update_metrics()

                await asyncio.sleep(self.poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"VRAM monitor hatası: {e}")
                await asyncio.sleep(self.poll_interval_seconds)

    # ── Metrics ──────────────────────────────────────────────

    def _update_metrics(self) -> None:
        """Metrics collector'a VRAM durumunu raporla."""
        if self._metrics is None:
            return

        with self._lock:
            for name, model in self._models.items():
                flag_name = f"model_loaded_{name}"
                self._metrics.set_flag(flag_name, model.is_loaded)

    # ── Reporting ────────────────────────────────────────────

    def get_report(self) -> dict:
        """Tam VRAM raporu — model states + GPU stats."""
        with self._lock:
            model_reports = {
                name: model.health()
                for name, model in self._models.items()
            }

        return {
            "gpu": _get_vram_stats(),
            "models": model_reports,
            "monitor_running": self._running,
            "idle_timeout_seconds": self.idle_timeout_seconds,
        }

    # ── Cleanup ──────────────────────────────────────────────

    def close(self) -> None:
        """Tüm modelleri kapat — shutdown sırasında."""
        self._running = False
        with self._lock:
            for name, model in self._models.items():
                try:
                    model.close()
                    logger.debug(f"VRAM: {name} kapatıldı")
                except Exception as e:
                    logger.error(f"VRAM: {name} kapatma hatası: {e}")
