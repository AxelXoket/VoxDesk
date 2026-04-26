<p align="center">
  <h1 align="center">VoxDesk</h1>
  <p align="center">
    <strong>Local-only AI desktop assistant with real-time screen analysis and voice interaction</strong>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.12+-blue?style=flat-square&logo=python" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
    <img src="https://img.shields.io/badge/status-v0.1.0-orange?style=flat-square" alt="Status">
    <img src="https://img.shields.io/badge/privacy-100%25_local-brightgreen?style=flat-square&logo=shield" alt="Privacy">
  </p>
</p>

---

VoxDesk is a privacy-first AI assistant that runs **entirely on your machine**. It watches your screen, listens to your voice, and responds with intelligent analysis — all without sending a single byte to the cloud.

## Features

- **Real-Time Screen Analysis** — Continuously captures your screen and provides intelligent context-aware answers about what you're working on
- **Voice Chat** — Speak naturally and get spoken responses via local STT (Whisper) and TTS (Kokoro)
- **100% Local & Private** — No cloud APIs, no telemetry, no CDN assets. Your data never leaves your machine
- **Binary Audio Protocol** — High-performance PCM audio transfer over WebSocket with AudioWorklet support
- **Vision LLM** — Uses multimodal models (MiniCPM-V) to understand screenshots, code, documents, and more
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
│  ┌─────────┐  ┌─────────┐  ┌─────┐  ┌───────────────┐  │
│  │   STT   │  │   TTS   │  │ LLM │  │ Screen Capture│  │
│  │ Whisper │  │ Kokoro  │  │Ollama│  │    DXCam      │  │
│  └─────────┘  └─────────┘  └─────┘  └───────────────┘  │
│                 VRAM Manager                             │
│              Module Registry (DI)                        │
└─────────────────────────────────────────────────────────┘
                    127.0.0.1 only
```

## Quick Start

### Prerequisites

- **Python 3.12+** (3.12.10 recommended)
- **[Ollama](https://ollama.com)** — Local LLM inference
- **NVIDIA GPU** (recommended) — For Whisper STT acceleration
- **espeak-ng** — Required by Kokoro TTS ([download](https://github.com/espeak-ng/espeak-ng/releases))

### Installation

```bash
# Clone the repository
git clone https://github.com/AxelXoket/VoxDesk.git
cd VoxDesk

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# First-time setup (downloads models — requires internet)
python setup.py

# After setup, internet can be disabled
```

### Running

```bash
python run.py
```

Then open **http://127.0.0.1:8765** in your browser.

## Privacy Contract

VoxDesk enforces strict local-only operation:

| Guarantee | Enforcement |
|:---|:---|
| No cloud inference | All models run from local files |
| No telemetry | Zero usage data sent externally |
| No CDN assets | No external scripts, fonts, or stylesheets |
| No runtime downloads | Missing model = startup failure |
| Localhost only | Server binds to `127.0.0.1` |

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

```bash
# Full test suite (348 tests)
python -m pytest

# With coverage report
python -m pytest --cov=src --cov-fail-under=55

# Quick run (skip benchmarks)
python -m pytest --no-benchmarks

# Regression tests only
python -m pytest -m regression
```

| Category | Count | Purpose |
|:---|:---:|:---|
| Unit | ~300 | Core logic validation |
| Regression | ~30 | Privacy, isolation, leak prevention |
| Benchmark | 4 | Performance baselines |
| GPU | 1 | CUDA smoke test (auto-skipped if no GPU) |

**Current coverage: ~65%** · Minimum threshold: 55%

## Project Structure

```
VoxDesk/
├── src/                        # Python backend
│   ├── main.py                 # FastAPI app + lifespan
│   ├── config.py               # Pydantic config (extra='forbid')
│   ├── llm_client.py           # Ollama vision LLM client
│   ├── stt.py                  # faster-whisper STT
│   ├── tts.py                  # Kokoro TTS
│   ├── capture.py              # DXCam screen capture
│   ├── vram_manager.py         # GPU memory lifecycle
│   ├── model_state.py          # ManagedModel state machine
│   ├── registry.py             # Module registry (DI)
│   ├── audio_protocol.py       # Binary PCM protocol v1
│   ├── isolation.py            # Network isolation enforcer
│   └── routes/                 # API route handlers
│       ├── chat.py             # /ws/chat streaming
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
├── config/
│   ├── default.yaml            # Application configuration
│   └── personalities/          # AI personality profiles
│       └── voxly.yaml          # Default personality
├── tests/                      # 348 tests
├── ARCHITECTURE.md             # Technical reference
├── SMOKE_TEST.md               # Manual verification checklist
├── setup.py                    # First-time model download
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
  model: "huihui-ai/minicpm-v4.5-abliterated"
  temperature: 0.7
  max_tokens: 2048

stt:
  engine: "faster-whisper"
  model: "large-v3-turbo"
  device: "cuda"

tts:
  engine: "kokoro"
  voice: "af_heart"
  speed: 1.0
```

> **Note**: All config models use `extra='forbid'` — typos and unknown fields cause immediate startup failure, preventing silent misconfiguration.

## Roadmap

- [ ] Multi-monitor support
- [ ] Custom hotkey bindings UI
- [ ] Plugin system for third-party modules
- [ ] Conversation branching and search
- [ ] Additional TTS voice packs

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  <sub>Built with privacy in mind — your data stays on your machine, always.</sub>
</p>
