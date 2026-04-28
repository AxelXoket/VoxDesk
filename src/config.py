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
    provider: str = "llama-cpp"

    # Local model paths — explicit, no auto-discovery, no runtime download
    model_path: str | None = None
    mmproj_path: str | None = None

    # Local fallback model paths (Sprint 4 PoC: null, ileride lower quant)
    fallback_model_path: str | None = None
    fallback_mmproj_path: str | None = None

    # llama-cpp-python specific
    n_gpu_layers: int = -1        # -1 = full GPU offload
    n_ctx: int = 8192             # context window
    chat_format: str | None = None  # None = auto-detect from model

    # Shared inference params
    temperature: float = 0.7
    max_tokens: int = 2048
    repeat_penalty: float = 1.1     # Prevent repetition loops
    context_messages: int = 10
    # Sprint 3: multi-frame vision — 3D-Resampler doğrulandıktan sonra artır
    llm_frame_count: int = 1


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
    model_path: str | None = None  # Local CT2 path (overrides hub model name)
    device: str = "cuda"
    compute_type: str = "float16"
    language: str | None = None  # None = auto-detect
    vad_enabled: bool = True


class TranslatorConfig(BaseModel):
    """MarianMT (opus-mt-tr-en) translator configuration."""
    model_config = ConfigDict(extra='forbid')
    engine: str = "marian"
    model_path: str = "models/opus-mt-tr-en"
    device: str = "cuda"
    enabled: bool = True


class VoiceActivationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    threshold_db: float = -30.0


class HotkeyConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    activate: str = "ctrl+shift+space"
    toggle_listen: str = "ctrl+shift+v"
    push_to_talk: str = "ctrl+shift+b"
    pin_screen: str = "ctrl+shift+s"


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

    # ── Modüler Prompt Bölümleri ─────────────────────────────
    system_prompt: str = ""           # Ana davranış kuralları ve kişilik tanımı
    stt_context: str = ""             # Whisper initial_prompt — domain vocabulary
    screen_analysis_prompt: str = ""  # Ekran yorumlama talimatları
    emotion_rules: str = ""           # Duygu algılama/yansıtma filtresi
    response_format: str = ""         # Çıktı biçim kuralları (voice vs text)


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
    enable_vram_unload: bool = True
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
    stt_idle_unload_seconds: float = 180.0         # 3 dk idle → offload
    tts_idle_unload_seconds: float = 180.0         # 3 dk idle → offload
    translator_idle_unload_seconds: float = 180.0  # 3 dk idle → offload
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
    translator: TranslatorConfig = Field(default_factory=TranslatorConfig)


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
            # Sprint 1 — Gap 5: map missing nested config sections
            "privacy": raw.get("privacy", {}),
            "network": raw.get("network", {}),
            "model_loading": raw.get("model_loading", {}),
            "features": raw.get("features", {}),
            "security": raw.get("security", {}),
            "vram": raw.get("vram", {}),
            "translator": raw.get("translator", {}),
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
