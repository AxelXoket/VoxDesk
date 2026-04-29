# VoxDesk Architecture — Production Reference

> **Version**: v0.6.0 — Sprint 5.3: Vision Pipeline + Handler Resolution + Qwen3-VL Feasibility  
> **Runtime**: Python 3.12 + FastAPI + Uvicorn  
> **Inference**: Local-only (Whisper STT, MarianMT Translator, Kokoro TTS, llama-cpp-python LLM)  
> **GPU**: RTX 5080 (Blackwell, SM 12.0) — CUDA 12.8  
> **Audio**: PCM binary WebSocket (v1) + legacy base64 fallback  
> **Voice Pipeline**: Mic → STT (auto-detect TR/EN) → Translator (TR→EN) → LLM (EN) → TTS (EN) → Speaker

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

## Vision Handler Resolution

`LlamaCppProvider` resolves the correct vision chat handler based on model filename pattern matching:

### Handler Priority (First Match Wins)

| Pattern Keywords | Resolved Handler | Status |
|:---|:---|:---|
| `gemma-4`, `gemma4`, `e4b`, `e2b` | `Gemma4ChatHandler` | ❌ Not in v0.3.21 |
| `gemma-3`, `gemma3`, `gemma` | `Gemma3ChatHandler` | ❌ Not in v0.3.21 |
| `qwen3-vl`, `qwen3vl`, `qwen3_vl`, `qwen3` | `Qwen3VLChatHandler` | ❌ Not in v0.3.21 (JamePeng fork only) |
| `qwen2.5-vl`, `qwen25vl`, `qwen2_5`, `qwen` | `Qwen25VLChatHandler` | ✅ Available |
| `minicpm` | `MiniCPMv26ChatHandler` | ✅ Available |
| `llava` | `Llava16ChatHandler` | ✅ Available |

### Explicit Override

```yaml
llm:
  chat_handler: auto  # auto | gemma4 | gemma3 | qwen3vl | qwen25vl | minicpm | llava
```

When set to `auto` (default), the provider resolves handler from model filename. When set explicitly, the specified handler is used directly — bypasses pattern matching.

### Missing Handler Policy

If a handler is resolved but not available in the installed `llama-cpp-python` build, the provider:
1. Logs a **clear warning** with the missing handler name.
2. Falls back to auto-detect (degraded vision).
3. **Does NOT silently substitute** another handler (e.g., Qwen25 for Qwen3).

### Visual Token Budget

```yaml
llm:
  vision_budget_preset: null  # null | screen_fast | screen_balanced | screen_ocr
  n_ubatch: 1024              # crash guard: budget only applied if n_ubatch >= max_tokens
```

| Preset | `image_min_tokens` | `image_max_tokens` | Use Case |
|:---|:---:|:---:|:---|
| `screen_fast` | 64 | 256 | Quick screen glance |
| `screen_balanced` | 256 | 768 | General screen understanding |
| `screen_ocr` | 512 | 1536 | Dense text / small font OCR |

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
| `enable_vram_unload` | `false` | Idle model unload |
| `enable_binary_audio` | `false` | Binary PCM transfer |
| `enable_audioworklet` | `false` | AudioWorklet capture |
| `enable_mediarecorder_fallback` | `true` | MediaRecorder fallback |
| `enable_debug_metrics` | `false` | `/api/debug/metrics` (returns 403 when disabled) |

> **Note**: VRAM monitor only starts when `enable_vram_unload` is `true`. When `false`, `VRAMManager` is still created for reporting but the idle-unload background task does not run.

---

## Health Endpoints

### `/api/health` (Public)

Minimal, safe to expose. **No** model names, paths, VRAM, or registry info.

```json
{
  "status": "ok",
  "version": "0.5.0",
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
    "version": "0.5.0",
    "uptime_seconds": 42.5,
    "degraded": false
  },
  "capture": {
    "running": true,
    "latest_frame_age_ms": 80
  },
  "connections": {
    "chat": { "count": 1, "state": "connected" },
    "screen": { "count": 1, "state": "connected" },
    "voice": { "count": 0, "state": "idle" },
    "voice_v2": { "count": 0, "state": "idle" }
  },
  "models": {
    "stt": { "name": "large-v3-turbo", "state": "LOADED" },
    "llm": { "name": "MiniCPM-V-4.5-Q6_K", "state": "LOADED" },
    "tts": { "name": "af_heart", "state": "UNLOADED" }
  },
  "features": {
    "enable_module_registry": true,
    "enable_vram_unload": false,
    "enable_binary_audio": false,
    "enable_audioworklet": false,
    "enable_mediarecorder_fallback": true,
    "enable_debug_metrics": false
  },
  "last_error": null
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

| Marker | Count | Purpose |
|:---|:---:|:---|
| `unit` | ~175 | Core logic |
| `regression` | ~83 | Privacy, isolation, config mapping, endpoint contracts, prompt safety, audit fixes |
| `benchmark` | 4 | Performance baselines |
| `gpu` | 1 | GPU smoke (skipped if no CUDA) |
| (handler/budget) | 39 | Vision handler resolution + budget plumbing |
| (quality parity) | 16 | Image quality pipeline |
| (image metadata) | ~20 | CanonicalImageArtifact + ImageMetadata |

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
