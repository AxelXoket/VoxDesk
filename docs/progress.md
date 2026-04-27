# VoxDesk — Development Progress

> Tracks completed work across all development phases.
> Last updated: 2026-04-27

---

## 2026-04-25 (Friday) — Pre-Sprint Foundation

### Phase 1–6: Foundation → Polish ✅

Built from scratch as a privacy-first, offline desktop AI assistant with voice + screen capture.

**What was done:**
- Configured `pyproject.toml` as single source of truth for pytest
- Registered custom markers: `unit`, `regression`, `benchmark`, `gpu`
- Set up `pytest-asyncio` with `auto` mode, coverage threshold at 55%
- Implemented `src/metrics.py` with sliding-window percentile tracking (process-local, never external)
- Implemented `src/registry.py` — factory catalog with immutable registrations
- Created `src/protocols.py` — abstract interfaces for STT, TTS, LLM, Capture
- Hardened all Pydantic config models with `extra='forbid'`
- Added privacy/network/model_loading config sections
- Implemented `src/model_state.py` — `ManagedModel` with 6-state machine (UNLOADED → LOADING → LOADED → IN_USE → UNLOADING → UNLOADED)
- Implemented `src/vram_manager.py` — background monitor with idle unload policy
- Integrated STT (`src/stt.py`) and TTS (`src/tts.py`) with ManagedModel lifecycle
- Defined audio protocol in `src/audio_protocol.py` (PCM S16LE, 16kHz, mono, 20ms chunks)
- Implemented `/ws/voice/v2` binary audio WebSocket endpoint
- Created `frontend/js/audio-processor.js` (AudioWorklet) + `frontend/js/audio-capture.js`
- MediaRecorder fallback for browsers without AudioWorklet
- Created `ARCHITECTURE.md`, `SMOKE_TEST.md`
- Hardened `/api/health` — no secrets exposed
- Feature flags: `enable_binary_audio`, `enable_audioworklet`, `enable_vram_unload`
- Safe shutdown sequence with isolated try/except per component

**Branding:**
- Renamed to **VoxDesk**, created **Voxly** personality
- All logger namespaces to `voxdesk.*`, CLI entry point to `voxdesk`
- Professional README with architecture diagram, privacy contract

**Pre-commit audit:**
- Zero API keys, tokens, secrets, personal paths, telemetry, analytics, `.env` files
- All external URLs verified: only `ollama.com` and `espeak-ng` (setup links)
- `.gitignore` covers caches, IDE, secrets, models, audio, coverage, containers

**Verification:**
- 348 tests passing, 65% coverage

---

## 2026-04-26 (Saturday) — 03:00 — Sprint 1: Foundation Hardening

### Sprint 1: Config Mapping + API + Security ✅

**Baseline:** 348 tests → 381 tests (+33) · Regression: 26 → 59 (+33)

**What was done:**

**Task 1 — Config Mapping:**
- Added 6 missing YAML→Pydantic section mappings to `load_config()`: `features`, `network`, `privacy`, `model_loading`, `security`, `vram`
- Added corresponding sections to `config/default.yaml` with Pydantic-matching defaults
- 8 new regression tests in `test_config.py`

**Task 2 — /api/status Endpoint:**
- Created `GET /api/status` returning safe runtime state: `api`, `capture`, `connections`, `models`, `features`, `last_error`
- Models expose `name` + `state` only (no filesystem paths)
- 6 new regression tests in `test_routes.py`

**Task 3 — app.js Health/Status Migration:**
- Rewrote `checkHealth()` to use `/api/health` for availability + `/api/status` for runtime state
- Eliminated `data.model.split('/')` crash
- Added graceful degradation when `/api/status` unavailable
- 3 new regression tests in `test_regression.py`

**Task 4 — Debug Metrics Feature Flag:**
- Guarded `/api/debug/metrics` with `config.features.enable_debug_metrics`
- Returns HTTP 403 when disabled (default: disabled)
- 2 new regression tests in `test_routes.py`

**Task 5 — WebSocket Origin Validation:**
- Added `check_origin()` helper supporting exact + wildcard port patterns
- Modified `ConnectionManager.connect()` to accept `allowed_origins` parameter
- Uses accept-then-close pattern (Starlette requires accept before close)
- Missing Origin → allowed (non-browser/test client compatibility)
- 5 new regression tests in `test_routes.py`

**Task 6 — audio-capture.js Loading:**
- Added `<script src="/static/js/audio-capture.js">` in correct order in `index.html`
- `audio-processor.js` correctly NOT loaded as script tag (AudioWorklet only)
- 3 new regression tests in `test_regression.py`

**Task 7 — Voxly Prompt Hardening:**
- Replaced `"Never refuse to help"` → refusal of unsafe/illegal/harmful requests
- Replaced `"Respond in the same language"` → English default + Turkish understanding
- 4 new regression tests in `test_regression.py`

**Task 8 — VRAM Monitor Feature Flag:**
- Guarded `vram_manager.start_monitor()` with `config.features.enable_vram_unload`
- VRAMManager still created for reporting; monitor only runs when flag is `true`
- 2 new regression tests in `test_routes.py`

**Verification:**
- 381 tests passing, 59 regression tests
- Zero regressions from existing 348 tests

---

## 2026-04-26 (Saturday) — 08:00 — Sprint 2: Voice Wiring

### Sprint 2: Binary Audio Protocol + Voice Pipeline ✅

**Baseline:** 381 → 382 tests · Regression: 59 (preserved)

**What was done:**
- Wired audio_config/audio_end/audio_cancel message handlers
- Implemented PCM binary frame reception with handshake enforcement
- Added STT → LLM → TTS pipeline in `_process_audio_buffer()`
- Structured error responses: `LLM_FAILED`, `TTS_FAILED`, `voice_error`
- LLM/TTS metrics: `llm_errors_total`, `tts_latency_ms`
- Legacy base64 audio path preserved for backward compatibility
- No voice auto-reconnect — user manual retry (design decision)

**Verification:**
- 382 tests passing, 59 regression tests

---

## 2026-04-26 (Saturday) — 16:00 — Sprint 3: Observability

### Sprint 3: DEV HUD + Metrics + Multi-Frame Vision ✅

**What was done:**
- Added DEV HUD glassmorphism overlay to frontend
- Created `src/audio_utils.py` — extracted shared audio decoding logic
- Upgraded `_build_messages` for multi-frame image input
- Added `llm_frame_count` configuration field
- Refactored chat/voice routes to use `audio_utils`
- Fixed cross-import issues between chat.py and voice_v2.py

**Verification:**
- 382 tests passing, 59 regression tests

---

## 2026-04-26 (Saturday) — 22:00 — Sprint 3 Post-Audit

### Sprint 3 Post-Audit: Cross-Reference Review ✅

Completed dual-AI cross-reference audit against Sprint 3 Post-Audit Report (15 findings).

**What was done:**
- Verified outbound deny-by-default compliance (zero external URLs in codebase)
- Confirmed `local_files_only: true` and `allow_runtime_model_downloads: false` enforcement
- Verified `/api/status` and `/api/settings` do not expose secrets/paths/credentials
- Identified 5 critical blockers and 4 hardening items for Sprint 3.5
- Created `docs/security_privacy_policy.md` — formal privacy contract

**Critical blockers identified:**
1. WS Origin validation helper exists but routes don't pass `allowed_origins`
2. `AppState.record_error()` defined but never called (DEV HUD empty)
3. Voice socket close doesn't stop AudioCapture (mic leak risk)
4. Frontend ignores feature flags for voice mode
5. STT exceptions fall through to generic WS disconnect

---

## 2026-04-27 (Sunday) — 02:15 — Sprint 3.5: Runtime Hardening

### Sprint 3.5: 9-Task Hardening Patch ✅

**Baseline:** 382 tests → 382 tests (zero regression) · Regression: 59 (preserved)

Addressed all 9 issues from the Master Risk & Hardening Report. No new features — only existing claims made real.

**What was done:**

**Task 1 — WS Origin Enforcement:**
- Made `ConnectionManager` config-aware via `set_allowed_origins()` injection
- All WS routes now enforce Origin validation automatically (no route code changes)
- Wired in `main.py` startup alongside existing `set_metrics()` pattern

**Task 2 — record_error() Wiring:**
- Connected `AppState.record_error()` to 5 exception paths:
  - Chat LLM stream error, Chat WS generic error
  - Voice WS generic error, STT error, Voice LLM error
- DEV HUD `last_error` now populated with real error messages

**Task 3 — Voice CONNECTING Guard + Close/Error Cleanup:**
- Added `WebSocket.CONNECTING` guard to `connectVoice()` preventing duplicate sockets
- Added `voice:disconnected` and `voice:error` cleanup handlers in `app.js`
- Cleanup stops AudioCapture, clears mic/TTS queue, resets UI state
- No auto-reconnect (Sprint 2 design decision preserved)

**Task 4 — Frontend Voice Feature Flags:**
- Cached `features` from `/api/status` in `_cachedFeatures` global
- Voice mode activation checks `enable_binary_audio` and `enable_mediarecorder_fallback`
- Disabled voice shows user warning, does not connect WS
- `AudioCapture` receives `useBinary` option from feature flags

**Task 5 — AudioCapture Transport Adapter:**
- Replaced raw `WebSocket` parameter with `{sendControl, sendBinary, isOpen}` transport adapter
- `app.js` creates transport from `VoxWebSocket` methods (centralized send/receive)
- Backwards compat: raw WS auto-wrapped with deprecation warning (safety net only)
- Zero `this.ws.send` calls remain in `audio-capture.js`

**Task 6 — MediaRecorder Fallback Stop Ordering:**
- Mode-aware `stop()`: worklet sends `audio_end`, MediaRecorder does not
- Prevents `audio_end` arriving before legacy audio payload

**Task 7 — ACK Pending Buffer Bound/Timeout:**
- `_maxPendingChunks = 10` — excess drops oldest chunk
- `_ackTimeoutMs = 3000` — no ACK → auto-stop capture
- ACK received → timer cleared immediately

**Task 8 — STT_FAILED Structured Error:**
- Wrapped STT `run_in_executor()` call with `try/except`
- On failure: `stt_errors_total` metric incremented, `record_error()` called
- Frontend receives structured `{"type":"voice_error","code":"STT_FAILED","message":"...","recoverable":true}`

**Task 9 — Docs Sync:**
- Updated `docs/PROGRESS.md` with Sprint 3.5 section (this file)
- Created `docs/dependency_matrix.md` — CUDA/package compatibility for RTX 5080 Blackwell
- Created `docs/local_smoke_checklist.md` — manual verification gate for Sprint 4

**Key security decisions:**
- `security_privacy_policy.md` now formal project policy
- WS Origin enforcement automatic via config injection
- No route-level opt-out possible without changing ConnectionManager config

**Verification:**
- 382 tests passing, 3 skipped
- 59 regression tests passing
- Zero regressions
- Static checks: zero `this.ws.send` in audio-capture.js, 5 `record_error()` call sites confirmed

**Sprint 4 gate status:**
- All 9 code tasks ✅
- Dependency matrix ✅
- Local smoke checklist ✅ (manual execution pending real hardware)

---

## 2026-04-27 (Sunday) — 03:00 — Local Smoke Execution

### Real Hardware Smoke: RTX 5080 + Windows ✅

First-ever real hardware deployment of VoxDesk.

**Environment:**
- Python 3.12.10, pip 26.1
- PyTorch 2.11.0+cu128 (CUDA 12.8)
- NVIDIA RTX 5080, compute capability (12, 0)
- Windows, 2560×1440 primary monitor

**Results:**
- All import smokes passed (fastapi, uvicorn, pydantic, faster-whisper, ctranslate2 4.7.1, kokoro, dxcam, sounddevice)
- dxcam frame capture: 1440×2560×3 ✅
- Audio IO: 33 devices detected ✅
- Full test suite: 383 passed, 2 skipped ✅
- Server boot: all components loaded, `127.0.0.1:8765` ✅
- Frontend UI: fully loaded with all elements ✅
- `/api/health` → ok, `/api/status` → no secrets, `/api/debug/metrics` → 403 ✅
- Privacy: `HF_HUB_OFFLINE=1`, `OLLAMA_NO_CLOUD=1`, `TRANSFORMERS_OFFLINE=1` ✅

**Issues discovered & fixed:**
1. `opencv-python-headless` missing → added to requirements.txt
2. `get_uptime_seconds()` round(,1) flaky → fixed to round(,2)

---

## 2026-04-27 (Sunday) — 03:10 — Sprint 3.6: Micro Patch

### Screen WS Broadcast Cleanup ✅

**Baseline:** 383 tests (preserved)

**Problem:** Browser kapandıktan sonra screen WS route, kapalı socket'e her saniye `send_json` denemeye devam ediyordu. `ConnectionManager.send_json` hatayı yakalayıp logluyordu ama döngüyü kırmıyordu → log spam.

**Fix:** Screen route'ta `send_json` yerine doğrudan `websocket.send_json` kullanılarak, exception'da `break` + `finally` ile `disconnect()` çağrısı yapıldı. `WebSocketDisconnect` handler'ı `pass` ile temizlendi (cleanup artık `finally`'de).

**Verification:**
- 383 passed, 2 skipped ✅
- Zero regressions
- **Live runtime verified:** Server started → browser connected (chat + screen WS) → browser closed → clean disconnect with zero "Cannot call send" errors in log. Before fix: ~30 error lines per 30 seconds. After fix: 2 clean `WS ayrıldı` lines.

---

## 2026-04-27 (Sunday) — 07:00 — Sprint 4: CUDA Setup & Model Deploy

### Sprint 4 Phase 1: Pure Local LLM Infrastructure ✅

**Baseline:** 390 tests (preserved) · Regression: 59 (preserved)

First-ever local LLM inference on VoxDesk — no Ollama, no cloud, pure llama-cpp-python.

**What was done:**

**CUDA Toolkit Setup:**
- Installed CUDA Toolkit 12.8.61 alongside existing 13.2
- Removed CUDA 13.2 MSBuild targets to prevent version conflict
- CUDA 12.8 aligns with PyTorch 2.11.0+cu128 runtime DLLs

**llama-cpp-python Build:**
- Source-compiled llama-cpp-python 0.3.20 with CUDA 12.8
- Build flags: `DGGML_CUDA=on`, `CMAKE_CUDA_ARCHITECTURES=120` (SM 12.0 Blackwell)
- Result: `ggml-cuda.dll` (57 MB) — GPU kernel'ları dahil
- cmake 4.3.2 installed in venv for build

**Model Deployment:**
- Created `models/minicpm-v4.5-official/` directory structure
- Downloaded `model-q6_k.gguf` (6.26 GB) — MiniCPM-V 4.5 Official Q6_K
- Downloaded `mmproj-f16.gguf` (1.02 GB) — Vision projector (SigLip2-400M + 3D-Resampler)
- Source: `openbmb/MiniCPM-V-4_5-gguf` (official HuggingFace repo)
- `models/minicpm-v4.5-abliterated/` klasörü hazır, kullanıcı onayı bekleniyor

**Config Update:**
- `config/default.yaml` → `model_path` ve `mmproj_path` gerçek dosya yollarına güncellendi
- Fallback paths abliterated model için ayrılmış (null — pending approval)

**First Inference:**
- Model GPU'ya yüklendi (n_gpu_layers=-1, full offload)
- Prompt: "Say hello in one sentence."
- Response: "Hello! How can I assist you today?"
- Inference latency: <2 saniye

**Documentation Sync:**
- `requirements.txt` — Sprint 4 header, SM 120 arch
- `docs/architecture.md` — v0.2.0, Ollama→llama-cpp-python, model name güncellendi
- `docs/dependency_matrix.md` — Tüm bağımlılıklar doğrulanmış (⏳→✅)
- `docs/local_smoke_checklist.md` — LLM smoke eklendi, compute capability düzeltildi
- `docs/PROGRESS.md` — Bu bölüm eklendi

**Verification:**
- 390 tests passing, 1 skipped ✅
- Zero regressions
- LLM text inference: PASSED
- GPU offload: PASSED (full VRAM)

**Next steps:**
- 3D-Resampler vision testi (single image → multi-image → 6-frame temporal)
- Abliterated model indirme (kullanıcı onayı ile)
- End-to-end pipeline: STT → LLM (with screen) → TTS
