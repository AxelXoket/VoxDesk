"""
VoxDesk — Main FastAPI Application
Entry point that wires all components together.
Binds to 127.0.0.1 only — no external network access.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import get_config, AppConfig
from src.metrics import MetricsCollector
from src.registry import ModuleRegistry
from src.vram_manager import VRAMManager
from src.isolation import verify_isolation
from src.capture import ScreenCapture
from src.llm_client import VisionLLM
from src.stt import SpeechRecognizer
from src.tts import VoiceSynth
from src.websocket_manager import ConnectionManager
from src.hotkey import HotkeyManager
from src.tray import TrayIcon

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("voxdesk")


@dataclass
class AppState:
    """Uygulama genelinde paylaşılan state."""
    config: AppConfig = field(default_factory=get_config)
    metrics: MetricsCollector = field(default_factory=MetricsCollector)
    registry: ModuleRegistry = field(default_factory=ModuleRegistry)
    vram_manager: VRAMManager | None = None
    capture: ScreenCapture | None = None
    llm: VisionLLM | None = None
    stt: SpeechRecognizer | None = None
    tts: VoiceSynth | None = None
    ws_manager: ConnectionManager = field(default_factory=ConnectionManager)
    hotkey_manager: HotkeyManager | None = None
    tray: TrayIcon | None = None


# Global state
_state: AppState | None = None


def get_app_state() -> AppState:
    """Global app state'e erişim."""
    global _state
    if _state is None:
        _state = AppState()
    return _state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlatma ve kapatma lifecycle."""
    global _state
    config = get_config()

    logger.info("=" * 60)
    logger.info(f"  🌐 VoxDesk — Local AI Desktop Assistant v0.1.0")
    logger.info(f"  📍 http://{config.host}:{config.port}")
    logger.info("=" * 60)

    # 1. İzolasyon doğrulaması
    isolation_report = verify_isolation()
    logger.info(f"  🔒 İzolasyon: {isolation_report['status']}")

    # 2. State oluştur
    _state = AppState(config=config)

    # 3. Registry — factory catalog'u oluştur
    _register_default_factories(_state.registry)
    logger.info(f"  📦 Registry: {len(_state.registry.list_modules())} kind kaydedildi")

    # 4. Bileşenleri oluştur (registry.create — startup'ta BİR KEZ)
    try:
        # Capture — registry üzerinden
        _state.capture = _state.registry.create(
            "capture", config.capture.backend, config.capture
        )
        _state.capture.start()

        # LLM — registry üzerinden
        _state.llm = _state.registry.create(
            "llm", config.llm.provider, config.llm
        )
        logger.info(f"  🤖 Model: {config.llm.model}")

        # STT — registry üzerinden
        _state.stt = _state.registry.create(
            "stt", config.stt.engine, config.stt
        )
        logger.info(f"  🎤 STT: {config.stt.model}")

        # TTS — registry üzerinden
        _state.tts = _state.registry.create(
            "tts", config.tts.engine, config.tts
        )
        logger.info(f"  🔊 TTS: {config.tts.voice}")

        # 5. VRAM Manager — model lifecycle koordinasyonu
        _state.vram_manager = VRAMManager(
            metrics=_state.metrics,
            idle_timeout_seconds=config.vram.stt_idle_unload_seconds,
            poll_interval_seconds=config.vram.monitor_interval_seconds,
        )
        if _state.stt:
            _state.vram_manager.register_model("stt", _state.stt._lifecycle)
        if _state.tts:
            _state.vram_manager.register_model("tts", _state.tts._lifecycle)
        await _state.vram_manager.start_monitor()
        logger.info(f"  📊 VRAM monitor başlatıldı")

        # Hotkeys — doğrudan (registry dışı, UI component)
        _state.hotkey_manager = HotkeyManager(
            activate_key=config.hotkeys.activate,
            toggle_listen_key=config.hotkeys.toggle_listen,
            push_to_talk_key=config.hotkeys.push_to_talk,
        )
        _state.hotkey_manager.start()

        # System Tray — doğrudan (registry dışı, UI component)
        _state.tray = TrayIcon()
        _state.tray.start()

        # Kişilik selamlaması
        logger.info(f"  💬 {config.personality.greeting}")

    except Exception as e:
        logger.error(f"  ❌ Başlatma hatası: {e}")
        raise  # Yarı başlatılmış state ile devam etme

    logger.info("=" * 60)
    logger.info("  ✅ VoxDesk ready! Open your browser and start chatting.")
    logger.info("=" * 60)

    yield  # Uygulama çalışıyor

    # Shutdown — her bileşen izole try/except ile
    logger.info("🛑 VoxDesk shutting down...")
    await _safe_shutdown()
    logger.info("👋 Goodbye!")


# ── Factory Registration ─────────────────────────────────────

def _register_default_factories(registry: ModuleRegistry) -> None:
    """
    Default engine factory'lerini registry'ye kaydet.
    Her factory config alır, engine instance döndürür.
    Startup sırasında bir kez çağrılır.
    """
    # Capture
    registry.register(
        "capture", "dxcam",
        lambda cfg: ScreenCapture(
            interval=cfg.interval_seconds,
            buffer_size=cfg.buffer_size,
            jpeg_quality=cfg.jpeg_quality,
            resize_width=cfg.resize_width,
        ),
        requires_gpu=False,
        description="dxcam screen capture",
    )

    # LLM
    registry.register(
        "llm", "ollama",
        lambda cfg: VisionLLM(),
        requires_gpu=False,
        description="Ollama local LLM",
    )

    # STT
    registry.register(
        "stt", "faster-whisper",
        lambda cfg: SpeechRecognizer(
            model_name=cfg.model,
            device=cfg.device,
            compute_type=cfg.compute_type,
            language=cfg.language,
            vad_enabled=cfg.vad_enabled,
        ),
        requires_gpu=True,
        description="faster-whisper STT",
    )

    # TTS
    registry.register(
        "tts", "kokoro",
        lambda cfg: VoiceSynth(
            voice=cfg.voice,
            speed=cfg.speed,
            lang_code=cfg.lang_code,
            enabled=cfg.enabled,
        ),
        requires_gpu=True,
        description="Kokoro TTS",
    )


# ── Shutdown Cleanup ─────────────────────────────────────────

async def _safe_shutdown() -> None:
    """
    Tüm bileşenleri güvenli şekilde kapat.
    Her bileşen izole try/except ile — bir hata diğerlerini engellemez.
    """
    if _state is None:
        return

    # VRAM Monitor
    try:
        if _state.vram_manager:
            await _state.vram_manager.stop_monitor()
            _state.vram_manager.close()
    except Exception as e:
        logger.error(f"VRAM manager shutdown hatası: {e}")

    # Capture
    try:
        if _state.capture:
            _state.capture.stop()
            if hasattr(_state.capture, 'close'):
                _state.capture.close()
    except Exception as e:
        logger.error(f"Capture shutdown hatası: {e}")

    # STT
    try:
        if _state.stt:
            _state.stt.close()
    except Exception as e:
        logger.error(f"STT shutdown hatası: {e}")

    # TTS
    try:
        if _state.tts:
            _state.tts.close()
    except Exception as e:
        logger.error(f"TTS shutdown hatası: {e}")

    # LLM
    try:
        if _state.llm and hasattr(_state.llm, 'aclose'):
            await _state.llm.aclose()
        elif _state.llm and hasattr(_state.llm, 'close'):
            _state.llm.close()
    except Exception as e:
        logger.error(f"LLM shutdown hatası: {e}")

    # Hotkeys
    try:
        if _state.hotkey_manager:
            _state.hotkey_manager.stop()
    except Exception as e:
        logger.error(f"Hotkey shutdown hatası: {e}")

    # System Tray
    try:
        if _state.tray:
            _state.tray.stop()
    except Exception as e:
        logger.error(f"Tray shutdown hatası: {e}")


# FastAPI App
app = FastAPI(
    title="VoxDesk",
    description="Local AI Desktop Assistant — Screen Analysis + Voice Chat",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — sadece localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (frontend)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")

# Routes
from src.routes.chat import router as chat_router
from src.routes.settings import router as settings_router
from src.routes.history import router as history_router
from src.routes.voice_v2 import router as voice_v2_router

app.include_router(chat_router)
app.include_router(settings_router)
app.include_router(history_router)
app.include_router(voice_v2_router)


@app.get("/")
async def root():
    """Ana sayfa — frontend'e yönlendir."""
    from fastapi.responses import FileResponse
    index = frontend_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "VoxDesk API active", "docs": "/docs"}


@app.get("/api/health")
async def health():
    """Public health — minimal, safe to expose."""
    state = get_app_state()
    degraded = False
    status = "ok"

    # Check core components
    if state.capture and not state.capture.is_running:
        degraded = True
        status = "degraded"

    return {
        "status": status,
        "version": app.version,
        "uptime_seconds": state.metrics.get_uptime_seconds(),
        "degraded": degraded,
    }


@app.get("/api/debug/metrics")
async def debug_metrics():
    """
    Detailed debug metrics — localhost-only in dev.
    Controlled by features.enable_debug_metrics in prod.
    Contains process-local metrics, NOT nvidia-smi.
    """
    state = get_app_state()
    report = state.metrics.get_full_report()

    # Registry module listing (factory catalog info)
    report["registry"] = state.registry.list_modules()
    report["engines"] = {
        "capture": {
            "backend": state.config.capture.backend,
            "running": state.capture.is_running if state.capture else False,
        },
        "stt": {
            "engine": state.config.stt.engine,
            "model": state.config.stt.model,
        },
        "tts": {
            "engine": state.config.tts.engine,
            "voice": state.config.tts.voice,
        },
        "llm": {
            "provider": state.config.llm.provider,
            "model": state.config.llm.model,
        },
    }

    # VRAM model lifecycle report
    if state.vram_manager:
        report["vram"] = state.vram_manager.get_report()

    report["_scope"] = "process-local"

    return report


def main():
    """Uygulamayı başlat."""
    import uvicorn
    config = get_config()

    uvicorn.run(
        "src.main:app",
        host=config.host,  # 127.0.0.1 — sadece lokal
        port=config.port,
        reload=config.debug,
        log_level="info",
    )


if __name__ == "__main__":
    main()
