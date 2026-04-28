"""
VoxDesk — Settings API Routes
Yapılandırma, model, kişilik, ses profili yönetimi.
"""

from __future__ import annotations

import logging
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import get_config, reload_config, load_personality, PERSONALITIES_DIR
from src.tts import VoiceSynth

logger = logging.getLogger("voxdesk.routes.settings")

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsResponse(BaseModel):
    model: str | None
    voice: str
    tts_speed: float
    tts_enabled: bool
    capture_interval: float
    personality: str
    stt_language: str | None
    voice_activation_enabled: bool
    voice_activation_threshold: float
    hotkeys: dict


class VoiceUpdateRequest(BaseModel):
    voice: str
    speed: float | None = None


class ModelUpdateRequest(BaseModel):
    model: str


@router.get("/settings", response_model=SettingsResponse)
async def get_settings():
    """Mevcut ayarları döndür."""
    config = get_config()
    return SettingsResponse(
        model=Path(config.llm.model_path).name if config.llm.model_path else None,
        voice=config.tts.voice,
        tts_speed=config.tts.speed,
        tts_enabled=config.tts.enabled,
        capture_interval=config.capture.interval_seconds,
        personality=config.personality.name,
        stt_language=config.stt.language,
        voice_activation_enabled=config.voice_activation.enabled,
        voice_activation_threshold=config.voice_activation.threshold_db,
        hotkeys={
            "activate": config.hotkeys.activate,
            "toggle_listen": config.hotkeys.toggle_listen,
            "push_to_talk": config.hotkeys.push_to_talk,
            "pin_screen": config.hotkeys.pin_screen,
        },
    )


@router.get("/voices")
async def get_voices():
    """Mevcut ses profillerini döndür."""
    return VoiceSynth.get_available_voices()


@router.put("/voice")
async def update_voice(request: VoiceUpdateRequest):
    """Ses profilini değiştir."""
    from src.main import get_app_state
    state = get_app_state()

    if state.tts:
        state.tts.set_voice(request.voice)
        if request.speed is not None:
            state.tts.set_speed(request.speed)

    return {"status": "ok", "voice": request.voice}


@router.get("/models")
async def list_models():
    """Yüklü modelleri listele (lokal dosya)."""
    from src.main import get_app_state
    state = get_app_state()
    config = get_config()
    models = []
    if config.llm.model_path:
        models.append({"name": Path(config.llm.model_path).name, "role": "primary"})
    if config.llm.fallback_model_path:
        models.append({"name": Path(config.llm.fallback_model_path).name, "role": "fallback"})
    return {"models": models, "llm_available": state.llm is not None}


@router.put("/model")
async def update_model(request: ModelUpdateRequest):
    """Aktif modeli değiştir. (NOT: hot-swap henüz implement değil — stub)."""
    from src.main import get_app_state
    state = get_app_state()
    if state.llm is None:
        return {"status": "error", "message": "LLM unavailable — model file missing"}
    state.llm.set_model(request.model)
    return {"status": "ok", "model": request.model}


@router.put("/tts/toggle")
async def toggle_tts():
    """TTS'i aç/kapat (runtime toggle)."""
    from src.main import get_app_state
    state = get_app_state()
    if state.tts is None:
        return {"status": "error", "message": "TTS component unavailable"}
    state.tts.enabled = not state.tts.enabled
    logger.info(f"TTS toggled: {state.tts.enabled}")
    return {"status": "ok", "tts_enabled": state.tts.enabled}


@router.put("/voice-activation/toggle")
async def toggle_voice_activation():
    """Voice activation'ı aç/kapat (runtime toggle)."""
    config = get_config()
    current = config.voice_activation.enabled
    object.__setattr__(config.voice_activation, "enabled", not current)
    new_state = config.voice_activation.enabled
    logger.info(f"Voice activation toggled: {new_state}")
    return {"status": "ok", "voice_activation_enabled": new_state}


@router.get("/personalities")
async def list_personalities():
    """Mevcut kişilik profillerini listele."""
    profiles = []
    if PERSONALITIES_DIR.exists():
        for f in PERSONALITIES_DIR.glob("*.yaml"):
            try:
                p = load_personality(f.stem)
                profiles.append({
                    "id": f.stem,
                    "name": p.name,
                    "tone": p.tone,
                    "greeting": p.greeting,
                })
            except Exception:
                continue
    return profiles


@router.put("/personality/{name}")
async def set_personality(name: str):
    """Kişilik profilini değiştir."""
    from src.main import get_app_state
    state = get_app_state()

    try:
        personality = load_personality(name)
        if state.llm is not None:
            state.llm.set_personality(personality)
        if state.tts and personality.voice:
            state.tts.set_voice(personality.voice)
        # Sprint 5.1: STT domain vocabulary — personality'ye bağlı
        if state.stt and hasattr(state.stt, 'set_initial_prompt'):
            state.stt.set_initial_prompt(personality.stt_context)
        return {"status": "ok", "personality": personality.name}
    except FileNotFoundError:
        return {"status": "error", "message": f"Kişilik bulunamadı: {name}"}


@router.get("/isolation")
async def get_isolation_status():
    """İzolasyon durumunu döndür."""
    from src.isolation import verify_isolation
    return verify_isolation()
