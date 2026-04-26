"""
VoxDesk — Startup & Registry Integration Tests
main.py startup refactor doğrulaması:
- Factory'ler sadece startup'ta çağrılıyor mu?
- Request path'te registry.create çağrılmıyor mu?
- Geçersiz engine config fail-fast mı?
- Health endpoint registry/model/vram sızdırmıyor mu?
- Shutdown cleanup izole try/except ile mi?
"""

import pytest
import inspect
from unittest.mock import MagicMock, patch

from src.registry import ModuleRegistry


# ══════════════════════════════════════════════════════════════
#  Startup Factory Registration
# ══════════════════════════════════════════════════════════════

class TestStartupRegistration:
    """Registry factory registration at startup."""

    @pytest.mark.unit
    def test_register_default_factories_populates_catalog(self):
        """_register_default_factories tüm 4 kind'ı kaydetmeli."""
        from src.main import _register_default_factories

        registry = ModuleRegistry()
        _register_default_factories(registry)

        modules = registry.list_modules()
        assert "capture" in modules, "capture kind eksik"
        assert "llm" in modules, "llm kind eksik"
        assert "stt" in modules, "stt kind eksik"
        assert "tts" in modules, "tts kind eksik"

    @pytest.mark.unit
    def test_default_factories_match_config_defaults(self):
        """Default config engine/provider değerleri registry'de kayıtlı olmalı."""
        from src.main import _register_default_factories
        from src.config import AppConfig

        registry = ModuleRegistry()
        _register_default_factories(registry)
        config = AppConfig()

        # Config default'ları registry'de var mı?
        assert registry.exists("capture", config.capture.backend), \
            f"capture/{config.capture.backend} registry'de yok"
        assert registry.exists("llm", config.llm.provider), \
            f"llm/{config.llm.provider} registry'de yok"
        assert registry.exists("stt", config.stt.engine), \
            f"stt/{config.stt.engine} registry'de yok"
        assert registry.exists("tts", config.tts.engine), \
            f"tts/{config.tts.engine} registry'de yok"

    @pytest.mark.unit
    def test_factory_creates_correct_type(self):
        """Factory'ler doğru tipteki engine döndürmeli."""
        from src.main import _register_default_factories
        from src.config import STTConfig, TTSConfig

        registry = ModuleRegistry()
        _register_default_factories(registry)

        # STT — factory'nin SpeechRecognizer döndürdüğünü doğrula
        from src.stt import SpeechRecognizer
        stt_cfg = STTConfig()
        stt = registry.create("stt", "faster-whisper", stt_cfg)
        assert isinstance(stt, SpeechRecognizer)

        # TTS
        from src.tts import VoiceSynth
        tts_cfg = TTSConfig()
        tts = registry.create("tts", "kokoro", tts_cfg)
        assert isinstance(tts, VoiceSynth)


# ══════════════════════════════════════════════════════════════
#  Request Path Safety
# ══════════════════════════════════════════════════════════════

class TestRequestPathSafety:
    """Request path'te registry.create çağrılmadığını doğrula."""

    @pytest.mark.regression
    def test_routes_do_not_import_registry(self):
        """Route dosyaları doğrudan registry import etmemeli."""
        from pathlib import Path

        routes_dir = Path(__file__).parent.parent / "src" / "routes"
        for py_file in routes_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text(encoding="utf-8")
            assert "registry.create" not in content, \
                f"{py_file.name} request path'te registry.create çağırıyor!"
            assert "from src.registry" not in content, \
                f"{py_file.name} route dosyasında registry import edilmiş!"

    @pytest.mark.regression
    def test_routes_use_get_app_state(self):
        """Route dosyaları get_app_state() üzerinden instance'lara erişmeli."""
        from pathlib import Path

        routes_dir = Path(__file__).parent.parent / "src" / "routes"
        for py_file in routes_dir.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            content = py_file.read_text(encoding="utf-8")
            # Route'lar ya get_app_state ya da state parametresi kullanmalı
            if "def " in content:  # Endpoint tanımlı
                assert "get_app_state" in content or "state" in content, \
                    f"{py_file.name} app state erişimi bulunamadı"


# ══════════════════════════════════════════════════════════════
#  Config Validation — Fail-Fast
# ══════════════════════════════════════════════════════════════

class TestConfigFailFast:
    """Geçersiz config fail-fast davranmalı."""

    @pytest.mark.unit
    def test_invalid_engine_fails_registry_create(self):
        """Kayıtlı olmayan engine registry.create'te KeyError vermeli."""
        from src.main import _register_default_factories

        registry = ModuleRegistry()
        _register_default_factories(registry)

        with pytest.raises(KeyError, match="bulunamadı"):
            registry.create("stt", "nonexistent-engine", MagicMock())

    @pytest.mark.unit
    def test_extra_config_field_rejected(self):
        """extra='forbid' ile bilinmeyen config field'ı ValidationError vermeli."""
        from pydantic import ValidationError
        from src.config import STTConfig

        with pytest.raises(ValidationError):
            STTConfig(engine="faster-whisper", unknown_field="value")

    @pytest.mark.unit
    def test_extra_appconfig_field_rejected(self):
        """AppConfig'te bilinmeyen field ValidationError vermeli."""
        from pydantic import ValidationError
        from src.config import AppConfig

        with pytest.raises(ValidationError):
            AppConfig(nonexistent_section="value")


# ══════════════════════════════════════════════════════════════
#  Shutdown Cleanup
# ══════════════════════════════════════════════════════════════

class TestShutdownCleanup:
    """Shutdown cleanup izole try/except ile çalışmalı."""

    @pytest.mark.unit
    def test_safe_shutdown_function_exists(self):
        """_safe_shutdown fonksiyonu var olmalı."""
        from src.main import _safe_shutdown
        assert callable(_safe_shutdown)

    @pytest.mark.unit
    def test_safe_shutdown_source_has_try_except(self):
        """_safe_shutdown her bileşen için try/except kullanmalı."""
        from src.main import _safe_shutdown

        source = inspect.getsource(_safe_shutdown)
        # En az 4 bileşen için izole try/except olmalı
        try_count = source.count("try:")
        except_count = source.count("except Exception")
        assert try_count >= 4, f"try bloğu {try_count} < 4 — izolasyon yetersiz"
        assert except_count >= 4, f"except bloğu {except_count} < 4 — izolasyon yetersiz"

    @pytest.mark.unit
    def test_safe_shutdown_handles_none_state(self):
        """_safe_shutdown _state=None iken crash etmemeli."""
        import asyncio
        import src.main as main_mod
        original_state = main_mod._state

        try:
            main_mod._state = None
            # _safe_shutdown is async — run it properly
            asyncio.run(main_mod._safe_shutdown())
        finally:
            main_mod._state = original_state

    @pytest.mark.unit
    def test_lifespan_source_has_raise(self):
        """lifespan() startup hatası raise etmeli — sessizce yutmamalı."""
        from src.main import lifespan
        source = inspect.getsource(lifespan)
        assert "raise" in source, "lifespan startup hatasını yutmamalı"


# ══════════════════════════════════════════════════════════════
#  AppState + Registry Consistency
# ══════════════════════════════════════════════════════════════

class TestAppStateRegistry:
    """AppState ve Registry tutarlılığı."""

    @pytest.mark.unit
    def test_appstate_has_registry_field(self):
        """AppState'te registry field'ı olmalı."""
        from src.main import AppState
        state = AppState()
        assert hasattr(state, "registry")
        assert isinstance(state.registry, ModuleRegistry)

    @pytest.mark.unit
    def test_appstate_registry_is_not_singleton(self):
        """Her AppState kendi registry instance'ına sahip olmalı."""
        from src.main import AppState
        s1 = AppState()
        s2 = AppState()
        assert s1.registry is not s2.registry
