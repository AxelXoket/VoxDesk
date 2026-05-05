<p align="center">
  <h1 align="center">VoxDesk</h1>
  <p align="center">
    <strong>Local-only AI desktop assistant with real-time screen analysis and voice interaction</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/version-0.7.2-orange?style=flat-square" alt="Version">
    <img src="https://img.shields.io/badge/privacy-100%25_local-brightgreen?style=flat-square" alt="Privacy">
    <img src="https://img.shields.io/badge/tests-764_passed-success?style=flat-square" alt="Tests">
    <img src="https://img.shields.io/badge/CUDA-12.8-76B900?style=flat-square&logo=nvidia&logoColor=white" alt="CUDA">
  </p>
</p>

---

VoxDesk is a privacy-first AI assistant that runs **entirely on your machine**. It watches your screen, listens to your voice, and responds with intelligent analysis — all without sending a single byte to the cloud.

## Features

- **Real-Time Screen Analysis** — Continuously captures your screen and provides intelligent context-aware answers about what you're working on
- **Voice Chat** — Speak naturally and get spoken responses via local STT (Whisper) and TTS (Kokoro)
- **100% Local & Private** — No cloud APIs, no telemetry, no CDN assets. Your data never leaves your machine
- **Vision LLM** — Gemma 4 E4B via local llama-server sidecar (OpenAI-compatible local API, not cloud) with multimodal projector (mmproj)
- **Model Agnostic** — Any GGUF model works — just drop the file and update config
- **Binary Audio Protocol** — High-performance PCM audio transfer over WebSocket with AudioWorklet support
- **Glassmorphism UI** — Premium dark-themed interface with smooth animations and responsive design
- **Modular Architecture** — Plugin-ready module registry with dependency injection and fail-fast config validation
- **VRAM Management** — Intelligent model lifecycle with idle unloading, ref-count guards, and state machine transitions

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   Frontend (Browser)                     │
│                                                          │
│   ┌──────────┐  ┌──────────┐  ┌───────────────────┐     │
│   │  Chat UI │  │ Settings │  │ AudioWorklet       │     │
│   └────┬─────┘  └────┬─────┘  │ Capture            │     │
│        │              │        └─────────┬─────────┘     │
│        │              │                  │               │
│        ▼              ▼                  ▼               │
│   WebSocket       REST API       Binary WebSocket        │
│   /ws/chat        /api/*         /ws/voice/v2            │
└────────┬──────────────┬──────────────────┬───────────────┘
         │              │                  │
┌────────▼──────────────▼──────────────────▼───────────────┐
│                  FastAPI + Uvicorn                        │
│                                                          │
│  ┌─────────┐ ┌─────────┐ ┌──────────────────┐           │
│  │   STT   │ │   TTS   │ │   Screen DXCam   │           │
│  │ Whisper │ │  Kokoro │ └──────────────────┘           │
│  └─────────┘ └─────────┘                                │
│                                                          │
│    LocalLlamaServerProvider (httpx → localhost only)      │
│              │                                           │
│              ▼                                           │
│    ┌──────────────────────────────────────┐              │
│    │  llama-server sidecar (subprocess)   │              │
│    │  Gemma 4 E4B + mmproj (libmtmd)     │              │
│    │  OpenAI-compatible /v1/chat/complete │              │
│    │  http://127.0.0.1:8081 only         │              │
│    └──────────────────────────────────────┘              │
│                                                          │
│              VRAM Manager + Model State Machine           │
│              Module Registry (DI) + Protocols             │
│              14 Pydantic Config Models (extra='forbid')   │
└──────────────────────────────────────────────────────────┘
                      127.0.0.1 only
```

## Quick Start

### Prerequisites

- **Python 3.12+** (3.12.10 recommended)
- **NVIDIA GPU** with CUDA support (RTX 5080 / Blackwell tested)
- **CUDA Toolkit 12.8** — [Download](https://developer.nvidia.com/cuda-12-8-0-download-archive)
- **espeak-ng** — Required by Kokoro TTS ([download](https://github.com/espeak-ng/espeak-ng/releases))

### Installation

```powershell
# Clone the repository
git clone https://github.com/AxelXoket/VoxDesk.git
cd VoxDesk

# Create virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install PyTorch with CUDA 12.8 support (MUST be done separately)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install dependencies
pip install -r requirements.txt

# Build llama-cpp-python with CUDA (required for fallback in-process provider)
$env:CMAKE_ARGS = "-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=120"
$env:CUDA_PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
pip install llama-cpp-python --no-cache-dir --force-reinstall
```

> **Why is PyTorch not in `requirements.txt`?**
> `pip install torch` can silently install a CPU-only build. RTX 5080 (Blackwell) requires the CUDA 12.8 wheel index. Install it explicitly first.

### llama-server Setup (Primary LLM Provider)

VoxDesk uses a **local llama-server sidecar** for LLM inference. You need a `llama-server.exe` binary:

```powershell
# Option A: Build from llama.cpp source
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp && cmake -B build -DGGML_CUDA=ON && cmake --build build --config Release
# Binary at: build/bin/Release/llama-server.exe

# Option B: Docker Desktop (dev shortcut)
# If Docker Desktop with GPU support is installed, you may already have:
# C:/Users/<you>/.docker/bin/inference/llama-server.exe
```

Set the path in `config/default.yaml`:
```yaml
local_llama_server:
  executable_path: "path/to/llama-server.exe"
```

> **"OpenAI-compatible" means local API format only** — VoxDesk uses the OpenAI JSON schema
> (`/v1/chat/completions`) to communicate with the local llama-server on `127.0.0.1`.
> **No data is sent to OpenAI or any cloud service.** This is strictly a local protocol.

### Model Setup

Download GGUF model files and place them under `models/`:

```
models/
  gemma-4-E4B-uncensored/             # Primary vision model (Gemma4 sidecar)
    Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf   # ~5.5 GB
    mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf  # mmproj (vision projector)
  whisper-large-v3-turbo/             # STT model (CTranslate2 format)
  opus-mt-tr-en/                      # MarianMT TR→EN translator (optional)
```

**Legacy / Fallback models** (for in-process `llama-cpp-python` provider):
```
models/
  Qwen2.5-VL-7B/                      # Fallback vision model (in-process)
    Qwen_Qwen2.5-VL-7B-Instruct-Q8_0.gguf
    mmproj-Qwen_Qwen2.5-VL-7B-Instruct-f16.gguf
```

> The primary provider is `local-llama-server` (Gemma4 sidecar). The fallback `llama-cpp` provider loads models in-process and is available for models with llama-cpp-python handler support.

### Running

```powershell
python run.py
```

Then open **http://127.0.0.1:8765** in your browser.

## LLM Providers

### Primary: `local-llama-server` (Gemma4 Sidecar)

VoxDesk runs a **local llama-server subprocess** (sidecar) for LLM inference:

- Model: Gemma 4 E4B (GGUF) + multimodal projector (mmproj via libmtmd)
- Protocol: OpenAI-compatible `/v1/chat/completions` — **local API format only, not OpenAI cloud**
- Transport: `httpx` → `http://127.0.0.1:8081` (localhost only, remote URLs rejected)
- Vision: `image_url` with `data:image/jpeg;base64,...` payload (never logged)
- Lifecycle: App-managed — auto-start, health-check, graceful shutdown
- Handler blocker: `Gemma4ChatHandler` is **not needed** — sidecar uses libmtmd natively

### Fallback: `llama-cpp` (In-Process)

`LlamaCppProvider` loads models in-process via llama-cpp-python. Handler auto-resolution:

| Pattern Keywords | Handler | Status |
|:---|:---|:---:|
| `qwen2.5-vl`, `qwen25vl`, `qwen` | `Qwen25VLChatHandler` | ✅ Available |
| `minicpm` | `MiniCPMv26ChatHandler` | ✅ Available |
| `llava` | `Llava16ChatHandler` | ✅ Available |
| `gemma-4`, `gemma4`, `e4b` | `Gemma4ChatHandler` | ⏳ Not in llama-cpp-python yet |

> **Note**: Gemma4 vision is fully supported via sidecar — the missing `Gemma4ChatHandler` in llama-cpp-python is no longer a blocker.

### EXE Packaging Plan

Future Windows EXE distribution:
```
VoxDesk/
  VoxDesk.exe                  # Main application
  llama-server.exe             # Bundled sidecar
  models/                      # User-provided GGUF models
    gemma-4-E4B-uncensored/
      *.gguf
```
Models are **not embedded** in the executable — shipped separately or downloaded via installer.

## VRAM Budget (RTX 5080 — 16 GB)

| Component | Est. VRAM | Idle Unload | Notes |
|:---|:---:|:---:|:---|
| LLM (Q6_K, full offload) | ~7 GB | ❌ Always warm | `n_gpu_layers=-1` |
| mmproj (F16) | ~1.1 GB | ❌ With LLM | Vision encoder |
| STT (large-v3-turbo) | ~3 GB | ✅ 3 min | CTranslate2 |
| TTS (Kokoro) | ~2 GB | ✅ 3 min | |
| Translator (MarianMT) | ~0.15 GB | ✅ 3 min | PyTorch float16 |
| **Active total** | **~13.3 GB** | | 83% of 16 GB |
| **Idle total (LLM only)** | **~8.1 GB** | | 51% of 16 GB |

### Model State Machine

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

**5 Unload Guards**: ref_count > 0, keep_warm, min_loaded_seconds, cooldown, already_unloaded.

## Privacy Contract

VoxDesk enforces strict local-only operation:

| Guarantee | Enforcement |
|:---|:---|
| No cloud inference | All models run from local GGUF/CT2 files |
| No telemetry | Zero usage data sent externally |
| No CDN assets | No external scripts, fonts, or stylesheets |
| No runtime downloads | Missing model = startup failure, no auto-download |
| Localhost only | Server binds to `127.0.0.1` |
| Offline env vars | `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` enforced |

These guarantees are backed by **85+ automated regression tests** that scan for external URLs, cloud API calls, CDN references, and telemetry code on every test run.

## API Endpoints

| Endpoint | Type | Description |
|:---|:---|:---|
| `GET /` | HTTP | Frontend (index.html) |
| `GET /api/health` | HTTP | Minimal health check (safe to expose) |
| `GET /api/status` | HTTP | Runtime snapshot — models, features, connections |
| `GET /api/debug/metrics` | HTTP | Full metrics (gated by feature flag, returns 403 when disabled) |
| `GET /api/history` | HTTP | Chat history export |
| `GET/POST /api/settings` | HTTP | Runtime config viewer/editor |
| `/ws/chat` | WebSocket | Text chat with streaming LLM response |
| `/ws/screen` | WebSocket | Live screen preview stream |
| `/ws/voice` | WebSocket | Legacy voice (base64 JSON audio) |
| `/ws/voice/v2` | WebSocket | Binary PCM voice (handshake → raw frames → STT → LLM → TTS) |

## Personality System

VoxDesk ships with **Voxly**, a bilingual AI companion. Create your own by adding a YAML file to `config/personalities/`:

```yaml
# config/personalities/my_assistant.yaml
name: "MyAssistant"
language: "both"          # "en", "tr", or "both" (auto-detect)
voice: "af_heart"         # Kokoro voice ID
tone: "professional"
greeting: "Hello! How can I help?"

system_prompt: |
  You are MyAssistant — a helpful AI desktop companion.
  Rules:
  - Be helpful and concise
  - Analyze the user's screen when asked
  - Respond in the user's language

stt_context: |
  MyAssistant, Python, JavaScript, React

screen_analysis_prompt: |
  Describe only what is visible. Never invent content.

response_format: |
  Voice mode: Natural speech. Text mode: Markdown allowed.
```

Then set in `config/default.yaml`: `personality: "my_assistant"`

## Testing

```powershell
# Full test suite (764+ tests)
python -m pytest

# With coverage report
python -m pytest --cov=src --cov-fail-under=55

# Quick run (unit + regression, no coverage)
python run_tests.py --quick

# Unit tests only
python run_tests.py --unit

# Regression tests only
python run_tests.py --regress

# Benchmarks (report-only)
python run_tests.py --bench
```

| Category | Count (approx.) | Purpose |
|:---|:---:|:---|
| Unit | ~180+ | Core logic validation |
| Regression | ~85+ | Privacy, isolation, config mapping, endpoint contracts, prompt safety, audit fixes |
| Handler/Budget | ~40 | Vision handler resolution + budget plumbing |
| Image Metadata | ~24 | CanonicalImageArtifact + ImageMetadata |
| Quality Parity | ~16 | Image quality pipeline |
| Benchmark | 4 | Performance baselines |
| GPU | 1 | CUDA smoke test (auto-skipped if no GPU) |

> Test counts are approximate and grow with each sprint. Run `pytest --co -q` for exact count.

**Current coverage: ~65%** — Minimum threshold: 55%

## Project Structure

```
VoxDesk/
├── src/                            # Python backend (21 modules)
│   ├── main.py                     # FastAPI app, lifespan, health/status/metrics endpoints
│   ├── config.py                   # 13 Pydantic config models (all extra='forbid')
│   ├── llm/
│   │   ├── local_server_provider.py # LocalLlamaServerProvider — sidecar HTTP client (primary)
│   │   ├── sidecar.py              # SidecarManager — llama-server subprocess lifecycle
│   │   ├── provider.py             # LlamaCppProvider — in-process GGUF inference (fallback)
│   │   ├── types.py                # ChatMessage, prompt builder
│   │   └── history.py              # Conversation history manager
│   ├── stt.py                      # faster-whisper STT with ManagedModel lifecycle
│   ├── tts.py                      # Kokoro TTS with ManagedModel lifecycle
│   ├── translator.py               # MarianMT TR→EN with ManagedModel lifecycle
│   ├── capture.py                  # DXCam screen capture + dual quality path
│   ├── image_artifact.py           # CanonicalImageArtifact — unified image interface
│   ├── image_metadata.py           # ImageMetadata — source/resolution/hash tracking
│   ├── vram_manager.py             # GPU memory lifecycle + idle unload monitor
│   ├── model_state.py              # ManagedModel state machine (5 unload guards)
│   ├── registry.py                 # Module registry (dependency injection)
│   ├── protocols.py                # 5 engine protocol contracts (structural typing)
│   ├── audio_protocol.py           # Binary PCM protocol v1 codec
│   ├── audio_utils.py              # PCM decode/encode helpers
│   ├── isolation.py                # Network isolation enforcer
│   ├── websocket_manager.py        # WebSocket lifecycle + origin validation
│   ├── metrics.py                  # MetricsCollector — sliding-window percentiles
│   ├── hotkey.py                   # Global keyboard shortcuts
│   ├── tray.py                     # System tray icon
│   └── routes/                     # API route handlers
│       ├── chat.py                 # /ws/chat, /ws/screen, /ws/voice, POST /chat
│       ├── voice_v2.py             # /ws/voice/v2 — binary PCM audio
│       ├── history.py              # GET /api/history
│       └── settings.py             # GET/POST /api/settings
├── frontend/                       # Browser UI (served as static files)
│   ├── index.html                  # Single-page application
│   ├── css/styles.css              # Glassmorphism dark theme
│   └── js/                         # 7 modular JS components
│       ├── app.js                  # Main orchestrator
│       ├── chat.js                 # Chat component
│       ├── websocket.js            # WebSocket manager
│       ├── audio-capture.js        # AudioWorklet + MediaRecorder capture
│       ├── audio-processor.js      # AudioWorklet processor (worklet thread)
│       ├── settings.js             # Settings panel
│       ├── screen-preview.js       # Live screen preview
│       └── dev-hud.js              # Developer HUD overlay
├── models/                         # GGUF/CT2 model files (gitignored)
├── config/
│   ├── default.yaml                # Application configuration (17 sections)
│   └── personalities/
│       └── voxly.yaml              # Default personality profile
├── tests/                          # 764+ tests across 24+ files
├── docs/
│   ├── architecture.md             # Technical reference (469 lines)
│   ├── dependency_matrix.md        # Verified dependency versions + VRAM budget
│   ├── local_smoke_checklist.md    # Manual verification checklist
│   ├── progress.md                 # Development log
│   └── security_privacy_policy.md  # Privacy contract
├── run.py                          # One-click launcher
├── run_tests.py                    # Test runner (--unit, --regress, --bench, --quick)
├── pyproject.toml                  # Project metadata + pytest config
├── requirements.txt                # Runtime + test dependencies
└── LICENSE                         # GPLv3
```

## Configuration

All configuration lives in `config/default.yaml` with **14 strict Pydantic models** (`extra='forbid'` — typos cause startup failure):

```yaml
app:
  host: "127.0.0.1"
  port: 8765

llm:
  provider: "local-llama-server"   # primary: sidecar | fallback: "llama-cpp"
  model_path: "models/gemma-4-E4B-uncensored/...Q8_K_P.gguf"
  mmproj_path: "models/gemma-4-E4B-uncensored/...f16.gguf"
  n_gpu_layers: -1
  n_ctx: 8192

local_llama_server:
  enabled: true
  executable_path: ""             # REQUIRED — set to local llama-server.exe path
  base_url: "http://127.0.0.1:8081"  # localhost only — remote rejected
  port: 8081
  auto_start: true
  jinja: true                     # required for Gemma4

stt:
  engine: "faster-whisper"
  model: "large-v3-turbo"

tts:
  engine: "kokoro"
  voice: "af_heart"

features:
  enable_vram_unload: true
  enable_binary_audio: false
  enable_debug_metrics: false

privacy:
  offline_mode: true
  allow_cloud_providers: false
  allow_cdn_assets: false
```

## Roadmap

- [x] Pure local inference — no cloud APIs, no Ollama dependency
- [x] CUDA 12.8 + RTX 5080 Blackwell support
- [x] **Gemma 4 E4B vision via local llama-server sidecar** (primary provider)
- [x] LocalLlamaServerProvider — localhost-only httpx client
- [x] SidecarManager — subprocess lifecycle (start/health/shutdown)
- [x] Qwen2.5-VL-7B + MiniCPM-V fallback (in-process llama-cpp-python)
- [x] Binary PCM WebSocket protocol
- [x] VRAM idle unload with 5-guard state machine
- [x] Modular personality system (YAML-driven)
- [x] Module registry with dependency injection
- [x] Dual-quality image pipeline (preview/inference)
- [x] 14 strict Pydantic config models
- [x] Screen context privacy enforcement (all 4 routes)
- [ ] Windows EXE packaging with bundled llama-server sidecar
- [ ] Setup Wizard + Model Downloader (SHA256 verified)
- [ ] Multi-monitor support
- [ ] Custom hotkey bindings UI
- [ ] Plugin system for third-party modules
- [ ] Conversation branching and search
- [ ] Additional TTS voice packs

## License

This project is licensed under the GNU General Public License v3.0 — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with privacy in mind — your data stays on your machine, always.</sub>
</p>
