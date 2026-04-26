"""
VoxDesk — History API Routes
Konuşma geçmişi yönetimi, export desteği.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("voxdesk.routes.history")

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
async def get_history():
    """Konuşma geçmişini döndür."""
    from src.main import get_app_state
    state = get_app_state()
    return state.llm.export_history()


@router.delete("/history")
async def clear_history():
    """Konuşma geçmişini temizle."""
    from src.main import get_app_state
    state = get_app_state()
    state.llm.clear_history()
    return {"status": "ok", "message": "Geçmiş temizlendi"}


@router.post("/history/export")
async def export_history():
    """Konuşma geçmişini dosyaya kaydet."""
    from src.main import get_app_state
    from src.config import get_config

    state = get_app_state()
    config = get_config()

    history = state.llm.export_history()
    if not history:
        return {"status": "empty", "message": "Kaydedilecek geçmiş yok"}

    save_dir = Path(config.history.save_path)
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = save_dir / f"voxdesk_history_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 Geçmiş kaydedildi: {filename}")
    return {"status": "ok", "file": str(filename), "messages": len(history)}
