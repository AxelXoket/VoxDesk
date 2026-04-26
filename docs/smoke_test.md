# VoxDesk — Manual Smoke Test Checklist

> Run this checklist before any release or major deployment.
> All items should pass on a fresh checkout with local models pre-installed.

## Prerequisites

- [ ] Python 3.12 environment active
- [ ] `pip install -e .` completed
- [ ] Local models pre-installed (Whisper, Kokoro)
- [ ] No active internet connection required

---

## 1. Test Suite

- [ ] `python -m pytest --cov=src --cov-fail-under=55` — all tests pass
- [ ] Coverage ≥55%
- [ ] `python run_tests.py --regress` — all regression tests pass
- [ ] `python run_tests.py --bench` — benchmark report generated
- [ ] No `RuntimeWarning` about unawaited coroutines

## 2. Server Startup

- [ ] `python -m src.main` — starts without errors
- [ ] Binds to `127.0.0.1:8765` only
- [ ] Console shows "✅ VoxDesk hazır!"
- [ ] Registry shows 4 kinds registered
- [ ] VRAM monitor starts

## 3. Health Endpoints

- [ ] `GET /api/health` — returns `{"status": "ok", ...}`
- [ ] `/api/health` does NOT contain model names, paths, VRAM info
- [ ] `GET /api/debug/metrics` — returns full metrics (dev only)
- [ ] Debug metrics includes `_scope: "process-local"`

## 4. Frontend

- [ ] `http://localhost:8765` — loads frontend
- [ ] No external network requests (check DevTools Network tab)
- [ ] No CDN scripts/fonts/styles loaded
- [ ] No console errors about external resources

## 5. Audio — AudioWorklet Path

- [ ] Click record → mic permission requested
- [ ] Permission granted → AudioWorklet starts
- [ ] `audio_config` handshake sent (check WS frames)
- [ ] Binary PCM frames sent (not base64 JSON)
- [ ] Stop → `audio_end` sent
- [ ] STT result received
- [ ] LLM response received
- [ ] TTS audio received

## 6. Audio — Error States

- [ ] Permission denied → UI shows error, no crash
- [ ] No mic device → UI shows error
- [ ] AudioWorklet addModule failure → falls back to MediaRecorder
- [ ] `processorerror` → falls back to MediaRecorder
- [ ] Disconnect during recording → session cleaned up

## 7. Audio — MediaRecorder Fallback

- [ ] Disable AudioWorklet → MediaRecorder activates
- [ ] Audio sent as base64 JSON (legacy path)
- [ ] Blob size ≤ 64KB per chunk
- [ ] `timeslice=250ms` working

## 8. Audio — Legacy Path

- [ ] `/ws/voice` (original) still accepts base64 JSON
- [ ] Works with `format: "webm"`
- [ ] Works with `format: "pcm"`

## 9. VRAM Lifecycle

- [ ] Model loads on first transcribe
- [ ] `safe_unload()` blocked during active transcribe
- [ ] Idle model unloads after configured timeout
- [ ] GPU-less machine doesn't crash
- [ ] `health()` returns correct state

## 10. Privacy Verification

- [ ] No DNS queries to external domains (check with Wireshark/netstat)
- [ ] No HTTP/HTTPS requests to external domains
- [ ] `HF_HUB_OFFLINE=1` set in environment
- [ ] Model paths are local only
- [ ] No telemetry/analytics sent
- [ ] CORS only allows localhost origins

---

## Sign-off

| Item | Date | Tester | Result |
|:---|:---|:---|:---|
| Test suite | | | |
| Server startup | | | |
| Frontend | | | |
| Audio worklet | | | |
| Audio fallback | | | |
| Privacy | | | |
