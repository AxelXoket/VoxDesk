<p align="center">
  <h1 align="center">VoxDesk</h1>
  <p align="center">
    <strong>Local-only AI desktop assistant with real-time screen analysis and voice interaction</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/license-GPL--3.0-blue?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/version-0.5.0-orange?style=flat-square" alt="Version">
    <img src="https://img.shields.io/badge/privacy-100%25_local-brightgreen?style=flat-square" alt="Privacy">
    <img src="https://img.shields.io/badge/tests-484_passed-success?style=flat-square" alt="Tests">
    <img src="https://img.shields.io/badge/CUDA-12.8-76B900?style=flat-square&logo=nvidia&logoColor=white" alt="CUDA">
  </p>
</p>

---

VoxDesk is a privacy-first AI assistant that runs **entirely on your machine**. It watches your screen, listens to your voice, and responds with intelligent analysis — all without sending a single byte to the cloud.

## Features

- **Real-Time Screen Analysis** — Continuously captures your screen and provides intelligent context-aware answers about what you're working on
- **Voice Chat** — Speak naturally and get spoken responses via local STT (Whisper) and TTS (Kokoro)
- **100% Local & Private** — No cloud APIs, no telemetry, no CDN assets. Your data never leaves your machine
- **Vision LLM** — MiniCPM-V 4.5 with 3D-Resampler for single image, multi-image, and high-FPS video understanding
- **Model Agnostic** — Any GGUF model works — just drop the file and update config
- **Binary Audio Protocol** — High-performance PCM audio transfer over WebSocket with AudioWorklet support
- **Glassmorphism UI** — Premium dark-themed interface with smooth animations and responsive design
- **Modular Architecture** — Plugin-ready module registry with dependency injection and fail-fast config validation
- **VRAM Management** — Intelligent model lifecycle with idle unloading, ref-count guards, and state machine transitions

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Browser)                    │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────────┐ │
│  │ Chat UI  │  │ Settings │  │ AudioWorklet Capture   │ │
│  └────┬─────┘  └────┬─────┘  └───────────┬────────────┘ │
│       │              │                    │              │
├───────┼──────────────┼────────────────────┼──────────────┤
│       ▼              ▼                    ▼              │
│  WebSocket       REST API          Binary WebSocket      │
│  /ws/chat        /api/*            /ws/voice/v2          │
├─────────────────────────────────────────────────────────┤
│                   FastAPI + Uvicorn                      │
│  ┌─────────┐  ┌─────────┐  ┌──────────┐ ┌───────────┐  │
│  │   STT   │  │   TTS   │  │   LLM    │ │  Screen   │  │
│  │ Whisper │  │ Kokoro  │  │llama-cpp  │ │  DXCam    │  │
│  └─────────┘  └─────────┘  │+ mmproj  │ └───────────┘  │
│                             └──────────┘                │
│                 VRAM Manager                             │
│              Module Registry (DI)                        │
└─────────────────────────────────────────────────────────┘
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

# Install PyTorch with CUDA 12.8 support
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128

# Install dependencies
pip install -r requirements.txt

# Build llama-cpp-python with CUDA (required for GPU inference)
$env:CMAKE_ARGS = "-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=120"
$env:CUDA_PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
pip install llama-cpp-python --no-cache-dir --force-reinstall
```

### Model Setup

Download GGUF model files and place them under `models/`:

```
models/
  Qwen2.5-VL-7B/
    Qwen_Qwen2.5-VL-7B-Instruct-Q8_0.gguf    # Primary LLM
    mmproj-Qwen_Qwen2.5-VL-7B-Instruct-f16.gguf  # Vision projector
  whisper-large-v3-turbo/                      # STT model (CTranslate2)
  opus-mt-tr-en/                               # TR→EN translator
```

> Any GGUF-compatible model can be used — update `config/default.yaml` accordingly.

### Running

```powershell
python run.py
```

Then open **http://127.0.0.1:8765** in your browser.

## Privacy Contract

VoxDesk enforces strict local-only operation:

| Guarantee | Enforcement |
|:---|:---|
| No cloud inference | All models run from local GGUF files via llama-cpp-python |
| No telemetry | Zero usage data sent externally |
| No CDN assets | No external scripts, fonts, or stylesheets |
| No runtime downloads | Missing model = startup failure, no auto-download |
| Localhost only | Server binds to `127.0.0.1` |
| Offline env vars | `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` enforced |

These guarantees are backed by automated regression tests that scan for external URLs, cloud API calls, and telemetry code on every test run.

## Personality System

VoxDesk ships with **Voxly**, a professional AI personality. You can create your own by adding a YAML file to `config/personalities/`:

```yaml
# config/personalities/my_assistant.yaml
name: "MyAssistant"
language: "both"          # "en", "tr", or "both" (auto-detect)
voice: "af_heart"         # Kokoro voice ID
tone: "professional"
greeting: "Hello! How can I help?"

system_prompt: |
  You are MyAssistant — a helpful AI desktop companion.
  Your rules:
  - Be helpful and concise
  - Analyze the user's screen when asked
  - Respond in the user's language
```

Then set it in `config/default.yaml`:

```yaml
personality: "my_assistant"
```

## Testing

```powershell
# Full test suite (484 tests)
python -m pytest

# With coverage report
python -m pytest --cov=src --cov-fail-under=55

# Quick run (skip benchmarks)
python -m pytest --no-benchmarks

# Regression tests only (83 tests)
python -m pytest -m regression
```

| Category | Count | Purpose |
|:---|:---:|:---|
| Unit | ~175 | Core logic validation |
| Regression | ~83 | Privacy, config mapping, endpoint contracts, prompt safety, audit fixes |
| Benchmark | 4 | Performance baselines |
| GPU | 1 | CUDA smoke test (auto-skipped if no GPU) |

**Current coverage: ~65%** · Minimum threshold: 55%

## Project Structure

```
VoxDesk/
├── src/                        # Python backend
│   ├── main.py                 # FastAPI app + lifespan
│   ├── config.py               # Pydantic config (extra='forbid')
│   ├── llm/
│   │   ├── provider.py         # LlamaCppProvider — GGUF inference
│   │   ├── types.py            # ChatMessage, prompts
│   │   └── history.py          # Conversation history
│   ├── stt.py                  # faster-whisper STT
│   ├── tts.py                  # Kokoro TTS
│   ├── translator.py           # MarianMT TR→EN translator
│   ├── capture.py              # DXCam screen capture
│   ├── vram_manager.py         # GPU memory lifecycle
│   ├── model_state.py          # ManagedModel state machine
│   ├── registry.py             # Module registry (DI)
│   ├── audio_protocol.py       # Binary PCM protocol v1
│   ├── audio_utils.py          # PCM decode/encode helpers
│   ├── isolation.py            # Network isolation enforcer
│   ├── websocket_manager.py    # WebSocket lifecycle manager
│   ├── hotkey.py               # Global keyboard shortcuts
│   ├── tray.py                 # System tray icon
│   └── routes/                 # API route handlers
│       ├── chat.py             # /ws/chat, /ws/screen, /ws/voice
│       ├── voice_v2.py         # /ws/voice/v2 binary audio
│       ├── history.py          # Chat history export
│       └── settings.py         # Runtime settings API
├── frontend/                   # Browser UI
│   ├── index.html              # Single-page app
│   ├── css/styles.css          # Glassmorphism theme
│   └── js/                     # Modular JS components
│       ├── app.js              # Main orchestrator
│       ├── chat.js             # Chat component
│       ├── websocket.js        # WebSocket manager
│       ├── audio-capture.js    # AudioWorklet client
│       ├── audio-processor.js  # AudioWorklet processor
│       ├── settings.js         # Settings panel
│       └── screen-preview.js   # Live screen preview
├── models/                     # GGUF model files (not in git)
│   └── minicpm-v4.5-official/  # Primary model
├── config/
│   ├── default.yaml            # Application configuration
│   └── personalities/          # AI personality profiles
│       └── voxly.yaml          # Default personality
├── tests/                      # 484+ tests
├── docs/                       # Documentation
│   ├── architecture.md         # Technical reference
│   ├── dependency_matrix.md    # Verified dependency versions
│   ├── local_smoke_checklist.md # Manual verification checklist
│   └── PROGRESS.md             # Development log
├── run.py                      # One-click launcher
└── pyproject.toml              # Project metadata + pytest config
```

## Configuration

All configuration lives in `config/default.yaml`:

```yaml
app:
  name: "VoxDesk"
  host: "127.0.0.1"
  port: 8765

llm:
  provider: "llama-cpp"
  model_path: "models/Qwen2.5-VL-7B/Qwen_Qwen2.5-VL-7B-Instruct-Q8_0.gguf"
  mmproj_path: "models/Qwen2.5-VL-7B/mmproj-Qwen_Qwen2.5-VL-7B-Instruct-f16.gguf"
  n_gpu_layers: -1          # -1 = full GPU offload
  n_ctx: 8192
  temperature: 0.4
  max_tokens: 512

stt:
  engine: "faster-whisper"
  model: "large-v3-turbo"
  device: "cuda"

tts:
  engine: "kokoro"
  voice: "af_heart"
  speed: 1.0

features:
  enable_debug_metrics: false
  enable_vram_unload: false
  enable_binary_audio: false
```

> **Note**: All config models use `extra='forbid'` — typos and unknown fields cause immediate startup failure, preventing silent misconfiguration.

## Roadmap

- [x] Pure local inference (llama-cpp-python, no Ollama)
- [x] CUDA 12.8 + RTX 5080 Blackwell support
- [x] MiniCPM-V 4.5 multimodal vision
- [ ] 3D-Resampler temporal video analysis
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
