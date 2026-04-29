"""
VoxDesk — Chat + Voice API Routes
Metin chat, ekran analizi, sesli sohbet.
Tüm pipeline non-blocking — event loop'u dondurmaz.
"""

from __future__ import annotations

import io
import base64
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger("voxdesk.routes.chat")

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    include_screen: bool = True


class ChatResponse(BaseModel):
    response: str
    model: str | None = None
    has_image: bool = False


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Metin tabanlı chat — async, non-blocking."""
    from src.main import get_app_state

    state = get_app_state()

    if state.llm is None:
        return ChatResponse(
            response="LLM unavailable — local model file missing. Please place GGUF files under models/.",
            model=None,
            has_image=False,
        )

    image_artifact = None

    if request.include_screen and state.capture:
        frame = state.capture.get_latest_frame()
        if frame:
            from src.image_artifact import build_artifact_from_frame
            image_artifact = build_artifact_from_frame(frame)

    # Async chat — event loop'u bloke etmez
    response_text = await state.llm.chat(request.message, image_artifact=image_artifact)

    return ChatResponse(
        response=response_text,
        model=state.llm.model_name,
        has_image=image_artifact is not None,
    )


@router.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """Real-time async streaming chat via WebSocket."""
    from src.main import get_app_state

    state = get_app_state()
    connected = await state.ws_manager.connect(websocket, "chat")
    if not connected:
        return

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            include_screen = data.get("include_screen", True)
            attachments = data.get("attachments", [])

            # ── Image priority: attachment > pinned frame > always-on screen ──
            image_artifact = None

            # 1. User attachment (file upload, drag & drop, paste)
            if attachments:
                try:
                    first_attachment = attachments[0]
                    att_data = first_attachment.get("data", "")
                    # Strip data URI prefix if present (e.g., "data:image/jpeg;base64,...")
                    if "," in att_data:
                        att_data = att_data.split(",", 1)[1]
                    raw_bytes = base64.b64decode(att_data)
                    from src.image_artifact import build_artifact_from_upload, ImageValidationError
                    image_artifact = build_artifact_from_upload(raw_bytes, jpeg_quality=92)
                    logger.info(f"📎 Upload artifact created ({image_artifact.metadata.byte_size} bytes)")
                except ImageValidationError as val_err:
                    logger.warning(f"Upload validation failed: {val_err}")
                    await state.ws_manager.send_json(websocket, {
                        "type": "error",
                        "code": val_err.code,
                        "message": f"Image validation failed: {val_err}",
                        "recoverable": True,
                    })
                    continue
                except Exception as att_err:
                    logger.error(f"Attachment decode error: {att_err}")

            # 2. Pinned frame (hotkey capture — sekme değişmeden önce alınmış)
            if image_artifact is None and state.capture and state.capture.has_pin:
                frame = state.capture.get_pinned_frame()
                if frame:
                    from src.image_artifact import build_artifact_from_frame
                    image_artifact = build_artifact_from_frame(frame, source_override="pinned_frame")
                    state.capture.clear_pin()
                    logger.info("📌 Pinned frame artifact created")

            # 3. Always-on screen capture — anlık canlı frame (stale buffer değil)
            if image_artifact is None and include_screen and state.capture:
                frame = state.capture.grab_now()
                if frame:
                    from src.image_artifact import build_artifact_from_frame
                    image_artifact = build_artifact_from_frame(frame)
                    logger.info(f"📸 Live frame artifact ({frame.width}x{frame.height})")

            if state.llm is None:
                await state.ws_manager.send_json(websocket, {
                    "type": "error",
                    "code": "LLM_UNAVAILABLE",
                    "message": "LLM unavailable — local model file missing.",
                    "recoverable": True,
                })
                continue

            await state.ws_manager.send_json(websocket, {
                "type": "start",
                "model": state.llm.model_name,
            })

            full_response = []
            try:
                async for token in state.llm.chat_stream(message, image_artifact=image_artifact):
                    full_response.append(token)
                    await state.ws_manager.send_json(websocket, {
                        "type": "token",
                        "content": token,
                    })

                await state.ws_manager.send_json(websocket, {
                    "type": "end",
                    "full_response": "".join(full_response),
                })
            except Exception as llm_err:
                logger.error(f"LLM stream error in chat: {llm_err}")
                state.record_error(f"Chat LLM: {llm_err}")  # Sprint 3.5
                await state.ws_manager.send_json(websocket, {
                    "type": "error",
                    "code": "LLM_STREAM_FAILED",
                    "message": "Failed to stream assistant response.",
                    "recoverable": True,
                })

    except WebSocketDisconnect:
        state.ws_manager.disconnect(websocket, "chat")
    except Exception as e:
        logger.error(f"WS chat hatası: {e}")
        state.record_error(f"Chat WS: {e}")  # Sprint 3.5
        state.ws_manager.disconnect(websocket, "chat")


@router.websocket("/ws/screen")
async def ws_screen(websocket: WebSocket):
    """Live screen preview — binary frame gönderimi (CPU tasarrufu)."""
    from src.main import get_app_state

    state = get_app_state()
    connected = await state.ws_manager.connect(websocket, "screen")
    if not connected:
        return

    _last_frame_ts = 0.0

    try:
        while True:
            if state.capture:
                frame = state.capture.get_latest_frame()
                # Sadece yeni frame varsa gönder (duplicate skip)
                if frame and frame.timestamp > _last_frame_ts:
                    _last_frame_ts = frame.timestamp
                    # Metadata + base64 image
                    try:
                        await websocket.send_json({
                            "type": "frame",
                            "image": base64.b64encode(frame.image_bytes).decode(),
                            "timestamp": frame.timestamp,
                            "width": frame.width,
                            "height": frame.height,
                        })
                    except Exception:
                        # Sprint 3.6: Socket kapanmış — cleanup and break
                        break
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        pass
    finally:
        state.ws_manager.disconnect(websocket, "screen")


# Sprint 3: audio decode fonksiyonları audio_utils'e extract edildi
from src.audio_utils import decode_audio_webm, decode_audio_raw_pcm


@router.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket):
    """
    Sesli chat — full async pipeline:
    Client audio → decode → STT → LLM (async) → TTS (streaming) → Client
    """
    from src.main import get_app_state

    state = get_app_state()
    connected = await state.ws_manager.connect(websocket, "voice")
    if not connected:
        return

    loop = asyncio.get_running_loop()

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "audio":
                audio_b64 = data.get("audio", "")
                audio_format = data.get("format", "webm")  # "webm" veya "pcm"
                try:
                    audio_bytes = base64.b64decode(audio_b64)
                except Exception:
                    await state.ws_manager.send_json(websocket, {
                        "type": "voice_error",
                        "code": "INVALID_AUDIO",
                        "message": "Base64 audio decode failed.",
                        "recoverable": True,
                    })
                    continue

                # 1. Audio decode (blocking → executor)
                if audio_format == "pcm":
                    audio_array = decode_audio_raw_pcm(audio_bytes)
                else:
                    audio_array = await loop.run_in_executor(
                        None, decode_audio_webm, audio_bytes
                    )

                if audio_array is None or len(audio_array) < 4800:  # <0.3s
                    await state.ws_manager.send_json(websocket, {
                        "type": "stt_empty",
                    })
                    continue

                # 2. STT (blocking → executor)
                result = await loop.run_in_executor(
                    None, state.stt.transcribe_audio, audio_array
                )
                text = result.get("text", "")
                lang = result.get("language", "unknown")

                if not text.strip():
                    await state.ws_manager.send_json(websocket, {
                        "type": "stt_empty",
                    })
                    continue

                await state.ws_manager.send_json(websocket, {
                    "type": "stt_result",
                    "text": text,
                    "language": lang,
                })

                # Voice mode: LLM handles multilingual natively, no translator needed
                llm_input = text

                # 3. Screen capture — voice mode'da da ekranı gör
                voice_artifact = None
                if state.capture:
                    frame = state.capture.grab_now()
                    if frame:
                        from src.image_artifact import build_artifact_from_frame
                        voice_artifact = build_artifact_from_frame(frame, source_override="voice_screen")
                        logger.info(f"🎤📸 Voice: frame artifact ({frame.width}x{frame.height})")

                if state.llm is None:
                    await state.ws_manager.send_json(websocket, {
                        "type": "error",
                        "code": "LLM_UNAVAILABLE",
                        "message": "LLM unavailable — local model file missing.",
                        "recoverable": True,
                    })
                    continue

                llm_response = await state.llm.chat(llm_input, response_mode="voice", image_artifact=voice_artifact)

                await state.ws_manager.send_json(websocket, {
                    "type": "llm_response",
                    "text": llm_response,
                })

                # 4. TTS — streaming, executor'da çalışır (blocking)
                if state.tts and state.tts.enabled:
                    try:
                        import soundfile as sf

                        def _produce_tts_chunks():
                            """TTS chunk'ları üret (senkron, executor'da çalışır)."""
                            chunks = []
                            for chunk in state.tts.synthesize_stream(llm_response):
                                buf = io.BytesIO()
                                sf.write(buf, chunk, state.tts.sample_rate, format="WAV")
                                chunks.append(base64.b64encode(buf.getvalue()).decode())
                            return chunks

                        tts_chunks = await loop.run_in_executor(None, _produce_tts_chunks)
                        for chunk_b64 in tts_chunks:
                            await state.ws_manager.send_json(websocket, {
                                "type": "tts_audio",
                                "audio": chunk_b64,
                            })
                    except Exception as tts_err:
                        logger.error(f"Voice TTS hatası: {tts_err}")
                        state.record_error(f"Voice TTS: {tts_err}")
                        if state.metrics:
                            state.metrics.increment("tts_errors_total")
                        await state.ws_manager.send_json(websocket, {
                            "type": "voice_error",
                            "code": "TTS_FAILED",
                            "message": f"TTS synthesis failed: {tts_err}",
                            "recoverable": True,
                        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WS voice hatası: {e}")
        state.record_error(f"Voice WS: {e}")
    finally:
        state.ws_manager.disconnect(websocket, "voice")
