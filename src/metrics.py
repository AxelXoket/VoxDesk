"""
VoxDesk — Metrics Collector
Sliding-window percentile collector + monotonic counters + gauges.
Lives on app.state.metrics — NOT a global singleton.
Thread-safe via threading.Lock (single uvicorn worker assumption).

Metrics are process-local.
"""

from __future__ import annotations

import time
import threading
from collections import deque
from dataclasses import dataclass, field
from contextlib import contextmanager
from typing import Generator


@dataclass
class _SlidingWindow:
    """Sliding-window percentile collector — son N ölçüm üzerinden p50/p95/p99."""
    values: deque = field(default_factory=lambda: deque(maxlen=500))

    def add(self, value: float) -> None:
        self.values.append(value)

    def percentile(self, p: float) -> float | None:
        if not self.values:
            return None
        sorted_vals = sorted(self.values)
        idx = int(len(sorted_vals) * p / 100)
        idx = min(idx, len(sorted_vals) - 1)
        return sorted_vals[idx]

    def summary(self) -> dict:
        if not self.values:
            return {"count": 0, "p50": None, "p95": None, "p99": None}
        return {
            "count": len(self.values),
            "p50": round(self.percentile(50), 2),
            "p95": round(self.percentile(95), 2),
            "p99": round(self.percentile(99), 2),
        }


class MetricsCollector:
    """
    Production-grade metrics collector.

    - Latency: sliding-window percentile (NOT histogram)
    - Errors: monotonic counters
    - Saturation: point-in-time gauges
    - VRAM: torch-based (process-local, NOT nvidia-smi)

    Thread-safe via single threading.Lock.
    Single uvicorn worker assumed — multi-worker requires Prometheus (P2).
    """

    def __init__(self, window_size: int = 500):
        self._lock = threading.Lock()
        self._start_time = time.monotonic()

        # Latency — sliding-window percentile collectors
        self._latency: dict[str, _SlidingWindow] = {
            "llm_latency_ms": _SlidingWindow(deque(maxlen=window_size)),
            "stt_decode_ms": _SlidingWindow(deque(maxlen=window_size)),
            "tts_synthesis_ms": _SlidingWindow(deque(maxlen=window_size)),
        }

        # Error counters — monotonic
        self._counters: dict[str, int] = {
            "llm_errors_total": 0,
            "stt_errors_total": 0,
            "tts_errors_total": 0,
            "ws_disconnects_total": 0,
        }

        # Saturation gauges — point-in-time
        self._gauges: dict[str, float] = {
            "active_stt_requests": 0,
            "active_tts_requests": 0,
            "audio_queue_depth": 0,
        }

        # Boolean flags
        self._flags: dict[str, bool] = {
            "model_loaded_stt": False,
            "model_loaded_tts": False,
        }

    # ── Latency ──────────────────────────────────────────────

    def record_latency(self, name: str, ms: float) -> None:
        """Record a latency measurement in milliseconds."""
        with self._lock:
            if name in self._latency:
                self._latency[name].add(ms)

    @contextmanager
    def measure(self, name: str) -> Generator[None, None, None]:
        """Context manager — auto-records elapsed time in ms."""
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record_latency(name, elapsed_ms)

    # ── Counters ─────────────────────────────────────────────

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a monotonic counter."""
        with self._lock:
            if name in self._counters:
                self._counters[name] += amount

    # ── Gauges ───────────────────────────────────────────────

    def set_gauge(self, name: str, value: float) -> None:
        """Set a point-in-time gauge value."""
        with self._lock:
            if name in self._gauges:
                self._gauges[name] = value

    def increment_gauge(self, name: str, amount: float = 1) -> None:
        """Increment a gauge (e.g., active requests)."""
        with self._lock:
            if name in self._gauges:
                self._gauges[name] += amount

    def decrement_gauge(self, name: str, amount: float = 1) -> None:
        """Decrement a gauge."""
        with self._lock:
            if name in self._gauges:
                self._gauges[name] -= amount

    # ── Flags ────────────────────────────────────────────────

    def set_flag(self, name: str, value: bool) -> None:
        """Set a boolean flag."""
        with self._lock:
            if name in self._flags:
                self._flags[name] = value

    # ── Reporting ────────────────────────────────────────────

    def get_uptime_seconds(self) -> float:
        """Uptime since MetricsCollector creation."""
        return round(time.monotonic() - self._start_time, 1)

    def get_latency_report(self) -> dict:
        """All latency percentile summaries."""
        with self._lock:
            return {name: sw.summary() for name, sw in self._latency.items()}

    def get_error_report(self) -> dict:
        """All error counter values."""
        with self._lock:
            return dict(self._counters)

    def get_saturation_report(self) -> dict:
        """All gauge + flag values."""
        with self._lock:
            result = dict(self._gauges)
            result.update(self._flags)
            return result

    def get_vram_report(self) -> dict:
        """
        PyTorch CUDA memory report (process-local allocator metrics).
        NOT nvidia-smi — these are different measurements.
        Returns empty dict if CUDA is unavailable.
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return {"cuda_available": False}

            return {
                "cuda_available": True,
                "device_name": torch.cuda.get_device_name(0),
                "torch_memory_allocated_bytes": torch.cuda.memory_allocated(0),
                "torch_memory_reserved_bytes": torch.cuda.memory_reserved(0),
                "torch_max_memory_allocated_bytes": torch.cuda.max_memory_allocated(0),
            }
        except Exception:
            return {"cuda_available": False, "error": "torch import failed"}

    def get_full_report(self) -> dict:
        """Complete metrics snapshot for debug endpoint."""
        return {
            "scope": "process-local",
            "uptime_seconds": self.get_uptime_seconds(),
            "latency": self.get_latency_report(),
            "errors": self.get_error_report(),
            "saturation": self.get_saturation_report(),
            "vram": self.get_vram_report(),
        }

    # ── Test Support ─────────────────────────────────────────

    def reset_for_tests(self) -> None:
        """
        Reset all metrics — test-only, NOT for production use.
        Clears all counters, gauges, flags, and latency windows.
        """
        with self._lock:
            for sw in self._latency.values():
                sw.values.clear()
            for key in self._counters:
                self._counters[key] = 0
            for key in self._gauges:
                self._gauges[key] = 0
            for key in self._flags:
                self._flags[key] = False
            self._start_time = time.monotonic()
