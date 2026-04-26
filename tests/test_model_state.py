"""
VoxDesk — Model State Machine Tests
ManagedModel lifecycle, ref_count, unload guards, state transitions.
GERÇEK MODEL YÜKLEME YOK — tüm testler mock/fake model ile.
"""

import time
import threading
import pytest
from unittest.mock import MagicMock

from src.model_state import ManagedModel, ModelState


# ══════════════════════════════════════════════════════════════
#  Fake Model — test-only, gerçek GPU/model yok
# ══════════════════════════════════════════════════════════════

class FakeModel(ManagedModel):
    """Test-only ManagedModel subclass — no real model loading."""

    def __init__(self, *, should_fail: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._should_fail = should_fail
        self.load_count = 0
        self.unload_count = 0

    def _do_load(self):
        if self._should_fail:
            raise RuntimeError("Fake load failure")
        self.load_count += 1
        return "fake_model_object"

    def _do_unload(self):
        self.unload_count += 1


# ══════════════════════════════════════════════════════════════
#  Initial State
# ══════════════════════════════════════════════════════════════

class TestInitialState:
    """Model başlangıç durumu."""

    @pytest.mark.unit
    def test_initial_state_is_unloaded(self):
        """Yeni model UNLOADED olmalı."""
        m = FakeModel(name="test-stt")
        assert m.state == ModelState.UNLOADED
        assert m.ref_count == 0
        assert not m.is_loaded
        assert not m.is_idle

    @pytest.mark.unit
    def test_initial_health(self):
        """Health raporu başlangıç değerlerini göstermeli."""
        m = FakeModel(name="test-stt")
        h = m.health()
        assert h["name"] == "test-stt"
        assert h["state"] == "unloaded"
        assert h["ref_count"] == 0
        assert h["error"] is None


# ══════════════════════════════════════════════════════════════
#  Load / Unload Lifecycle
# ══════════════════════════════════════════════════════════════

class TestLoadUnload:
    """Load ve unload lifecycle."""

    @pytest.mark.unit
    def test_load_success(self):
        """load() başarılı → state LOADED."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        assert m.load() is True
        assert m.state == ModelState.LOADED
        assert m.is_loaded
        assert m.load_count == 1

    @pytest.mark.unit
    def test_load_failure_goes_to_error(self):
        """load() başarısız → state ERROR."""
        m = FakeModel(name="test-stt", should_fail=True)
        assert m.load() is False
        assert m.state == ModelState.ERROR
        h = m.health()
        assert h["error"] is not None
        assert "Fake load failure" in h["error"]

    @pytest.mark.unit
    def test_duplicate_load_no_second_model(self):
        """Zaten loaded iken load() ikinci model yaratmamalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        assert m.load_count == 1

        # İkinci load çağrısı
        result = m.load()
        assert result is True
        assert m.load_count == 1  # Hâlâ 1 — ikinci model yaratılmadı

    @pytest.mark.unit
    def test_unload_success(self):
        """safe_unload() başarılı → state UNLOADED."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        assert m.safe_unload() is True
        assert m.state == ModelState.UNLOADED
        assert m.unload_count == 1

    @pytest.mark.unit
    def test_unload_already_unloaded(self):
        """Zaten unloaded iken safe_unload() True döner (no-op)."""
        m = FakeModel(name="test-stt")
        assert m.safe_unload() is True
        assert m.state == ModelState.UNLOADED

    @pytest.mark.unit
    def test_load_after_error(self):
        """ERROR state'ten tekrar load denenebilmeli."""
        m = FakeModel(name="test-stt", should_fail=True, min_loaded_seconds=0)
        m.load()  # Fail → ERROR
        assert m.state == ModelState.ERROR

        # Fix the failure and try again
        m._should_fail = False
        assert m.load() is True
        assert m.state == ModelState.LOADED


# ══════════════════════════════════════════════════════════════
#  Ref Count Guards
# ══════════════════════════════════════════════════════════════

class TestRefCount:
    """Ref count ve aktif kullanım sırasında unload koruması."""

    @pytest.mark.unit
    def test_acquire_increments_ref_count(self):
        """acquire() ref_count artırmalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        assert m.acquire() is True
        assert m.ref_count == 1
        assert m.state == ModelState.IN_USE

    @pytest.mark.unit
    def test_release_decrements_ref_count(self):
        """release() ref_count azaltmalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.acquire()
        m.release()
        assert m.ref_count == 0
        assert m.state == ModelState.LOADED

    @pytest.mark.unit
    def test_unload_blocked_by_ref_count(self):
        """ref_count > 0 iken safe_unload() False döner."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.acquire()
        assert m.ref_count == 1

        # Unload reddedilmeli
        assert m.safe_unload() is False
        assert m.state == ModelState.IN_USE
        assert m.unload_count == 0

    @pytest.mark.unit
    def test_unload_allowed_after_release(self):
        """ref_count 0'a düştükten sonra unload yapılabilmeli."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.acquire()
        m.release()
        assert m.ref_count == 0

        assert m.safe_unload() is True
        assert m.state == ModelState.UNLOADED

    @pytest.mark.unit
    def test_multiple_acquires_and_releases(self):
        """Birden fazla acquire/release doğru çalışmalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()

        m.acquire()
        m.acquire()
        m.acquire()
        assert m.ref_count == 3
        assert m.state == ModelState.IN_USE

        m.release()
        assert m.ref_count == 2
        assert m.state == ModelState.IN_USE

        m.release()
        m.release()
        assert m.ref_count == 0
        assert m.state == ModelState.LOADED

    @pytest.mark.unit
    def test_release_below_zero_is_safe(self):
        """ref_count 0'dayken release() negatife düşmemeli."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.release()  # ref_count zaten 0
        m.release()  # Yine 0
        assert m.ref_count == 0


# ══════════════════════════════════════════════════════════════
#  Unload Policy Guards
# ══════════════════════════════════════════════════════════════

class TestUnloadPolicy:
    """Unload policy guard'ları."""

    @pytest.mark.unit
    def test_keep_warm_blocks_unload(self):
        """keep_warm=True iken unload reddedilmeli."""
        m = FakeModel(name="test-stt", keep_warm=True, min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        assert m.safe_unload() is False
        assert m.state == ModelState.LOADED

    @pytest.mark.unit
    def test_min_loaded_seconds_blocks_unload(self):
        """min_loaded_seconds dolmadan unload reddedilmeli."""
        m = FakeModel(name="test-stt", min_loaded_seconds=60.0, unload_cooldown_seconds=0)
        m.load()
        # Hemen unload dene — 60s dolmadı
        assert m.safe_unload() is False
        assert m.state == ModelState.LOADED

    @pytest.mark.unit
    def test_cooldown_blocks_second_unload(self):
        """Cooldown aktifken tekrar unload reddedilmeli."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=60.0)
        m.load()

        # İlk unload — başarılı
        m.safe_unload()
        assert m.state == ModelState.UNLOADED

        # Tekrar load + hemen unload — cooldown aktif
        m.load()
        assert m.safe_unload() is False  # Cooldown henüz dolmadı
        assert m.state == ModelState.LOADED


# ══════════════════════════════════════════════════════════════
#  Close (Force Cleanup)
# ══════════════════════════════════════════════════════════════

class TestClose:
    """close() force cleanup."""

    @pytest.mark.unit
    def test_close_forces_unload(self):
        """close() ref_count ne olursa olsun force unload."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.acquire()
        m.acquire()
        assert m.ref_count == 2

        m.close()
        assert m.state == ModelState.UNLOADED
        assert m.ref_count == 0

    @pytest.mark.unit
    def test_close_on_unloaded_is_safe(self):
        """close() UNLOADED state'te crash etmemeli."""
        m = FakeModel(name="test-stt")
        m.close()  # No-op, should not raise
        assert m.state == ModelState.UNLOADED


# ══════════════════════════════════════════════════════════════
#  Health Report
# ══════════════════════════════════════════════════════════════

class TestHealth:
    """Health raporu doğruluğu."""

    @pytest.mark.unit
    def test_error_state_health(self):
        """ERROR state'te health raporu error bilgisi içermeli."""
        m = FakeModel(name="test-stt", should_fail=True)
        m.load()
        h = m.health()
        assert h["state"] == "error"
        assert h["error"] is not None

    @pytest.mark.unit
    def test_loaded_state_health(self):
        """LOADED state'te health raporu doğru olmalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        h = m.health()
        assert h["state"] == "loaded"
        assert h["loaded_at"] is not None
        assert h["error"] is None

    @pytest.mark.unit
    def test_in_use_state_health(self):
        """IN_USE state'te ref_count > 0."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        m.acquire()
        h = m.health()
        assert h["state"] == "in_use"
        assert h["ref_count"] == 1


# ══════════════════════════════════════════════════════════════
#  Thread Safety
# ══════════════════════════════════════════════════════════════

class TestThreadSafety:
    """State machine thread-safety."""

    @pytest.mark.unit
    def test_concurrent_acquire_release(self):
        """Concurrent acquire/release doğru çalışmalı."""
        m = FakeModel(name="test-stt", min_loaded_seconds=0, unload_cooldown_seconds=0)
        m.load()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    m.acquire()
                    m.release()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert m.ref_count == 0
        assert m.state == ModelState.LOADED
