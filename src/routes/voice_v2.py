"""
VoxDesk — Binary Audio WebSocket Handler
/ws/voice/v2 — PCM binary transfer protocol.

Receive loop:
    1. Text frame → JSON dispatch (audio_config, audio_end, audio_cancel)
    2. Binary frame → PCM decode (only after handshake)

Voice mode — text-only:
    Sesli girdi sadece metin olarak LLM'e gönderilir.
    Ekran analizi sadece chat (text) pipeline'da kullanılır.

Güvenlik:
    - Binary before handshake → protocol_error
    - Oversized frame → protocol_error
    - Odd byte count → protocol_error
    - Invalid JSON → protocol_error
    - Disconnect → clean session close
    - Legacy base64 path korunur (/ws/voice → eski handler)
"""

from __future__ import annotations

import base64
import io
import json
import logging
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.audio_protocol import (
    AudioSession,
    AudioConfig,
    AudioMessageType,
    MAX_BASE64_BYTES,
    validate_config,
    validate_binary_frame,
    decode_pcm_s16le,
    build_config_ack,
    build_protocol_error,
)

logger = logging.getLogger("voxdesk.routes.voice_v2")

router = APIRouter(prefix="/api", tags=["voice_v2"])


@router.websocket("/ws/voice/v2")
async def ws_voice_v2(websocket: WebSocket):
    """
    Binary audio WebSocket — PCM S16LE transfer.

    Protocol:
        1. Client → audio_config (JSON text frame)
        2. Server → audio_config_ack (JSON text frame)
        3. Client → binary PCM frames
        4. Client → audio_end (JSON text frame)
        5. Server → STT → LLM → TTS pipeline
    """
    from src.main import get_app_state

    state = get_app_state()
    connected = await state.ws_manager.connect(websocket, "voice_v2")
    if not connected:
        return

    session = AudioSession()
    audio_buffer = bytearray()
    loop = asyncio.get_running_loop()

    try:
        while True:
            message = await websocket.receive()

            # ── Disconnect ───────────────────────────────────
            if message.get("type") == "websocket.disconnect":
                break

            # ── Text Frame ───────────────────────────────────
            if "text" in message:
                text_data = message["text"]
                if not text_data or not text_data.strip():
                    await websocket.send_json(
                        build_protocol_error("Boş text frame", "empty_frame")
                    )
                    continue

                try:
                    data = json.loads(text_data)
                except (json.JSONDecodeError, ValueError):
                    await websocket.send_json(
                        build_protocol_error("Geçersiz JSON", "invalid_json")
                    )
                    continue

                msg_type = data.get("type", "")

                # ── audio_config (handshake) ─────────────────
                if msg_type == AudioMessageType.AUDIO_CONFIG.value:
                    config, err = validate_config(data)
                    if err:
                        await websocket.send_json(
                            build_protocol_error(err, "invalid_config")
                        )
                        continue

                    session.accept_handshake(config)
                    await websocket.send_json(build_config_ack(config))
                    logger.debug(
                        f"Audio handshake OK — "
                        f"v{config.protocol_version}, "
                        f"{config.sample_rate}Hz"
                    )
                    continue

                # ── audio_end ────────────────────────────────
                if msg_type == AudioMessageType.AUDIO_END.value:
                    if not session.handshake_done:
                        await websocket.send_json(
                            build_protocol_error(
                                "audio_end — handshake yapılmamış",
                                "no_handshake"
                            )
                        )
                        continue

                    # Buffer'daki audio'yu işle
                    if audio_buffer:
                        await _process_audio_buffer(
                            websocket, state, loop,
                            bytes(audio_buffer), session
                        )
                        audio_buffer.clear()
                    else:
                        await websocket.send_json({"type": "stt_empty"})

                    session.reset()
                    continue

                # ── audio_cancel ─────────────────────────────
                if msg_type == AudioMessageType.AUDIO_CANCEL.value:
                    audio_buffer.clear()
                    session.reset()
                    logger.debug("Audio cancel — buffer temizlendi")
                    await websocket.send_json({"type": "audio_cancelled"})
                    continue

                # ── legacy base64 audio ──────────────────────
                if msg_type == "audio":
                    await _handle_legacy_audio(
                        websocket, state, loop, data
                    )
                    continue

                # ── Bilinmeyen type ──────────────────────────
                await websocket.send_json(
                    build_protocol_error(
                        f"Bilinmeyen message type: {msg_type}",
                        "unknown_type"
                    )
                )
                continue

            # ── Binary Frame ─────────────────────────────────
            if "bytes" in message:
                binary_data = message["bytes"]

                # Handshake kontrolü
                if not session.handshake_done:
                    await websocket.send_json(
                        build_protocol_error(
                            "Binary frame — önce audio_config gönder",
                            "binary_before_handshake"
                        )
                    )
                    continue

                # Frame validation
                valid, err = validate_binary_frame(binary_data)
                if not valid:
                    await websocket.send_json(
                        build_protocol_error(err, "invalid_frame")
                    )
                    continue

                # Buffer'a ekle + sequence güncelle
                audio_buffer.extend(binary_data)
                session.record_chunk(len(binary_data))
                continue

    except WebSocketDisconnect:
        logger.debug(f"Voice v2 disconnect — {session.total_chunks} chunks")
    except Exception as e:
        logger.error(f"WS voice v2 hatası: {e}")
        state.record_error(f"Voice WS: {e}")  # Sprint 3.5
    finally:
        state.ws_manager.disconnect(websocket, "voice_v2")


# ── Audio Processing Pipeline ────────────────────────────────

async def _process_audio_buffer(
    websocket: WebSocket,
    state,
    loop: asyncio.AbstractEventLoop,
    audio_bytes: bytes,
    session: AudioSession,
) -> None:
    """Buffered PCM audio → STT → LLM → TTS pipeline."""
    import numpy as np

    # PCM decode
    audio_array = decode_pcm_s16le(audio_bytes)

    if len(audio_array) < 4800:  # < 0.3s
        await websocket.send_json({"type": "stt_empty"})
        return

    # STT (blocking → executor)
    import time as _time
    _stt_t0 = _time.perf_counter()
    try:
        result = await loop.run_in_executor(
            None, state.stt.transcribe_audio, audio_array
        )
    except Exception as stt_err:
        logger.error(f"STT error: {stt_err}")
        state.metrics.increment("stt_errors_total")
        state.record_error(f"STT: {stt_err}")  # Sprint 3.5
        await websocket.send_json({
            "type": "voice_error",
            "code": "STT_FAILED",
            "message": "Failed to transcribe speech.",
            "recoverable": True,
        })
        return
    _stt_ms = (_time.perf_counter() - _stt_t0) * 1000
    state.metrics.record_latency("stt_decode_ms", _stt_ms)

    text = result.get("text", "")
    lang = result.get("language", "unknown")

    if not text.strip():
        await websocket.send_json({"type": "stt_empty"})
        return

    await websocket.send_json({
        "type": "stt_result",
        "text": text,
        "language": lang,
    })

    # Voice mode: LLM algılar dili, çeviri yapılmaz.
    llm_input = text

    # LLM — async, non-blocking
    # Voice mode = text-only (ekran analizi sadece chat pipeline'da)
    try:
        if state.llm is None:
            raise RuntimeError("LLM unavailable — local model file missing")
        llm_response = await state.llm.chat(llm_input, image_bytes=None, response_mode="voice")
    except Exception as llm_err:
        logger.error(f"Voice LLM error: {llm_err}")
        state.metrics.increment("llm_errors_total")
        state.record_error(f"Voice LLM: {llm_err}")  # Sprint 3.5
        await websocket.send_json({
            "type": "voice_error",
            "code": "LLM_FAILED",
            "message": "Failed to generate voice response.",
            "recoverable": True,
        })
        return

    await websocket.send_json({
        "type": "llm_response",
        "text": llm_response,
    })

    # TTS — streaming, executor'da çalışır
    if state.tts and state.tts.enabled:
        import soundfile as sf

        try:
            _tts_t0 = _time.perf_counter()

            def _produce_tts_chunks():
                chunks = []
                for chunk in state.tts.synthesize_stream(llm_response):
                    buf = io.BytesIO()
                    sf.write(buf, chunk, state.tts.sample_rate, format="WAV")
                    chunks.append(base64.b64encode(buf.getvalue()).decode())
                return chunks

            tts_chunks = await loop.run_in_executor(None, _produce_tts_chunks)
            _tts_ms = (_time.perf_counter() - _tts_t0) * 1000
            state.metrics.record_latency("tts_synthesis_ms", _tts_ms)

            for chunk_b64 in tts_chunks:
                await websocket.send_json({
                    "type": "tts_audio",
                    "audio": chunk_b64,
                })
        except Exception as tts_err:
            logger.error(f"Voice TTS error: {tts_err}")
            state.metrics.increment("tts_errors_total")
            await websocket.send_json({
                "type": "voice_error",
                "code": "TTS_FAILED",
                "message": "Failed to synthesize speech.",
                "recoverable": True,
            })


# ── Legacy Base64 Handler ────────────────────────────────────

async def _handle_legacy_audio(
    websocket: WebSocket,
    state,
    loop: asyncio.AbstractEventLoop,
    data: dict,
) -> None:
    """
    Legacy base64 audio path — geriye dönük uyumluluk.
    enable_binary_audio=false iken bu path kullanılır.
    """
    audio_b64 = data.get("audio", "")
    audio_format = data.get("format", "webm")

    # Base64 size limit
    if len(audio_b64) > MAX_BASE64_BYTES:
        await websocket.send_json(
            build_protocol_error(
                f"Base64 audio çok büyük: {len(audio_b64)} bytes",
                "oversized_base64"
            )
        )
        return

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception:
        await websocket.send_json(
            build_protocol_error("Base64 decode hatası", "invalid_base64")
        )
        return

    # Sprint 3: audio_utils'ten import — chat.py cross-import kaldırıldı
    from src.audio_utils import decode_audio_webm, decode_audio_raw_pcm

    if audio_format == "pcm":
        audio_array = decode_audio_raw_pcm(audio_bytes)
    else:
        audio_array = await loop.run_in_executor(
            None, decode_audio_webm, audio_bytes
        )

    if audio_array is None or len(audio_array) < 4800:
        await websocket.send_json({"type": "stt_empty"})
        return

    # Delegate to shared pipeline
    # Sprint 3: __import__ anti-pattern kaldırıldı — AudioConfig zaten import edildi
    temp_session = AudioSession()
    temp_session.accept_handshake(AudioConfig())

    result = await loop.run_in_executor(
        None, state.stt.transcribe_audio, audio_array
    )
    text = result.get("text", "")
    lang = result.get("language", "unknown")

    if not text.strip():
        await websocket.send_json({"type": "stt_empty"})
        return

    await websocket.send_json({
        "type": "stt_result",
        "text": text,
        "language": lang,
    })

    # Voice mode: çeviri yok, LLM orijinal dilde cevaplar
    llm_input = text

    # LLM — voice mode = text-only (no screen capture)
    try:
        if state.llm is None:
            raise RuntimeError("LLM unavailable — local model file missing")
        llm_response = await state.llm.chat(llm_input, image_bytes=None, response_mode="voice")
    except Exception as llm_err:
        logger.error(f"Voice legacy LLM error: {llm_err}")
        state.record_error(f"Voice legacy LLM: {llm_err}")
        await websocket.send_json({
            "type": "voice_error",
            "code": "LLM_FAILED",
            "message": "Failed to generate voice response.",
            "recoverable": True,
        })
        return

    await websocket.send_json({
        "type": "llm_response",
        "text": llm_response,
    })

    # TTS — streaming, executor'da çalışır
    if state.tts and state.tts.enabled:
        import soundfile as sf

        try:
            def _produce_tts_chunks():
                chunks = []
                for chunk in state.tts.synthesize_stream(llm_response):
                    buf = io.BytesIO()
                    sf.write(buf, chunk, state.tts.sample_rate, format="WAV")
                    chunks.append(base64.b64encode(buf.getvalue()).decode())
                return chunks

            tts_chunks = await loop.run_in_executor(None, _produce_tts_chunks)
            for chunk_b64 in tts_chunks:
                await websocket.send_json({
                    "type": "tts_audio",
                    "audio": chunk_b64,
                })
        except Exception as tts_err:
            logger.error(f"Voice legacy TTS error: {tts_err}")
            await websocket.send_json({
                "type": "voice_error",
                "code": "TTS_FAILED",
                "message": "Failed to synthesize speech.",
                "recoverable": True,
            })
