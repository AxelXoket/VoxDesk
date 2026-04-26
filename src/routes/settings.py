"""
VoxDesk — Settings API Routes
Yapılandırma, model, kişilik, ses profili yönetimi.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter
from pydantic import BaseModel

from src.config import get_config, reload_config, load_personality, PERSONALITIES_DIR
from src.tts import VoiceSynth

logger = logging.getLogger("voxdesk.routes.settings")

router = APIRouter(prefix="/api", tags=["settings"])


class SettingsResponse(BaseModel):
    model: str
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
        model=config.llm.model,
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
    """Ollama'da yüklü modelleri listele (lokal)."""
    from src.main import get_app_state
    state = get_app_state()
    return await state.llm.list_models()


@router.put("/model")
async def update_model(request: ModelUpdateRequest):
    """Aktif modeli değiştir."""
    from src.main import get_app_state
    state = get_app_state()
    state.llm.set_model(request.model)
    return {"status": "ok", "model": request.model}


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
        state.llm.set_personality(personality)
        if state.tts and personality.voice:
            state.tts.set_voice(personality.voice)
        return {"status": "ok", "personality": personality.name}
    except FileNotFoundError:
        return {"status": "error", "message": f"Kişilik bulunamadı: {name}"}


@router.get("/isolation")
async def get_isolation_status():
    """İzolasyon durumunu döndür."""
    from src.isolation import verify_isolation
    return verify_isolation()
