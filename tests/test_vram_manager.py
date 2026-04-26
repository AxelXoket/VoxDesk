"""
VoxDesk — VRAM Manager Tests
VRAMManager model registration, reporting, idle unload, metrics, GPU guard.
GERÇEK GPU/MODEL YÜKLEME YOK — tüm testler mock ile.
GPU smoke test opsiyonel ve skip'li.
"""

import asyncio
import time
import pytest
from unittest.mock import MagicMock, patch

from src.vram_manager import VRAMManager, _cuda_available, _get_vram_stats
from src.model_state import ManagedModel, ModelState
from src.metrics import MetricsCollector


# ══════════════════════════════════════════════════════════════
#  Fake Model — same as test_model_state.py
# ══════════════════════════════════════════════════════════════

class FakeModel(ManagedModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _do_load(self):
        return "fake_model"

    def _do_unload(self):
        pass


# ══════════════════════════════════════════════════════════════
#  Basic VRAMManager
# ══════════════════════════════════════════════════════════════

class TestVRAMManagerBasics:
    """VRAMManager temel işlevselliği."""

    @pytest.mark.unit
    def test_empty_report(self):
        """Boş manager rapor verebilmeli."""
        vm = VRAMManager()
        report = vm.get_report()
        assert "gpu" in report
        assert "models" in report
        assert report["models"] == {}
        assert report["monitor_running"] is False

    @pytest.mark.unit
    def test_register_model(self):
        """Model kayıt ve rapor."""
        vm = VRAMManager()
        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        vm.register_model("stt", model)

        report = vm.get_report()
        assert "stt" in report["models"]
        assert report["models"]["stt"]["state"] == "unloaded"

    @pytest.mark.unit
    def test_unregister_model(self):
        """Model kayıt silme."""
        vm = VRAMManager()
        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        vm.register_model("stt", model)
        vm.unregister_model("stt")

        report = vm.get_report()
        assert "stt" not in report["models"]

    @pytest.mark.unit
    def test_report_with_loaded_model(self):
        """Loaded model raporu doğru olmalı."""
        vm = VRAMManager()
        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        model.load()
        vm.register_model("stt", model)

        report = vm.get_report()
        assert report["models"]["stt"]["state"] == "loaded"


# ══════════════════════════════════════════════════════════════
#  Metrics Integration
# ══════════════════════════════════════════════════════════════

class TestVRAMMetrics:
    """VRAMManager metrics entegrasyonu."""

    @pytest.mark.unit
    def test_update_metrics_sets_flags(self):
        """_update_metrics model_loaded flag'lerini set etmeli."""
        metrics = MetricsCollector()
        vm = VRAMManager(metrics=metrics)

        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        model.load()
        vm.register_model("stt", model)

        vm._update_metrics()
        report = metrics.get_saturation_report()
        assert report.get("model_loaded_stt") is True

    @pytest.mark.unit
    def test_update_metrics_unloaded_flag(self):
        """Unloaded model flag False olmalı."""
        metrics = MetricsCollector()
        vm = VRAMManager(metrics=metrics)

        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        vm.register_model("stt", model)

        vm._update_metrics()
        report = metrics.get_saturation_report()
        assert report.get("model_loaded_stt") is False

    @pytest.mark.unit
    def test_no_metrics_no_crash(self):
        """metrics=None iken _update_metrics crash etmemeli."""
        vm = VRAMManager(metrics=None)
        model = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        vm.register_model("stt", model)
        vm._update_metrics()  # Should not raise


# ══════════════════════════════════════════════════════════════
#  Cleanup
# ══════════════════════════════════════════════════════════════

class TestVRAMCleanup:
    """close() cleanup."""

    @pytest.mark.unit
    def test_close_stops_all_models(self):
        """close() tüm modelleri kapatmalı."""
        vm = VRAMManager()
        m1 = FakeModel(name="stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m2 = FakeModel(name="tts", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m1.load()
        m2.load()
        vm.register_model("stt", m1)
        vm.register_model("tts", m2)

        vm.close()
        assert m1.state == ModelState.UNLOADED
        assert m2.state == ModelState.UNLOADED

    @pytest.mark.unit
    def test_close_handles_error_gracefully(self):
        """close() model.close() hatası diğerlerini engellememeli."""
        vm = VRAMManager()
        m1 = FakeModel(name="stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m1.load()

        # close() override — error simülasyonu
        original_close = m1.close
        call_count = [0]
        def failing_close():
            call_count[0] += 1
            raise RuntimeError("Close failed")

        m1.close = failing_close
        vm.register_model("stt", m1)

        # Should not raise
        vm.close()
        assert call_count[0] == 1


# ══════════════════════════════════════════════════════════════
#  GPU Guard
# ══════════════════════════════════════════════════════════════

class TestGPUGuard:
    """torch.cuda.is_available() guard — CPU ortamda crash yok."""

    @pytest.mark.unit
    def test_cuda_available_no_crash(self):
        """_cuda_available() crash etmemeli."""
        result = _cuda_available()
        assert isinstance(result, bool)

    @pytest.mark.unit
    def test_vram_stats_no_crash(self):
        """_get_vram_stats() GPU yoksa safe dict dönmeli."""
        stats = _get_vram_stats()
        assert "cuda_available" in stats

    @pytest.mark.unit
    def test_vram_stats_no_gpu_returns_false(self):
        """torch import failure → cuda_available=False."""
        with patch.dict("sys.modules", {"torch": None}):
            result = _cuda_available()
            assert result is False

    @pytest.mark.unit
    @pytest.mark.skipif(
        not _cuda_available(),
        reason="GPU yok — smoke test skip"
    )
    def test_vram_stats_with_gpu(self):
        """GPU varsa detaylı stats dönmeli (opsiyonel smoke test)."""
        stats = _get_vram_stats()
        assert stats["cuda_available"] is True
        assert "device_name" in stats
        assert "allocated_bytes" in stats
