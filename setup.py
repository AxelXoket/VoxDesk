"""
VoxDesk — First-Time Setup Script
Downloads models and installs dependencies.
This script REQUIRES INTERNET — run it once only.
After setup, internet access can be disabled.
"""

import os
import sys
import subprocess
import shutil


def banner():
    print()
    print("  🌐 VoxDesk — First-Time Setup")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ⚠️  This script requires internet!")
    print("  ⚠️  After setup, internet can be disabled.")
    print()


def check_ollama():
    """Check that Ollama is installed."""
    print("[1/5] Checking Ollama...")
    result = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  ✅ Ollama found: {result.stdout.strip()}")
    else:
        print("  ❌ Ollama not found!")
        print("  📥 Download from https://ollama.com")
        sys.exit(1)


def pull_ollama_models():
    """Download Ollama models."""
    print("[2/5] Downloading Ollama models...")
    models = [
        "huihui-ai/minicpm-v4.5-abliterated",
    ]
    for model in models:
        print(f"  📥 Downloading: {model}")
        subprocess.run(["ollama", "pull", model], check=False)
    print("  ✅ Models ready")


def download_whisper_model():
    """Pre-download faster-whisper model."""
    print("[3/5] Downloading Whisper STT model...")
    try:
        from faster_whisper import WhisperModel
        # First run downloads and caches the model
        _model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
        del _model
        print("  ✅ Whisper model ready")
    except Exception as e:
        print(f"  ⚠️  Whisper model download error: {e}")
        print("  ℹ️  Will be downloaded automatically on first run")


def download_kokoro_model():
    """Pre-download Kokoro TTS model."""
    print("[4/5] Downloading Kokoro TTS model...")
    try:
        from kokoro import KPipeline
        _pipeline = KPipeline(lang_code='a')
        _pipeline("test", voice="af_heart")
        del _pipeline
        print("  ✅ Kokoro TTS model ready")
    except Exception as e:
        print(f"  ⚠️  Kokoro model download error: {e}")
        print("  ℹ️  Will be downloaded automatically on first run")


def check_espeak():
    """Check that espeak-ng is installed."""
    print("[5/5] Checking espeak-ng...")
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        print("  ✅ espeak-ng found")
    else:
        print("  ⚠️  espeak-ng not found!")
        print("  📥 Windows: https://github.com/espeak-ng/espeak-ng/releases")
        print("  📥 Required for Kokoro TTS")


def main():
    banner()

    check_ollama()
    pull_ollama_models()
    download_whisper_model()
    download_kokoro_model()
    check_espeak()

    print()
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  ✅ Setup complete!")
    print("  🔒 You can now disable internet access.")
    print("  🚀 To start: python run.py")
    print("  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print()


if __name__ == "__main__":
    main()
