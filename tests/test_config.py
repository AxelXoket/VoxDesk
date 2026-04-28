"""
VoxDesk — Config Module Tests
Pydantic model defaults, YAML loading, personality parsing, singleton lifecycle.
Hardware/internet gerektirmez.
"""

import pytest
import yaml
from pathlib import Path

from src.config import (
    AppConfig,
    CaptureConfig,
    LLMConfig,
    TTSConfig,
    STTConfig,
    VoiceActivationConfig,
    HotkeyConfig,
    HistoryConfig,
    PersonalityConfig,
    PrivacyConfig,
    NetworkConfig,
    ModelLoadingConfig,
    FeaturesConfig,
    SecurityConfig,
    VRAMConfig,
    load_personality,
    load_config,
)


# ── Pydantic Model Defaults ─────────────────────────────────

class TestConfigDefaults:
    """Her config model'inin default değerleri doğru mu?"""

    def test_app_config_defaults(self):
        cfg = AppConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 8765
        assert cfg.debug is False
        assert cfg.name == "VoxDesk"

    def test_capture_defaults(self):
        cfg = CaptureConfig()
        assert cfg.interval_seconds == 1.0
        assert cfg.buffer_size == 30
        assert cfg.jpeg_quality == 85
        assert cfg.resize_width == 1920

    def test_llm_defaults(self):
        cfg = LLMConfig()
        assert cfg.provider == "llama-cpp"
        assert cfg.model_path is None
        assert cfg.mmproj_path is None
        assert cfg.n_gpu_layers == -1
        assert cfg.n_ctx == 8192
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 2048
        assert cfg.context_messages == 10

    def test_tts_defaults(self):
        cfg = TTSConfig()
        assert cfg.engine == "kokoro"
        assert cfg.voice == "af_heart"
        assert cfg.speed == 1.0
        assert cfg.lang_code == "a"
        assert cfg.enabled is True

    def test_stt_defaults(self):
        cfg = STTConfig()
        assert cfg.engine == "faster-whisper"
        assert cfg.model == "large-v3-turbo"
        assert cfg.device == "cuda"
        assert cfg.compute_type == "float16"
        assert cfg.language is None  # auto-detect
        assert cfg.vad_enabled is True

    def test_voice_activation_defaults(self):
        cfg = VoiceActivationConfig()
        assert cfg.enabled is False
        assert cfg.threshold_db == -30.0

    def test_hotkey_defaults(self):
        cfg = HotkeyConfig()
        assert cfg.activate == "ctrl+shift+space"
        assert cfg.toggle_listen == "ctrl+shift+v"
        assert cfg.push_to_talk == "ctrl+shift+b"

    def test_history_defaults(self):
        cfg = HistoryConfig()
        assert cfg.max_messages == 500
        assert cfg.auto_save is False
        assert "history" in cfg.save_path

    def test_personality_defaults(self):
        cfg = PersonalityConfig()
        assert cfg.name == "Voxly"
        assert cfg.language == "both"
        assert cfg.voice == "af_heart"
        assert cfg.tone == "professional"
        assert cfg.system_prompt == ""
        assert len(cfg.greeting) > 0


# ── Nested AppConfig ─────────────────────────────────────────

class TestAppConfigNesting:
    """AppConfig alt-modelleri doğru bağlıyor mu?"""

    def test_nested_sub_configs_exist(self):
        cfg = AppConfig()
        assert isinstance(cfg.capture, CaptureConfig)
        assert isinstance(cfg.llm, LLMConfig)
        assert isinstance(cfg.tts, TTSConfig)
        assert isinstance(cfg.stt, STTConfig)
        assert isinstance(cfg.voice_activation, VoiceActivationConfig)
        assert isinstance(cfg.hotkeys, HotkeyConfig)
        assert isinstance(cfg.history, HistoryConfig)
        assert isinstance(cfg.personality, PersonalityConfig)

    def test_host_is_localhost(self):
        """İzolasyon: host her zaman 127.0.0.1 olmalı."""
        cfg = AppConfig()
        assert cfg.host == "127.0.0.1"

    def test_custom_override(self):
        """Pydantic model_validate ile custom değer override."""
        cfg = AppConfig(port=9999, debug=True)
        assert cfg.port == 9999
        assert cfg.debug is True
        # Geri kalanlar default kalmalı
        assert cfg.host == "127.0.0.1"

    def test_nested_override(self):
        """Alt-config override — capture interval."""
        cfg = AppConfig(capture=CaptureConfig(interval_seconds=0.5))
        assert cfg.capture.interval_seconds == 0.5
        # Diğer alt-config'ler default kalmalı
        assert cfg.llm.provider == LLMConfig().provider

    def test_personality_name_default(self):
        cfg = AppConfig()
        assert cfg.personality_name == "voxly"


# ── Personality Loading ──────────────────────────────────────

class TestPersonalityLoading:
    """Personality YAML dosya yükleme."""

    def test_load_personality_from_yaml(self, tmp_path):
        """Geçerli YAML'dan personality yüklenebiliyor mu?"""
        p_file = tmp_path / "test_persona.yaml"
        p_file.write_text(
            yaml.dump({
                "name": "TestBot",
                "language": "en",
                "voice": "am_adam",
                "tone": "professional",
                "greeting": "Hello!",
                "system_prompt": "You are a test bot.",
            }),
            encoding="utf-8",
        )

        # load_personality PERSONALITIES_DIR kullanıyor — monkey-patch
        import src.config as cfg_module
        original_dir = cfg_module.PERSONALITIES_DIR
        cfg_module.PERSONALITIES_DIR = tmp_path
        try:
            p = load_personality("test_persona")
            assert p.name == "TestBot"
            assert p.voice == "am_adam"
            assert p.tone == "professional"
            assert p.greeting == "Hello!"
            assert p.system_prompt == "You are a test bot."
            assert p.language == "en"
        finally:
            cfg_module.PERSONALITIES_DIR = original_dir

    def test_load_personality_not_found(self):
        """Var olmayan personality → FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_personality("nonexistent_persona_xyz_123")

    def test_personality_partial_yaml(self, tmp_path):
        """Eksik alanlar default'a düşmeli."""
        p_file = tmp_path / "minimal.yaml"
        p_file.write_text(
            yaml.dump({"name": "MinimalBot"}),
            encoding="utf-8",
        )

        import src.config as cfg_module
        original_dir = cfg_module.PERSONALITIES_DIR
        cfg_module.PERSONALITIES_DIR = tmp_path
        try:
            p = load_personality("minimal")
            assert p.name == "MinimalBot"
            assert p.voice == "af_heart"  # default
            assert p.tone == "professional"   # default
            assert p.system_prompt == ""  # default
        finally:
            cfg_module.PERSONALITIES_DIR = original_dir

    def test_personality_empty_yaml(self, tmp_path):
        """Boş YAML → tüm default'lar kullanılmalı."""
        p_file = tmp_path / "empty.yaml"
        p_file.write_text("{}", encoding="utf-8")

        import src.config as cfg_module
        original_dir = cfg_module.PERSONALITIES_DIR
        cfg_module.PERSONALITIES_DIR = tmp_path
        try:
            p = load_personality("empty")
            assert p.name == "Voxly"  # default personality name
        finally:
            cfg_module.PERSONALITIES_DIR = original_dir


# ── Config Loading ───────────────────────────────────────────

class TestConfigLoading:
    """load_config() doğru YAML parse ediyor mu?"""

    def test_load_config_returns_app_config(self):
        """load_config() bir AppConfig döndürmeli."""
        cfg = load_config()
        assert isinstance(cfg, AppConfig)
        assert cfg.host == "127.0.0.1"

    def test_config_singleton(self):
        """get_config() tekil instance döndürmeli."""
        from src.config import get_config
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reload_config_creates_new(self):
        """reload_config() yeni bir instance oluşturmalı."""
        from src.config import get_config, reload_config
        c1 = get_config()
        c2 = reload_config()
        assert isinstance(c2, AppConfig)
        # Reload sonrası get_config yeni instance'ı döndürmeli
        c3 = get_config()
        assert c3 is c2


# ── Sprint 1 — Config Mapping Tests ──────────────────────────

class TestConfigMappingSprint1:
    """Sprint 1 Gap 5: load_config() maps all 6 previously-missing sections."""

    def _make_yaml_and_load(self, tmp_path, yaml_content: dict):
        """Helper: write yaml, point load_config at it, return AppConfig."""
        import src.config as cfg_module

        config_file = tmp_path / "default.yaml"
        config_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        personalities_dir = tmp_path / "personalities"
        personalities_dir.mkdir(exist_ok=True)
        (personalities_dir / "voxly.yaml").write_text(
            yaml.dump({"name": "Voxly", "greeting": "Hi"}),
            encoding="utf-8",
        )

        orig_default = cfg_module.DEFAULT_CONFIG
        orig_personalities = cfg_module.PERSONALITIES_DIR
        orig_config = cfg_module._config
        try:
            cfg_module.DEFAULT_CONFIG = config_file
            cfg_module.PERSONALITIES_DIR = personalities_dir
            cfg_module._config = None
            return load_config()
        finally:
            cfg_module.DEFAULT_CONFIG = orig_default
            cfg_module.PERSONALITIES_DIR = orig_personalities
            cfg_module._config = orig_config

    @pytest.mark.regression
    def test_maps_features_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "features": {"enable_debug_metrics": True, "enable_vram_unload": True},
        })
        assert cfg.features.enable_debug_metrics is True
        assert cfg.features.enable_vram_unload is True
        # Unmapped fields keep defaults
        assert cfg.features.enable_module_registry is True

    @pytest.mark.regression
    def test_maps_network_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "network": {"bind_host": "0.0.0.0"},
        })
        assert cfg.network.bind_host == "0.0.0.0"
        assert len(cfg.network.allowed_ws_origins) >= 1

    @pytest.mark.regression
    def test_maps_privacy_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "privacy": {"offline_mode": False},
        })
        assert cfg.privacy.offline_mode is False
        assert cfg.privacy.allow_cloud_providers is False  # default

    @pytest.mark.regression
    def test_maps_model_loading_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "model_loading": {"local_files_only": False},
        })
        assert cfg.model_loading.local_files_only is False
        assert cfg.model_loading.fail_if_model_missing is True  # default

    @pytest.mark.regression
    def test_maps_security_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "security": {"max_ws_frame_bytes": 32768},
        })
        assert cfg.security.max_ws_frame_bytes == 32768
        assert cfg.security.idle_disconnect_seconds == 300  # default

    @pytest.mark.regression
    def test_maps_vram_section(self, tmp_path):
        cfg = self._make_yaml_and_load(tmp_path, {
            "vram": {"monitor_interval_seconds": 10.0, "keep_warm": True},
        })
        assert cfg.vram.monitor_interval_seconds == 10.0
        assert cfg.vram.keep_warm is True
        assert cfg.vram.stt_idle_unload_seconds == 180.0  # default (3 dk)

    @pytest.mark.regression
    def test_missing_sections_use_defaults(self, tmp_path):
        """YAML with no new sections → Pydantic defaults."""
        cfg = self._make_yaml_and_load(tmp_path, {})
        assert cfg.features.enable_debug_metrics is False
        assert cfg.network.bind_host == "127.0.0.1"
        assert cfg.privacy.offline_mode is True
        assert cfg.model_loading.local_files_only is True
        assert cfg.security.max_ws_frame_bytes == 65536
        assert cfg.vram.monitor_interval_seconds == 30.0

    @pytest.mark.regression
    def test_unknown_keys_rejected_by_extra_forbid(self, tmp_path):
        """extra='forbid' must reject unknown keys."""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            self._make_yaml_and_load(tmp_path, {
                "features": {"nonexistent_flag": True},
            })
