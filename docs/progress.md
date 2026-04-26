# VoxDesk — Development Progress

> Tracks completed work across all development phases.
> Last updated: 2026-04-26

---

## Phase 1 — CI & Regression Foundation

- Configured `pyproject.toml` as single source of truth for pytest
- Registered custom markers: `unit`, `regression`, `benchmark`, `gpu`
- Set up `pytest-asyncio` with `auto` mode
- Set coverage threshold at 55% (`--cov-fail-under=55`)
- Created `run_tests.py` wrapper for quick/full/benchmark modes
- Established `tests/conftest.py` with autouse cleanup fixtures
- Added AppState, metrics, config, and background task reset between tests

## Phase 2 — Metrics Baseline

- Implemented `src/metrics.py` with sliding-window percentile tracking
- Added request counting, latency histograms, and error rate tracking
- Created VRAM report integration (torch.cuda optional)
- All metrics scoped as `process-local` — never exposed externally
- Added `reset_for_tests()` for test isolation

## Phase 3 — Module Registry & Config Hardening

- Implemented `src/registry.py` — factory catalog with immutable registrations
- Created `src/protocols.py` — abstract interfaces for STT, TTS, LLM, Capture
- Hardened all Pydantic config models with `extra='forbid'`
- Added privacy config section: `offline_mode`, `allow_cloud_providers`, etc.
- Added network config: `bind_host`, `allowed_ws_origins`
- Added model loading config: `local_files_only`, `fail_if_model_missing`
- Refactored `main.py` startup to use registry + lifespan pattern
- Wired all subsystems through `AppState` — no global singletons

## Phase 4 — VRAM Manager & Model Lifecycle

- Implemented `src/model_state.py` — `ManagedModel` with 6-state machine
  - States: UNLOADED → LOADING → LOADED → IN_USE → UNLOADING → UNLOADED
- Added 5 unload guards: ref_count, keep_warm, min_loaded, cooldown, already_unloaded
- Implemented `src/vram_manager.py` — background monitor with idle unload policy
- Integrated STT (`src/stt.py`) with ManagedModel pattern
  - `acquire()` / `release()` context for active transcription
  - `safe_unload()` respects ref_count and cooldown
- Integrated TTS (`src/tts.py`) with same lifecycle
- Added VRAM config section: `monitor_interval`, `idle_unload`, `min_loaded`, `cooldown`
- All GPU paths guarded by `torch.cuda.is_available()`
- No runtime model downloads — missing model = fail

## Phase 5 — AudioWorklet Binary Protocol

- Defined audio protocol constants in `src/audio_protocol.py`
  - PCM S16LE, 16kHz, mono, 20ms chunks, 64KB max frame
- Implemented `/ws/voice/v2` WebSocket endpoint with binary receive loop
- Added handshake flow: `audio_config` → `audio_config_ack` → binary frames → `audio_end`
- Frame validation: even byte count, min/max size, handshake-before-binary
- Protocol error responses with typed error codes
- Created `frontend/js/audio-processor.js` — AudioWorklet thread (Float32 → Int16)
- Created `frontend/js/audio-capture.js` — capture lifecycle with linear-interpolation resampler
- MediaRecorder fallback for browsers without AudioWorklet support
- Legacy `/ws/voice` base64 path preserved for backward compatibility

## Phase 6 — Polish & Hardening

- Full regression suite: 348 tests passing, 65% coverage
- Created `ARCHITECTURE.md` — production reference for all subsystems
- Created `SMOKE_TEST.md` — 10-section manual verification checklist
- Hardened `/api/health` — no model names, paths, VRAM, or secrets exposed
- Added `/api/debug/metrics` — dev-only, scoped as `process-local`
- Verified no external URLs in `src/` or `frontend/` (automated regression tests)
- Verified `HF_HUB_OFFLINE=1` enforcement via `src/isolation.py`
- Feature flags: `enable_binary_audio`, `enable_audioworklet`, `enable_vram_unload`, etc.
- Safe shutdown sequence with isolated try/except per component

## Branding — VoxDesk Identity

- Renamed project from internal codename to **VoxDesk**
- Created **Voxly** as default AI personality (professional, brand-consistent)
- Personality system: users create custom YAML profiles in `config/personalities/`
- Cleaned all personal/intimate content from codebase
- Translated user-facing strings to English
- Updated all logger namespaces to `voxdesk.*`
- Renamed CLI entry point to `voxdesk`
- Professional README with architecture diagram, quick start, privacy contract

## Pre-Commit Audit

- Zero API keys, tokens, or secrets in codebase
- Zero personal file paths or email addresses
- Zero external telemetry or analytics code
- Zero `.env` files or hardcoded credentials
- Zero model weights or binary assets
- All external URLs verified: only `ollama.com` and `espeak-ng` (setup links)
- `.gitignore` covers Python cache, IDE, secrets, models, audio, coverage, containers
