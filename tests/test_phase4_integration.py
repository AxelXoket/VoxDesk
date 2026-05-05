"""
VoxDesk — Phase 4 Integration Tests
STT/TTS ManagedModel lifecycle, VRAM manager wiring, config validation.
GERÇEK MODEL YÜKLEME YOK — tüm testler mock/fake ile.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.model_state import ModelState
from src.config import AppConfig, VRAMConfig


# ══════════════════════════════════════════════════════════════
#  STT Safe Unload Guards
# ══════════════════════════════════════════════════════════════

class TestSTTLifecycle:
    """SpeechRecognizer ManagedModel lifecycle."""

    @pytest.mark.unit
    def test_stt_has_lifecycle_methods(self):
        """SpeechRecognizer close/health/safe_unload/acquire/release sahip olmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        assert callable(stt.close)
        assert callable(stt.health)
        assert callable(stt.safe_unload)
        assert callable(stt.acquire)
        assert callable(stt.release)

    @pytest.mark.unit
    def test_stt_initial_state(self):
        """STT başlangıç state'i UNLOADED olmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        h = stt.health()
        assert h["state"] == "unloaded"
        assert h["ref_count"] == 0
        assert h["is_listening"] is False

    @pytest.mark.unit
    def test_stt_safe_unload_blocks_when_active(self):
        """Aktif transcribe sırasında safe_unload False dönmeli."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(
            activation_threshold_db=-30.0,
            min_loaded_seconds=0,
            unload_cooldown_seconds=0,
        )

        # Manuel load + acquire (transcribe simülasyonu)
        # _do_load yapamayız (model yok) — lifecycle state'i elle set edelim
        stt._lifecycle._state = ModelState.LOADED
        stt._lifecycle._loaded_at = 0
        stt._lifecycle._last_used = 0

        stt.acquire()
        assert stt._lifecycle.ref_count == 1
        assert stt._lifecycle.state == ModelState.IN_USE

        # Safe unload reddedilmeli
        assert stt.safe_unload() is False

        stt.release()
        assert stt._lifecycle.ref_count == 0

        # Artık unload yapılabilmeli
        assert stt.safe_unload() is True

    @pytest.mark.unit
    def test_stt_close_calls_lifecycle_close(self):
        """close() lifecycle.close() çağırmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(activation_threshold_db=-30.0)

        # close — no crash on unloaded
        stt.close()
        assert stt._lifecycle.state == ModelState.UNLOADED


# ══════════════════════════════════════════════════════════════
#  TTS Safe Unload Guards
# ══════════════════════════════════════════════════════════════

class TestTTSLifecycle:
    """VoiceSynth ManagedModel lifecycle."""

    @pytest.mark.unit
    def test_tts_has_lifecycle_methods(self):
        """VoiceSynth close/health/safe_unload/acquire/release sahip olmalı."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(enabled=False)
        assert callable(tts.close)
        assert callable(tts.health)
        assert callable(tts.safe_unload)
        assert callable(tts.acquire)
        assert callable(tts.release)

    @pytest.mark.unit
    def test_tts_initial_state(self):
        """TTS başlangıç state'i UNLOADED olmalı."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(enabled=False)
        h = tts.health()
        assert h["state"] == "unloaded"
        assert h["ref_count"] == 0
        assert h["enabled"] is False
        assert h["voice"] == "af_heart"

    @pytest.mark.unit
    def test_tts_safe_unload_blocks_when_active(self):
        """Aktif synthesize sırasında safe_unload False dönmeli."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(
            enabled=True,
            min_loaded_seconds=0,
            unload_cooldown_seconds=0,
        )

        # Manuel state set (model yüklemeden)
        tts._lifecycle._state = ModelState.LOADED
        tts._lifecycle._loaded_at = 0
        tts._lifecycle._last_used = 0

        tts.acquire()
        assert tts._lifecycle.ref_count == 1

        assert tts.safe_unload() is False

        tts.release()
        assert tts.safe_unload() is True

    @pytest.mark.unit
    def test_tts_close_calls_lifecycle_close(self):
        """close() lifecycle.close() çağırmalı."""
        from src.tts import VoiceSynth
        tts = VoiceSynth(enabled=False)
        tts.close()
        assert tts._lifecycle.state == ModelState.UNLOADED


# ══════════════════════════════════════════════════════════════
#  VRAM Manager Registered Models Report
# ══════════════════════════════════════════════════════════════

class TestVRAMManagerWithEngines:
    """VRAMManager STT/TTS model kayıtları."""

    @pytest.mark.unit
    def test_vram_manager_registered_models_report_state(self):
        """Register edilen model'lerin state'i raporda görünmeli."""
        from src.vram_manager import VRAMManager
        from src.stt import SpeechRecognizer
        from src.tts import VoiceSynth

        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        tts = VoiceSynth(enabled=False)

        vm = VRAMManager()
        vm.register_model("stt", stt._lifecycle)
        vm.register_model("tts", tts._lifecycle)

        report = vm.get_report()
        assert "stt" in report["models"]
        assert "tts" in report["models"]
        assert report["models"]["stt"]["state"] == "unloaded"
        assert report["models"]["tts"]["state"] == "unloaded"

    @pytest.mark.unit
    def test_vram_manager_per_model_timeout(self):
        """Per-model idle timeout kaydı çalışmalı."""
        from src.vram_manager import VRAMManager
        from src.stt import SpeechRecognizer

        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        vm = VRAMManager(idle_timeout_seconds=120.0)
        vm.register_model("stt", stt._lifecycle, idle_timeout_seconds=300.0)

        assert vm._model_timeouts["stt"] == 300.0

    @pytest.mark.unit
    def test_vram_manager_unregister_clears_timeout(self):
        """unregister_model per-model timeout'u da temizlemeli."""
        from src.vram_manager import VRAMManager
        from src.stt import SpeechRecognizer

        stt = SpeechRecognizer(activation_threshold_db=-30.0)
        vm = VRAMManager()
        vm.register_model("stt", stt._lifecycle, idle_timeout_seconds=300.0)
        vm.unregister_model("stt")

        assert "stt" not in vm._model_timeouts
        assert "stt" not in vm._models


# ══════════════════════════════════════════════════════════════
#  Translator Lifecycle
# ══════════════════════════════════════════════════════════════

class TestTranslatorLifecycle:
    """Translator ManagedModel lifecycle."""

    @pytest.mark.unit
    def test_translator_has_lifecycle_methods(self):
        """Translator close/health/safe_unload/acquire/release sahip olmalı."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model", enabled=True)
        assert callable(tr.close)
        assert callable(tr.health)
        assert callable(tr.safe_unload)
        assert callable(tr.acquire)
        assert callable(tr.release)

    @pytest.mark.unit
    def test_translator_initial_state(self):
        """Translator başlangıç state'i UNLOADED olmalı."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model")
        h = tr.health()
        assert h["state"] == "unloaded"
        assert h["ref_count"] == 0
        assert h["enabled"] is True
        assert h["model_path"] == "models/fake-model"

    @pytest.mark.unit
    def test_translator_close_no_crash(self):
        """close() unloaded state'te crash etmemeli."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model")
        tr.close()  # No exception
        assert tr._lifecycle.state == ModelState.UNLOADED

    @pytest.mark.unit
    def test_translator_bypass_english(self):
        """source_lang='en' ise çeviri yapmamalı (identity return)."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model")
        result = tr.translate("Hello world", "en")
        assert result == "Hello world"

    @pytest.mark.unit
    def test_translator_bypass_disabled(self):
        """enabled=False ise çeviri yapmamalı."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model", enabled=False)
        result = tr.translate("Merhaba dünya", "tr")
        assert result == "Merhaba dünya"

    @pytest.mark.unit
    def test_translator_bypass_empty(self):
        """Boş metin bypass edilmeli."""
        from src.translator import Translator
        tr = Translator(model_path="models/fake-model")
        result = tr.translate("", "tr")
        assert result == ""
        result2 = tr.translate("   ", "tr")
        assert result2 == "   "

    @pytest.mark.unit
    def test_translator_safe_unload_blocks_when_active(self):
        """Aktif çeviri sırasında safe_unload False dönmeli."""
        from src.translator import Translator
        tr = Translator(
            model_path="models/fake-model",
            min_loaded_seconds=0,
            unload_cooldown_seconds=0,
        )
        # Manuel state — gerçek model yükleme olmadan
        tr._lifecycle._state = ModelState.LOADED
        tr._lifecycle._loaded_at = 0
        tr._lifecycle._last_used = 0

        tr.acquire()
        assert tr._lifecycle.ref_count == 1
        assert tr._lifecycle.state == ModelState.IN_USE
        assert tr.safe_unload() is False

        tr.release()
        assert tr._lifecycle.ref_count == 0
        assert tr.safe_unload() is True

    @pytest.mark.unit
    def test_translator_vram_manager_registration(self):
        """Translator VRAMManager'a register edilebilmeli."""
        from src.vram_manager import VRAMManager
        from src.translator import Translator

        tr = Translator(model_path="models/fake-model")
        vm = VRAMManager()
        vm.register_model("translator", tr._lifecycle, idle_timeout_seconds=180.0)

        report = vm.get_report()
        assert "translator" in report["models"]
        assert report["models"]["translator"]["state"] == "unloaded"
        assert vm._model_timeouts["translator"] == 180.0


# ══════════════════════════════════════════════════════════════
#  Translator Config
# ══════════════════════════════════════════════════════════════

class TestTranslatorConfig:
    """TranslatorConfig validation."""

    @pytest.mark.unit
    def test_translator_config_defaults(self):
        """TranslatorConfig defaults doğru olmalı."""
        from src.config import TranslatorConfig
        cfg = TranslatorConfig()
        assert cfg.engine == "marian"
        assert cfg.model_path == "models/opus-mt-tr-en"
        assert cfg.device == "cuda"
        assert cfg.enabled is False  # LLM handles multilingual natively \u2014 translator dormant

    @pytest.mark.unit
    def test_translator_config_extra_forbid(self):
        """TranslatorConfig bilinmeyen field'ı reddetmeli."""
        from src.config import TranslatorConfig
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            TranslatorConfig(unknown_field="value")

    @pytest.mark.unit
    def test_appconfig_has_translator(self):
        """AppConfig'te translator section'ı olmalı."""
        from src.config import TranslatorConfig
        cfg = AppConfig()
        assert hasattr(cfg, "translator")
        assert isinstance(cfg.translator, TranslatorConfig)

    @pytest.mark.regression
    def test_translator_local_files_only_enforced(self):
        """Translator from_pretrained local_files_only=True kullanmalı."""
        import ast
        source = Path(__file__).parent.parent / "src" / "translator.py"
        content = source.read_text(encoding="utf-8")
        tree = ast.parse(content)

        # from_pretrained çağrılarını bul
        calls_found = 0
        local_files_only_found = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "from_pretrained":
                    calls_found += 1
                    for kw in node.keywords:
                        if kw.arg == "local_files_only":
                            local_files_only_found += 1

        assert calls_found >= 2, "from_pretrained en az 2 kez çağrılmalı"
        assert local_files_only_found == calls_found, (
            f"from_pretrained çağrılarının hepsi local_files_only=True kullanmalı "
            f"({local_files_only_found}/{calls_found})"
        )


# ══════════════════════════════════════════════════════════════
#  Config VRAM Defaults
# ══════════════════════════════════════════════════════════════

class TestVRAMConfig:
    """VRAMConfig validation."""

    @pytest.mark.unit
    def test_vram_config_defaults(self):
        """VRAMConfig defaults güvenli olmalı."""
        cfg = VRAMConfig()
        assert cfg.monitor_interval_seconds == 30.0
        assert cfg.stt_idle_unload_seconds == 180.0
        assert cfg.tts_idle_unload_seconds == 180.0
        assert cfg.translator_idle_unload_seconds == 180.0
        assert cfg.min_loaded_seconds == 30.0
        assert cfg.unload_cooldown_seconds == 10.0
        assert cfg.keep_warm is False

    @pytest.mark.unit
    def test_vram_config_extra_forbid(self):
        """VRAMConfig bilinmeyen field'ı reddetmeli."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            VRAMConfig(unknown_field="value")

    @pytest.mark.unit
    def test_appconfig_has_vram_section(self):
        """AppConfig'te vram section'ı olmalı."""
        cfg = AppConfig()
        assert hasattr(cfg, "vram")
        assert isinstance(cfg.vram, VRAMConfig)

    @pytest.mark.unit
    def test_appstate_has_vram_manager_field(self):
        """AppState'te vram_manager field'ı olmalı."""
        from src.main import AppState
        state = AppState()
        assert hasattr(state, "vram_manager")


# ══════════════════════════════════════════════════════════════
#  No Runtime Model Download Guard
# ══════════════════════════════════════════════════════════════

class TestNoRuntimeDownload:
    """Phase 4 testlerinde gerçek model indirme olmamalı."""

    @pytest.mark.regression
    def test_no_runtime_model_download_in_vram_tests(self):
        """
        Test sırasında from_pretrained / snapshot_download çağrılmamalı.
        Bu test import tarama yaparak doğrular.
        """
        test_dir = Path(__file__).parent
        download_patterns = [
            "from_pretrained(",
            "snapshot_download(",
            ".download(",
            "hf_hub_download(",
        ]

        violations = []
        for py_file in test_dir.rglob("test_*vram*.py"):
            content = py_file.read_text(encoding="utf-8")
            for pattern in download_patterns:
                if pattern in content:
                    violations.append(f"{py_file.name}: {pattern}")

        for py_file in test_dir.rglob("test_*model_state*.py"):
            content = py_file.read_text(encoding="utf-8")
            for pattern in download_patterns:
                if pattern in content:
                    violations.append(f"{py_file.name}: {pattern}")

        assert not violations, \
            f"Phase 4 testlerinde runtime model download bulundu:\n" + \
            "\n".join(f"  - {v}" for v in violations)
