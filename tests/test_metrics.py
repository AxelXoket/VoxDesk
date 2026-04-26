"""
VoxDesk — Metrics Collector Tests
MetricsCollector thread-safety, sliding-window percentile,
counters, gauges, VRAM report, and reset semantics.
"""

import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from src.metrics import MetricsCollector


class TestMetricsCollectorBasics:
    """Basic MetricsCollector functionality."""

    @pytest.mark.unit
    def test_initial_state(self):
        """Fresh collector has zero counters and empty windows."""
        m = MetricsCollector()
        report = m.get_full_report()

        assert report["scope"] == "process-local"
        assert report["errors"]["llm_errors_total"] == 0
        assert report["errors"]["stt_errors_total"] == 0
        assert report["saturation"]["active_stt_requests"] == 0
        assert report["latency"]["llm_latency_ms"]["count"] == 0

    @pytest.mark.unit
    def test_record_latency(self):
        """Latency values are recorded and percentiles computed."""
        m = MetricsCollector()
        for i in range(100):
            m.record_latency("llm_latency_ms", float(i))

        summary = m.get_latency_report()["llm_latency_ms"]
        assert summary["count"] == 100
        assert summary["p50"] is not None
        assert summary["p95"] is not None
        assert summary["p99"] is not None
        # p50 should be around 49-50, p95 around 94-95
        assert 40 <= summary["p50"] <= 55
        assert 90 <= summary["p95"] <= 99

    @pytest.mark.unit
    def test_measure_context_manager(self):
        """measure() context manager records elapsed time."""
        m = MetricsCollector()
        with m.measure("stt_decode_ms"):
            time.sleep(0.01)  # ~10ms

        summary = m.get_latency_report()["stt_decode_ms"]
        assert summary["count"] == 1
        assert summary["p50"] >= 5  # At least 5ms

    @pytest.mark.unit
    def test_increment_counter(self):
        """Monotonic counter increments."""
        m = MetricsCollector()
        m.increment("llm_errors_total")
        m.increment("llm_errors_total")
        m.increment("llm_errors_total", 3)

        report = m.get_error_report()
        assert report["llm_errors_total"] == 5

    @pytest.mark.unit
    def test_unknown_counter_ignored(self):
        """Unknown counter name silently ignored."""
        m = MetricsCollector()
        m.increment("nonexistent_counter")  # Should not raise
        assert "nonexistent_counter" not in m.get_error_report()


class TestGaugesAndFlags:
    """Gauge and flag behavior."""

    @pytest.mark.unit
    def test_set_gauge(self):
        """Gauge can be set to absolute value."""
        m = MetricsCollector()
        m.set_gauge("audio_queue_depth", 42)
        report = m.get_saturation_report()
        assert report["audio_queue_depth"] == 42

    @pytest.mark.unit
    def test_increment_decrement_gauge(self):
        """Gauge can be incremented and decremented."""
        m = MetricsCollector()
        m.increment_gauge("active_stt_requests")
        m.increment_gauge("active_stt_requests")
        assert m.get_saturation_report()["active_stt_requests"] == 2

        m.decrement_gauge("active_stt_requests")
        assert m.get_saturation_report()["active_stt_requests"] == 1

    @pytest.mark.unit
    def test_set_flag(self):
        """Boolean flags can be toggled."""
        m = MetricsCollector()
        assert m.get_saturation_report()["model_loaded_stt"] is False

        m.set_flag("model_loaded_stt", True)
        assert m.get_saturation_report()["model_loaded_stt"] is True

        m.set_flag("model_loaded_stt", False)
        assert m.get_saturation_report()["model_loaded_stt"] is False


class TestSlidingWindow:
    """Sliding window overflow and percentile edge cases."""

    @pytest.mark.unit
    def test_window_overflow(self):
        """Window drops oldest values when full."""
        m = MetricsCollector(window_size=10)
        for i in range(20):
            m.record_latency("llm_latency_ms", float(i))

        # Should only have last 10 values (10-19)
        summary = m.get_latency_report()["llm_latency_ms"]
        assert summary["count"] == 10
        assert summary["p50"] >= 14  # Median of 10-19

    @pytest.mark.unit
    def test_empty_window_returns_none(self):
        """Empty window returns None percentiles."""
        m = MetricsCollector()
        summary = m.get_latency_report()["llm_latency_ms"]
        assert summary["count"] == 0
        assert summary["p50"] is None

    @pytest.mark.unit
    def test_single_value_window(self):
        """Single value window returns that value for all percentiles."""
        m = MetricsCollector()
        m.record_latency("llm_latency_ms", 42.0)

        summary = m.get_latency_report()["llm_latency_ms"]
        assert summary["count"] == 1
        assert summary["p50"] == 42.0
        assert summary["p95"] == 42.0
        assert summary["p99"] == 42.0


class TestVRAMReport:
    """VRAM reporting edge cases."""

    @pytest.mark.unit
    def test_vram_report_no_cuda(self):
        """VRAM report returns cuda_available=False when CUDA unavailable."""
        m = MetricsCollector()
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False
        with patch.dict("sys.modules", {"torch": mock_torch}):
            report = m.get_vram_report()
            assert report["cuda_available"] is False

    @pytest.mark.unit
    def test_vram_report_import_error(self):
        """VRAM report handles torch import failure gracefully."""
        m = MetricsCollector()
        # Real call — if torch isn't available, should not crash
        report = m.get_vram_report()
        assert "cuda_available" in report


class TestResetForTests:
    """reset_for_tests() behavior."""

    @pytest.mark.unit
    def test_reset_clears_all(self):
        """reset_for_tests() clears all metrics."""
        m = MetricsCollector()

        # Populate
        m.record_latency("llm_latency_ms", 100.0)
        m.increment("llm_errors_total", 5)
        m.set_gauge("audio_queue_depth", 10)
        m.set_flag("model_loaded_stt", True)

        # Reset
        m.reset_for_tests()

        report = m.get_full_report()
        assert report["latency"]["llm_latency_ms"]["count"] == 0
        assert report["errors"]["llm_errors_total"] == 0
        assert report["saturation"]["audio_queue_depth"] == 0
        assert report["saturation"]["model_loaded_stt"] is False


class TestThreadSafety:
    """Thread-safety under concurrent access."""

    @pytest.mark.unit
    def test_concurrent_increments(self):
        """Counter handles concurrent increments correctly."""
        m = MetricsCollector()
        errors = []

        def worker():
            try:
                for _ in range(1000):
                    m.increment("llm_errors_total")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert m.get_error_report()["llm_errors_total"] == 4000

    @pytest.mark.unit
    def test_concurrent_latency(self):
        """Latency recording handles concurrent access."""
        m = MetricsCollector()
        errors = []

        def worker():
            try:
                for i in range(100):
                    m.record_latency("llm_latency_ms", float(i))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        summary = m.get_latency_report()["llm_latency_ms"]
        assert summary["count"] > 0


class TestUptime:
    """Uptime tracking."""

    @pytest.mark.unit
    def test_uptime_increases(self):
        """Uptime is non-zero and increases."""
        m = MetricsCollector()
        time.sleep(0.05)
        assert m.get_uptime_seconds() >= 0.04

    @pytest.mark.unit
    def test_uptime_resets(self):
        """reset_for_tests() resets uptime."""
        m = MetricsCollector()
        time.sleep(0.05)
        m.reset_for_tests()
        assert m.get_uptime_seconds() < 0.05
