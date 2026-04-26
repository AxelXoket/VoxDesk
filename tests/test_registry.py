"""
VoxDesk — Module Registry Tests
Factory catalog lifecycle, create, exists, list, error handling.
"""

import pytest
from unittest.mock import MagicMock

from src.registry import ModuleRegistry


# ══════════════════════════════════════════════════════════════
#  Registry Basics
# ══════════════════════════════════════════════════════════════

class TestRegistryBasics:
    """Core registry functionality."""

    @pytest.mark.unit
    def test_empty_registry(self):
        """Fresh registry has no modules."""
        reg = ModuleRegistry()
        assert reg.list_modules() == {}
        assert not reg.exists("stt", "whisper")

    @pytest.mark.unit
    def test_register_and_exists(self):
        """Registered module should be findable."""
        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", lambda cfg: "stt_instance")

        assert reg.exists("stt", "faster-whisper")
        assert not reg.exists("stt", "unknown")
        assert not reg.exists("tts", "faster-whisper")

    @pytest.mark.unit
    def test_create_with_config(self):
        """create() should call factory with config and return result."""
        mock_factory = MagicMock(return_value="mock_engine")
        mock_config = MagicMock()

        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", mock_factory)

        result = reg.create("stt", "faster-whisper", mock_config)

        assert result == "mock_engine"
        mock_factory.assert_called_once_with(mock_config)

    @pytest.mark.unit
    def test_create_without_config(self):
        """create() should call factory without args when config=None."""
        mock_factory = MagicMock(return_value="mock_engine")

        reg = ModuleRegistry()
        reg.register("tts", "kokoro", mock_factory)

        result = reg.create("tts", "kokoro")

        assert result == "mock_engine"
        mock_factory.assert_called_once_with()


# ══════════════════════════════════════════════════════════════
#  Error Handling
# ══════════════════════════════════════════════════════════════

class TestRegistryErrors:
    """Error cases — unknown kind/name."""

    @pytest.mark.unit
    def test_create_unknown_kind(self):
        """Unknown kind raises KeyError with helpful message."""
        reg = ModuleRegistry()
        reg.register("stt", "whisper", lambda: None)

        with pytest.raises(KeyError, match="bilinmeyen kind"):
            reg.create("unknown", "whisper")

    @pytest.mark.unit
    def test_create_unknown_name(self):
        """Unknown name within valid kind raises KeyError with alternatives."""
        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", lambda: None)

        with pytest.raises(KeyError, match="bulunamadı"):
            reg.create("stt", "nonexistent")

    @pytest.mark.unit
    def test_get_metadata_unknown(self):
        """get_metadata on unknown module raises KeyError."""
        reg = ModuleRegistry()
        with pytest.raises(KeyError):
            reg.get_metadata("stt", "nonexistent")


# ══════════════════════════════════════════════════════════════
#  Listing & Metadata
# ══════════════════════════════════════════════════════════════

class TestRegistryListing:
    """List and metadata queries."""

    @pytest.mark.unit
    def test_list_all_modules(self):
        """list_modules() returns full catalog structure."""
        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", lambda: None, requires_gpu=True)
        reg.register("tts", "kokoro", lambda: None, requires_gpu=True)
        reg.register("llm", "ollama", lambda: None, requires_gpu=False)

        modules = reg.list_modules()
        assert "stt" in modules
        assert "tts" in modules
        assert "llm" in modules
        assert "faster-whisper" in modules["stt"]
        assert modules["stt"]["faster-whisper"]["requires_gpu"] is True

    @pytest.mark.unit
    def test_list_by_kind(self):
        """list_modules(kind) returns only that kind."""
        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", lambda: None, version="1.1")
        reg.register("tts", "kokoro", lambda: None, version="0.9")

        stt_modules = reg.list_modules(kind="stt")
        assert "faster-whisper" in stt_modules
        assert "kokoro" not in stt_modules

    @pytest.mark.unit
    def test_list_unknown_kind(self):
        """list_modules for unknown kind returns empty dict."""
        reg = ModuleRegistry()
        assert reg.list_modules(kind="nonexistent") == {}

    @pytest.mark.unit
    def test_metadata(self):
        """get_metadata returns registered metadata."""
        reg = ModuleRegistry()
        reg.register("stt", "faster-whisper", lambda: None,
                     requires_gpu=True, description="Whisper STT")

        meta = reg.get_metadata("stt", "faster-whisper")
        assert meta["requires_gpu"] is True
        assert meta["description"] == "Whisper STT"


# ══════════════════════════════════════════════════════════════
#  Override & Immutability Semantics
# ══════════════════════════════════════════════════════════════

class TestRegistryOverride:
    """Registration override behavior."""

    @pytest.mark.unit
    def test_register_override(self):
        """Registering same kind/name twice overrides the factory."""
        factory_a = MagicMock(return_value="engine_a")
        factory_b = MagicMock(return_value="engine_b")

        reg = ModuleRegistry()
        reg.register("stt", "whisper", factory_a)
        reg.register("stt", "whisper", factory_b)

        result = reg.create("stt", "whisper")
        assert result == "engine_b"
        factory_b.assert_called_once()
        factory_a.assert_not_called()

    @pytest.mark.unit
    def test_multiple_kinds(self):
        """Multiple kinds can coexist independently."""
        reg = ModuleRegistry()
        reg.register("stt", "whisper", MagicMock(return_value="stt"))
        reg.register("tts", "kokoro", MagicMock(return_value="tts"))
        reg.register("llm", "ollama", MagicMock(return_value="llm"))
        reg.register("capture", "dxcam", MagicMock(return_value="cap"))

        assert reg.create("stt", "whisper") == "stt"
        assert reg.create("tts", "kokoro") == "tts"
        assert reg.create("llm", "ollama") == "llm"
        assert reg.create("capture", "dxcam") == "cap"

    @pytest.mark.unit
    def test_factory_exception_propagates(self):
        """Factory exception propagates to caller — no silent failure."""
        def bad_factory(cfg):
            raise RuntimeError("GPU not available")

        reg = ModuleRegistry()
        reg.register("stt", "broken", bad_factory)

        with pytest.raises(RuntimeError, match="GPU not available"):
            reg.create("stt", "broken", MagicMock())
