# VoxDesk Architecture — Production Reference

> **Version** : v0.7.2 — Sprint 7.2 : Stabilization — FVM stuck fix, UI calm, screen prompt policy, Gemma4 default  
> **Runtime** : Python 3.12 + FastAPI + Uvicorn  
> **Inference** : Local-only (Whisper STT, Kokoro TTS, Gemma4 via llama-server sidecar, llama-cpp-python fallback)  
> **GPU** : RTX 5080 (Blackwell, SM 12.0) — CUDA 12.8  
> **Audio** : PCM binary WebSocket (v1) + legacy base64 fallback  
> **Voice Pipeline** : Mic → STT (auto-detect TR/EN) → LLM (multilingual, screen context optional) → TTS → Speaker  
> **Note** : Translator (MarianMT TR→EN) is available but disabled by default — LLM handles multilingual natively.

---

## Voice Modes (Sprint 7)

> [!IMPORTANT]
> Full Voice Mode and normal dictation are **separate, independent modes**.
> They share the same voice_v2 WebSocket but never run simultaneously.

### Architecture Overview

```
┌──────────────────────────────────────────────┐
│               Frontend                        │
│                                               │
│  ┌─────────────┐    ┌───────────────────────┐ │
│  │ Dictation    │    │ Full Voice Mode (FVM) │ │
│  │ #btnMic      │    │ full-voice-mode.js    │ │
│  │ Click toggle │    │ 7-state machine       │ │
│  └──────┬───────┘    └──────────┬────────────┘ │
│         │                       │              │
│         └───────┬───────────────┘              │
│                 ▼                               │
│     ┌───────────────────┐                      │
│     │  AudioCapture     │ ◄── onLevelUpdate    │
│     │  audio-capture.js │     (RMS from        │
│     └────────┬──────────┘      AudioWorklet)   │
│              ▼                                  │
│     ┌───────────────────┐                      │
│     │ WebSocket         │                      │
│     │ /api/ws/voice/v2  │                      │
│     └────────┬──────────┘                      │
└──────────────┼──────────────────────────────────┘
               ▼
┌──────────────────────────────────────────────┐
│           Backend (voice_v2.py)               │
│  PCM → STT → LLM (+screen context) → TTS    │
└──────────────────────────────────────────────┘
```

### Full Voice Mode State Machine

| State | Label | Behavior |
|:------|:------|:---------|
| `idle` | — | FVM off, chat UI visible |
| `listening` | Dinliyorum... | Mic active, waiting for speech (RMS > threshold) |
| `user_speaking` | Konuşuyor... | User is speaking, waveform active |
| `silence_countdown` | Sessizlik algılandı... | RMS < threshold for up to 3s, timer running |
| `processing` | İşleniyor... | audio_end sent, waiting for STT → LLM → TTS |
| `ai_speaking` | Yanıt veriliyor... | TTS playback, mic RMS ignored |
| `error` | ⚠️ [message] | Error shown, auto-recover after 2s |

### Silence Detection

- Threshold : `FVM_SILENCE_RMS_THRESHOLD = 0.01` (JS constant)
- Duration : `FVM_SILENCE_DURATION_MS = 3000` (3 seconds)
- Guard : `hasSpokeYet` — turn only closes after user has spoken at least once
- Implementation : Frontend-only via AudioWorklet RMS reports (~21ms granularity)

### Read-Aloud Endpoint

| Aspect | Detail |
|:-------|:-------|
| Endpoint | `POST /api/tts/read` |
| Request | `{ "text": "..." }` |
| Success | `200 audio/wav` — WAV bytes |
| Empty text | `400 { "error": "empty_text" }` |
| Too long | `400 { "error": "text_too_long", "max": 2000 }` |
| TTS off | `503 { "error": "tts_unavailable" }` |
| Failure | `500 { "error": "synthesis_failed" }` |

### TTS Playback Conflict Management

Single `activeAudio` reference in `app.js` prevents simultaneous playback:
- FVM TTS → `playAudioFromBase64()` → stops previous audio
- Read-aloud → `playAudio()` (blob URL) → stops previous audio
- Voice dictation TTS → `playAudio()` → stops previous audio

---

## Screen Context Policy (Sprint 6.1)

> [!IMPORTANT]
> Screen context is **automatic backend behavior**, not a manual user action.

### Design Principles

1. **Backend-driven** : The backend owns frame buffer, frame selection, artifact creation, and LLM injection
2. **Frontend-controlled** : Frontend only controls screen context ON/OFF toggle and optional live preview
3. **Unified across all paths** : Text chat (HTTP + WS), legacy voice, and voice_v2 binary all follow the same policy
4. **Privacy-first** : Screen context OFF = zero image data reaches the LLM

### Request-Time Frame Selection

| Path | Endpoint | Frame Selector | Artifact Builder |
|------|----------|---------------|------------------|
| HTTP chat | `POST /api/chat` | `get_best_frame()` | `build_artifact_from_frame()` |
| WS chat | `GET /api/ws/chat` | `get_best_frame()` | `build_artifact_from_frame()` |
| Legacy voice | `GET /api/ws/voice` | `get_best_frame()` | `build_artifact_from_frame()` |
| Voice v2 binary | `GET /api/ws/voice/v2` | `get_best_frame()` | `build_artifact_from_frame()` |
| Voice v2 legacy | `GET /api/ws/voice/v2` (fallback) | `get_best_frame()` | `build_artifact_from_frame()` |

### Frame Selection Priority

`get_best_frame()` → pin > ring buffer latest > None

- **Pin** : User hotkey (Ctrl+Shift+S) captures inference-quality frame, consumed once
- **Ring buffer** : Preview-quality frames from dxcam capture loop (1s interval)
- **grab_now()** : Explicit immediate capture (dxcam-first, PIL fallback) — reserved for pin/hotkey

### Frontend Behavior

- Screen context toggle : ON by default (`alwaysOnToggle`)
- No manual screenshot attachment — upload/drag-drop/paste flow removed
- Live preview sidebar shows capture status
- Pin indicator shows when a pinned frame will be used

### Backlog

- Temporal multi-frame selection (long-message start/end frame) — future sprint
- Input lifecycle tracking (`input_started_at`, `typing_duration`) — future sprint

---

## Privacy & Local-Only Contract

> [!CAUTION]
> VoxDesk is a **local-only** AI assistant. No user data leaves the machine.

### Guarantees

- **No cloud inference**: All STT, TTS, Translator, and LLM run from local model files
- **No telemetry**: No usage data, metrics, or logs sent externally
- **No CDN**: No external scripts, fonts, or stylesheets
- **No runtime downloads**: Models must be pre-installed; missing = fail
- **Localhost binding**: Server binds to `127.0.0.1` only
- **WebSocket origins**: Only `localhost` and `127.0.0.1` accepted, validated via `check_origin()` helper

### Config Enforcement

```yaml
privacy:
  offline_mode: true
  allow_cloud_providers: false
  allow_runtime_model_downloads: false
  allow_external_telemetry: false
  allow_cdn_assets: false

network:
  bind_host: "127.0.0.1"
  allowed_ws_origins:
    - "http://127.0.0.1:*"
    - "http://localhost:*"

model_loading:
  local_files_only: true
  fail_if_model_missing: true
```

### Regression Guards

These tests enforce the contract automatically:

| Test | File | What it guards |
|:---|:---|:---|
| `test_no_external_urls_in_python` | `test_regression.py` | No `http://` / `https://` to external domains in `src/` |
| `test_no_external_urls_in_frontend_js` | `test_voice_v2.py` | No external URLs in frontend JS |
| `test_no_external_urls_in_frontend_html` | `test_voice_v2.py` | No external URLs in frontend HTML |
| `test_no_cdn_script_in_frontend` | `test_voice_v2.py` | No CDN (jsdelivr, unpkg, googleapis, etc.) |
| `test_no_runtime_model_download_in_vram_tests` | `test_phase4_integration.py` | No `from_pretrained()` in VRAM tests |
| `test_isolation_env_guards` | `test_regression.py` | `HF_HUB_OFFLINE=1` enforced |

---

## LLM Providers

### Primary: `local-llama-server` (Gemma4 Sidecar)

The default LLM provider runs a **local llama-server subprocess** (sidecar):

| Property | Value |
|:---------|:------|
| Provider class | `LocalLlamaServerProvider` |
| Transport | `httpx` → `http://127.0.0.1:<port>` only |
| Protocol | OpenAI-compatible `/v1/chat/completions` — **local API format only, not OpenAI cloud** |
| Vision | `image_url` with `data:image/jpeg;base64,...` payload via libmtmd/mmproj |
| Lifecycle | `SidecarManager` — auto-start, health-check, graceful shutdown |
| Handler blocker | `Gemma4ChatHandler` is **not needed** — sidecar uses libmtmd natively |
| Security | Remote URLs rejected at constructor time (`ValueError`) |
| Logging | Base64 image data **never logged** — only metadata (size, source, endpoint) |

**Config** (`config/default.yaml`):
```yaml
llm:
  provider: "local-llama-server"
local_llama_server:
  enabled: true
  base_url: "http://127.0.0.1:8081"
  model_path: "models/gemma-4-E4B-uncensored/...Q8_K_P.gguf"
  mmproj_path: "models/gemma-4-E4B-uncensored/...f16.gguf"
  jinja: true        # required for Gemma4 chat template
  auto_start: true
```

### Fallback: `llama-cpp` (In-Process)

`LlamaCppProvider` loads models in-process via llama-cpp-python with automatic vision handler resolution:

### Handler Priority (First Match Wins)

| Pattern Keywords | Resolved Handler | Status |
|:---|:---|:---|
| `qwen2.5-vl`, `qwen25vl`, `qwen` | `Qwen25VLChatHandler` | ✅ Available |
| `minicpm` | `MiniCPMv26ChatHandler` | ✅ Available |
| `llava` | `Llava16ChatHandler` | ✅ Available |
| `gemma-4`, `gemma4`, `e4b`, `e2b` | `Gemma4ChatHandler` | ❌ Not in v0.3.21 |
| `gemma-3`, `gemma3`, `gemma` | `Gemma3ChatHandler` | ❌ Not in v0.3.21 |
| `qwen3-vl`, `qwen3vl` | `Qwen3VLChatHandler` | ❌ JamePeng fork only |

> **Note**: Gemma4 vision is fully operational via the sidecar provider. The missing `Gemma4ChatHandler` in llama-cpp-python is **no longer a blocker**.

### Visual Token Budget

```yaml
llm:
  vision_budget_preset: null  # null | screen_fast | screen_balanced | screen_ocr
  n_ubatch: 1024              # crash guard: budget only applied if n_ubatch >= max_tokens
```

| Preset | `image_min_tokens` | `image_max_tokens` | Use Case |
|:---|:---:|:---:|:---|
| `screen_fast` | 280 | 280 | Quick screen glance |
| `screen_balanced` | 560 | 560 | General screen understanding |
| `screen_ocr` | 1120 | 1120 | Dense text / small font OCR |

---

## Image Pipeline Quality

### Dual Quality Path

| Path | Resolution | Quality | Purpose |
|:---|:---:|:---:|:---|
| Preview (`ws_screen`) | 1280px max | Q85 | WebSocket live preview |
| Inference (`grab_now`, `pinned_frame`, `voice_screen`) | 1920px max | Q92 | LLM vision input |
| Upload (user-provided) | Original | Original | Never recompressed |

### CanonicalImageArtifact

All image sources pass through `CanonicalImageArtifact` before reaching the LLM:
- Uniform interface for `ws_screen`, `pinned_frame`, `grab_now`, and `upload`.
- Image history stores only references — **no raw/base64 in conversation history**.
- `ImageMetadata` tracks source, resolution, format, byte size, and content hash.

---

## Audio Protocol v1

### Overview

Binary PCM audio transfer over WebSocket at `/ws/voice/v2`.

| Property | Value |
|:---|:---|
| Encoding | `pcm_s16le` (signed 16-bit little-endian) |
| Sample rate | 16000 Hz |
| Channels | 1 (mono) |
| Chunk duration | 20ms (320 samples = 640 bytes) |
| Max frame | 64 KB (config-backed via `SecurityConfig.max_ws_frame_bytes`) |
| Sequence counter | Server-side only |
| Client timestamp | None (v1) |
| Protocol version | 1 |

### Handshake Flow

```
Client                              Server
  │                                    │
  ├─── audio_config (JSON) ──────────►│
  │    {                               │
  │      "type": "audio_config",       │
  │      "protocol_version": 1,        │
  │      "encoding": "pcm_s16le",      │
  │      "sample_rate": 16000,         │
  │      "channels": 1,               │
  │      "chunk_ms": 20               │
  │    }                               │
  │                                    │
  │◄── audio_config_ack (JSON) ───────┤
  │    {                               │
  │      "type": "audio_config_ack",   │
  │      "accepted": true,             │
  │      "protocol_version": 1,        │
  │      "encoding": "pcm_s16le",      │
  │      "sample_rate": 16000          │
  │    }                               │
  │                                    │
  ├─── binary PCM frames ────────────►│  (repeated)
  │                                    │
  ├─── audio_end (JSON) ─────────────►│
  │    {"type": "audio_end"}           │
  │                                    │
  │◄── stt_result / stt_empty ────────┤
  │◄── llm_response ─────────────────┤
  │◄── tts_audio (base64 WAV) ───────┤
```

### Error Responses

```json
{
  "type": "protocol_error",
  "error": "Human-readable description",
  "code": "error_code"
}
```

| Code | Trigger |
|:---|:---|
| `binary_before_handshake` | Binary frame before `audio_config` |
| `invalid_config` | Bad protocol_version, encoding, sample_rate |
| `invalid_frame` | Odd bytes, oversized, too small |
| `invalid_json` | Unparseable text frame |
| `empty_frame` | Empty/whitespace text frame |
| `no_handshake` | `audio_end` before `audio_config` |
| `unknown_type` | Unrecognized message type |
| `oversized_base64` | Legacy base64 > 256KB |
| `invalid_base64` | Base64 decode failure |

### Frame Validation Rules

1. **Even byte count** — 16-bit samples require `len(data) % 2 == 0`
2. **Min size** — At least 2 bytes (1 sample)
3. **Max size** — Config-backed via `SecurityConfig.max_ws_frame_bytes` (default 64 KB)
4. **Handshake required** — Binary frames rejected before `audio_config`

### PCM Decode

```python
samples = np.frombuffer(data, dtype="<i2")       # S16LE
audio = samples.astype(np.float32) / 32768.0      # normalize to [-1.0, 1.0]
```

### Legacy Base64 Path

The original `/ws/voice` endpoint and base64 JSON format are **preserved**:

```json
{"type": "audio", "audio": "<base64>", "format": "webm"}
```

This path works when `enable_binary_audio=false` (default).

---

## Frontend Audio Capture

### AudioWorklet (Primary)

`audio-processor.js` runs in the AudioWorklet thread:
- Receives Float32 samples from `getUserMedia`
- Converts to Int16 PCM with clamping
- Transfers via `postMessage` with `Transferable` (zero-copy)

`audio-capture.js` manages the capture lifecycle:
- Linear-interpolation downsampling: 48kHz/44.1kHz → 16kHz
- Binary `ws.send(ArrayBuffer)` for each PCM chunk
- Sends `audio_config` handshake before first binary frame
- Sends `audio_end` on stop

### MediaRecorder Fallback

If `AudioWorklet` is unavailable or fails:
- Falls back to `MediaRecorder` with `audio/webm;codecs=opus`
- Sends audio as base64 JSON via legacy path
- `timeslice=250ms` for chunked recording
- Blob size limit: 64KB per chunk

### getUserMedia Error States

| Error | Behavior |
|:---|:---|
| Permission denied | Throws — UI must catch and display |
| No device | Throws — same handling |
| Device busy | Throws — same handling |
| AudioWorklet addModule fail | Falls back to MediaRecorder |
| `processorerror` event | Falls back to MediaRecorder |

---

## VRAM & Model Lifecycle

### State Machine

```
UNLOADED ──load()──► LOADING ──success──► LOADED
                        │                    │
                      fail                acquire()
                        │                    │
                        ▼                    ▼
                     UNLOADED             IN_USE
                                            │
                                         release()
                                            │
                                            ▼
                    UNLOADED ◄──unload()── LOADED
```

### Unload Guards (5)

| Guard | Condition | Effect |
|:---|:---|:---|
| ref_count | `ref_count > 0` | Block unload |
| keep_warm | `keep_warm=True` | Block unload |
| min_loaded | `loaded_time < min_loaded_seconds` | Block unload |
| cooldown | `time_since_unload < cooldown_seconds` | Block unload |
| already_unloaded | `state == UNLOADED` | No-op |

### Config

```yaml
vram:
  monitor_interval_seconds: 30.0
  stt_idle_unload_seconds: 180.0    # 0 = disable
  tts_idle_unload_seconds: 180.0    # 0 = disable
  min_loaded_seconds: 30.0
  unload_cooldown_seconds: 10.0
  keep_warm: false
```

---

## Feature Flags

All flags are **restart-only** (no runtime toggle):

| Flag | Default | Description |
|:---|:---:|:---|
| `enable_module_registry` | `true` | DI registry |
| `enable_vram_unload` | `true` | Idle model unload |
| `enable_binary_audio` | `false` | Binary PCM transfer |
| `enable_audioworklet` | `false` | AudioWorklet capture |
| `enable_mediarecorder_fallback` | `true` | MediaRecorder fallback |
| `enable_debug_metrics` | `false` | `/api/debug/metrics` (returns 403 when disabled) |
| `enable_debug_capture_export` | `false` | Write LLM-bound image bytes to `data/debug_frames/` (dev only) |

> **Note**: VRAM monitor only starts when `enable_vram_unload` is `true`. When `false`, `VRAMManager` is still created for reporting but the idle-unload background task does not run.

---

## Health Endpoints

### `/api/health` (Public)

Minimal, safe to expose. **No** model names, paths, VRAM, or registry info.

```json
{
  "status": "ok",
  "version": "0.7.2",
  "uptime_seconds": 42.5,
  "degraded": false
}
```

### `/api/status` (Runtime State)

Safe runtime snapshot with model states, capture status, connections, and feature flags. **No** filesystem paths or secrets.

```json
{
  "api": {
    "status": "ok",
    "version": "0.7.2",
    "uptime_seconds": 42.5,
    "degraded": false
  },
  "capture": {
    "running": true,
    "latest_frame_age_ms": 80
  },
  "screen_context_enabled": true,
  "connections": {
    "chat": { "count": 1, "state": "connected" },
    "screen": { "count": 1, "state": "connected" },
    "voice": { "count": 0, "state": "idle" },
    "voice_v2": { "count": 0, "state": "idle" }
  },
  "models": {
    "stt": { "name": "large-v3-turbo", "state": "LOADED" },
    "llm": { "name": "Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf", "state": "LOADED" },
    "tts": { "name": "af_heart", "state": "UNLOADED" },
    "translator": { "name": null, "state": "UNAVAILABLE" }
  },
  "llm_provider": {
    "provider": "local-llama-server",
    "has_vision": true,
    "server_available": true
  },
  "sidecar": {
    "running": true,
    "healthy": true
  },
  "features": {
    "enable_module_registry": true,
    "enable_vram_unload": true,
    "enable_binary_audio": false,
    "enable_audioworklet": false,
    "enable_mediarecorder_fallback": true,
    "enable_debug_metrics": false
  },
  "last_error": null,
  "last_error_time": null
}
```

### `/api/debug/metrics` (Dev/Debug)

Full process-local metrics. **Gated by `enable_debug_metrics` feature flag** — returns HTTP 403 when disabled (default: disabled).

Contains: registry catalog, engine config, VRAM model states, sliding-window percentiles.

Includes `"_scope": "process-local"` marker.

---

## Running Tests

```bash
# Full suite (includes benchmarks)
python -m pytest

# Quick (no benchmarks)
python -m pytest --no-benchmarks

# With coverage
python -m pytest --cov=src --cov-fail-under=55

# Only regression tests
python -m pytest -m regression

# Only unit tests
python -m pytest -m unit

# Only benchmarks (report-only)
python -m pytest -m benchmark --benchmark-only

# Specific module
python -m pytest tests/test_audio_protocol.py -v
```

### Test Categories

| Marker | Count (approx.) | Purpose |
|:---|:---:|:---|
| `unit` | ~180+ | Core logic |
| `regression` | ~85+ | Privacy, isolation, config mapping, endpoint contracts, prompt safety, audit fixes |
| `benchmark` | 4 | Performance baselines |
| `gpu` | 1 | GPU smoke (skipped if no CUDA) |
| (handler/budget) | ~40 | Vision handler resolution + budget plumbing |
| (quality parity) | ~16 | Image quality pipeline |
| (image metadata) | ~24 | CanonicalImageArtifact + ImageMetadata |

> **Note**: Test counts are approximate and grow with each sprint. Run `pytest --co -q` for exact current count.

### Coverage

- **Target**: ≥55% (`--cov-fail-under=55`)
- **Current**: ~65%
- **Low coverage modules**: Route handlers (23–51%) — require real WebSocket/HTTP integration tests

### WebSocket Origin Validation

`ConnectionManager.connect()` accepts an `allowed_origins` parameter. The `check_origin()` helper supports:

- Exact matches (e.g. `http://127.0.0.1:8765`)
- Wildcard port patterns (e.g. `http://localhost:*`)
- Missing Origin header is allowed for non-browser/test clients

Rejection uses the accept-then-close pattern (Starlette requires `accept()` before `close()`).

---

## Module Registry

Factory catalog with immutable registrations:

```python
# Startup (lifespan) — register factories ONCE
registry.register("stt", "faster-whisper", lambda cfg: SpeechRecognizer(...))

# Startup — create instances ONCE
state.stt = registry.create("stt", config.stt.engine, config.stt)

# Request path — NEVER call registry.create()
# Use: state = get_app_state(); state.stt.transcribe_audio(...)
```

**Config validation**: All models use `extra='forbid'` — unknown fields cause startup failure.

---

## Shutdown Sequence

```python
async def _safe_shutdown():
    # Each component in isolated try/except
    # Order: VRAM monitor → Capture → STT → TTS → LLM → Hotkeys → Tray
    # Individual failures don't crash other cleanups
```

`_safe_shutdown()` is async — properly awaits `vram_manager.stop_monitor()`. Shutdown order: VRAM → Capture → STT → TTS → Translator → LLM → Hotkeys → Tray.
