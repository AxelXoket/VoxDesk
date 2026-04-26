"""
VoxDesk — Configuration Management
Pydantic Settings ile merkezi yapılandırma.
"""

from __future__ import annotations

import yaml
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field


CONFIG_DIR = Path(__file__).parent.parent / "config"
DEFAULT_CONFIG = CONFIG_DIR / "default.yaml"
PERSONALITIES_DIR = CONFIG_DIR / "personalities"


class CaptureConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    backend: str = "dxcam"
    interval_seconds: float = 1.0
    buffer_size: int = 30
    jpeg_quality: int = 85
    resize_width: int = 1920


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: str = "ollama"
    model: str = "huihui-ai/minicpm-v4.5-abliterated"
    fallback_models: list[str] = Field(default_factory=lambda: [
        "AliBilge/GLM-4.6V-Flash-abliterated",
        "gemma4:e4b",
    ])
    temperature: float = 0.7
    max_tokens: int = 2048
    context_messages: int = 10


class TTSConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    engine: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0
    lang_code: str = "a"
    enabled: bool = True


class STTConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    engine: str = "faster-whisper"
    model: str = "large-v3-turbo"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None  # None = auto-detect
    vad_enabled: bool = True


class VoiceActivationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    threshold_db: float = -30.0


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    activate: str = "ctrl+shift+space"
    toggle_listen: str = "ctrl+shift+v"
    push_to_talk: str = "ctrl+shift+b"


class HistoryConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_messages: int = 500
    auto_save: bool = False
    save_path: str = "./data/history/"


class PersonalityConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = "Voxly"
    language: str = "both"
    voice: str = "af_heart"
    tone: str = "professional"
    greeting: str = "Hello! Voxly is online and ready to assist."
    system_prompt: str = ""


# ── Privacy & Security Configs ───────────────────────────────

class PrivacyConfig(BaseModel):
    """Local-only runtime contract — hiçbir veri dışarı çıkmaz."""
    model_config = ConfigDict(extra='forbid')
    offline_mode: bool = True
    allow_cloud_providers: bool = False
    allow_runtime_model_downloads: bool = False
    allow_external_telemetry: bool = False
    allow_cdn_assets: bool = False


class NetworkConfig(BaseModel):
    """Network binding & origin restrictions."""
    model_config = ConfigDict(extra='forbid')
    bind_host: str = "127.0.0.1"
    allowed_ws_origins: list[str] = Field(default_factory=lambda: [
        "http://127.0.0.1:*",
        "http://localhost:*",
    ])


class ModelLoadingConfig(BaseModel):
    """Model loading policy — no runtime downloads."""
    model_config = ConfigDict(extra='forbid')
    local_files_only: bool = True
    fail_if_model_missing: bool = True


class FeaturesConfig(BaseModel):
    """Feature flags — restart-only, no runtime toggle."""
    model_config = ConfigDict(extra='forbid')
    enable_module_registry: bool = True
    enable_vram_unload: bool = False
    enable_binary_audio: bool = False
    enable_audioworklet: bool = False
    enable_mediarecorder_fallback: bool = True
    enable_debug_metrics: bool = False


class SecurityConfig(BaseModel):
    """Runtime security limits."""
    model_config = ConfigDict(extra='forbid')
    max_ws_frame_bytes: int = 65536
    max_audio_queue_depth: int = 50
    max_json_message_bytes: int = 65536
    idle_disconnect_seconds: int = 300
    max_messages_per_second: int = 60


class VRAMConfig(BaseModel):
    """
    VRAM / model lifecycle configuration.
    0 = ilgili unload devre dışı (sonsuz).
    """
    model_config = ConfigDict(extra='forbid')
    monitor_interval_seconds: float = 30.0
    stt_idle_unload_seconds: float = 120.0   # 0 = disable
    tts_idle_unload_seconds: float = 120.0   # 0 = disable
    min_loaded_seconds: float = 30.0
    unload_cooldown_seconds: float = 10.0
    keep_warm: bool = False


class AppConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = "VoxDesk"
    host: str = "127.0.0.1"
    port: int = 8765
    debug: bool = False

    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    voice_activation: VoiceActivationConfig = Field(default_factory=VoiceActivationConfig)
    hotkeys: HotkeyConfig = Field(default_factory=HotkeyConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    personality_name: str = "voxly"
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    model_loading: ModelLoadingConfig = Field(default_factory=ModelLoadingConfig)
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    vram: VRAMConfig = Field(default_factory=VRAMConfig)


def load_personality(name: str) -> PersonalityConfig:
    """Kişilik profilini YAML dosyasından yükle."""
    personality_file = PERSONALITIES_DIR / f"{name}.yaml"
    if not personality_file.exists():
        raise FileNotFoundError(f"Kişilik profili bulunamadı: {personality_file}")

    with open(personality_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return PersonalityConfig(**data)


def load_config() -> AppConfig:
    """Varsayılan config'i yükle ve kişilik profilini birleştir."""
    config_data = {}

    if DEFAULT_CONFIG.exists():
        with open(DEFAULT_CONFIG, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Flat YAML -> nested Pydantic mapping
        config_data = {
            "name": raw.get("app", {}).get("name", "VoxDesk"),
            "host": raw.get("app", {}).get("host", "127.0.0.1"),
            "port": raw.get("app", {}).get("port", 8765),
            "debug": raw.get("app", {}).get("debug", False),
            "capture": raw.get("capture", {}),
            "llm": raw.get("llm", {}),
            "tts": raw.get("tts", {}),
            "stt": raw.get("stt", {}),
            "voice_activation": raw.get("voice_activation", {}),
            "hotkeys": raw.get("hotkeys", {}),
            "history": raw.get("history", {}),
            "personality_name": raw.get("personality", "voxly"),
        }

    config = AppConfig(**config_data)

    # Kişilik profilini yükle
    try:
        config.personality = load_personality(config.personality_name)
        # Kişilik TTS voice ayarını override et
        if config.personality.voice:
            config.tts.voice = config.personality.voice
    except FileNotFoundError:
        pass  # Varsayılan kişilik kullanılır

    return config


# Singleton config instance
_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Tekil config instance döndür."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> AppConfig:
    """Config'i yeniden yükle."""
    global _config
    _config = load_config()
    return _config
