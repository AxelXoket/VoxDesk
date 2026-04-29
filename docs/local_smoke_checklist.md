# VoxDesk — Local Smoke Checklist

> Sprint 5.3 (Part 5b) kurulum sonrası gerçek donanımda doğrulanmış maddeler.
> Bu çalıştırma kodu DEĞİL, manual verification listesidir.

---

## Prerequisite: venv + Dependencies

- [ ] Python 3.12.x virtual environment aktif
- [ ] `pip install -r requirements.txt` başarılı (tüm paketler)
- [ ] `pip install -e .` editable install başarılı
- [ ] NVIDIA driver ≥570 kurulu (`nvidia-smi` çalışıyor)

## 1. Import Smoke

- [ ] `python -c "import torch; print(torch.__version__)"` → 2.11+
- [ ] `python -c "import faster_whisper"` → no error
- [ ] `python -c "import kokoro"` → no error
- [ ] `python -c "import dxcam"` → no error
- [ ] `python -c "from src.config import get_config; get_config()"` → no error

## 2. CUDA Smoke

- [ ] `torch.cuda.is_available()` → True
- [ ] `torch.cuda.get_device_name(0)` → RTX 5080
- [x] `torch.cuda.get_device_capability(0)` → (12, 0) [Blackwell SM 12.0]
- [ ] Basic tensor op: `torch.randn(10, device='cuda')` → no error

## 3. Model Load Smoke

- [ ] faster-whisper model load (large-v3-turbo veya small) → no error, model files in `models/`
- [ ] Kokoro TTS model load → no error
- [ ] STT: 1 saniyelik sessizlik transcribe → empty result veya short text
- [x] llama-cpp-python model load (MiniCPM-V 4.5 Q6_K) → inference OK
- [x] mmproj load (F16) → vision projector mevcut

## 3b. Vision Handler Smoke

- [ ] Handler resolution: model filename → correct handler class (Qwen25VL, MiniCPM, etc.)
- [ ] Explicit `chat_handler: qwen25vl` override → correct handler used
- [ ] Missing handler (Qwen3, Gemma4) → clear warning logged, no silent fallback
- [ ] Inference image quality → 1920px max, Q92 (not preview 1280/Q85)
- [ ] CanonicalImageArtifact → image metadata (source, resolution, hash) logged correctly
- [ ] No base64/raw image data in conversation history

## 4. Screen Capture Smoke

- [ ] `dxcam.create()` → camera object
- [ ] `.grab()` → numpy array with valid shape
- [ ] `ScreenCapture.start()` → ring buffer filling

## 5. Backend Boot Smoke

- [ ] `python run.py` → server starts on 127.0.0.1:8765
- [ ] `curl http://127.0.0.1:8765/api/health` → `{"status":"ok"}`
- [ ] `curl http://127.0.0.1:8765/api/status` → JSON with models/features/capture

## 6. Frontend Smoke

- [ ] Open `http://127.0.0.1:8765` in browser → UI loads
- [ ] Status bar shows model name → `Aktif — modelname`
- [ ] DEV HUD visible → shows metrics
- [ ] Screen preview shows captured frame

## 7. Voice Smoke

- [ ] Click voice mode → WS connected
- [ ] Mic button press → AudioCapture starts (worklet or mediarecorder)
- [ ] Mic release → audio_end sent, STT result appears
- [ ] LLM response appears in chat
- [ ] TTS audio plays
- [ ] Disconnect voice → AudioCapture stops, mic released

## 8. Error Visibility Smoke

- [ ] Simulate LLM error → DEV HUD shows last_error
- [ ] Simulate STT error → voice_error message in chat
- [ ] Close voice WS → cleanup handler fires, mic stops

## 9. Security Smoke

- [ ] Server binds 127.0.0.1 (not 0.0.0.0)
- [ ] `/api/debug/metrics` returns 403 (default disabled)
- [ ] `/api/status` shows no paths, secrets, or env vars
- [ ] No external URLs in browser network tab during normal use

---

## Pass Criteria

ALL items checked → Sprint 5.3 ready.
ANY unchecked → document issue, assess impact, fix or accept known limitation before proceeding.

---

## Known Limitations (Sprint 5.3)

- `Qwen3VLChatHandler` not available in `llama-cpp-python` v0.3.21 (requires JamePeng fork or upstream update).
- `Gemma4ChatHandler` / `Gemma3ChatHandler` not available in v0.3.21.
- POST `/chat` still uses ring buffer quality (1280/Q85) — low priority.
