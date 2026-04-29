# VoxDesk — Dependency Compatibility Matrix

> Sprint 5.3 donanım doğrulaması tamamlanmış bağımlılık tablosu.
> RTX 5080 = Blackwell mimarisi (SM 12.0, compute capability 12.0).
> Son güncelleme: 2026-04-29

---

## Runtime Dependencies

| Package | Required | Installed | CUDA? | Status | Notes |
|:--------|:---------|:----------|:------|:-------|:------|
| Python | 3.12.x | 3.12.10 | — | ✅ | |
| NVIDIA Driver | ≥570 | Güncel | — | ✅ | Blackwell destekli |
| CUDA Toolkit | 12.8 | 12.8.61 | ✅ | ✅ | SM 12.0 (Blackwell) |
| PyTorch | ≥2.7 | 2.11.0+cu128 | ✅ | ✅ | |
| torchaudio | matching | eşleşmiş | ✅ | ✅ | Kokoro TTS backend |
| CTranslate2 | latest | 4.7.1 | ✅ | ✅ | faster-whisper backend |
| faster-whisper | ≥1.1 | güncel | ✅ | ✅ | large-v3-turbo model |
| kokoro | latest | güncel | ✅ | ✅ | TTS engine |
| dxcam | ≥0.3 | güncel | — | ✅ | Windows screen capture |
| llama-cpp-python | latest | 0.3.21 | ✅ | ✅ | CUDA 12.8, SM 120 build |
| transformers | ≥4.40 | güncel | — | ✅ | MarianMT backend |
| sentencepiece | ≥0.2 | güncel | — | ✅ | MarianMT tokenizer |
| sacremoses | ≥2.1 | güncel | — | ✅ | MarianMT tokenizer util |
| espeak-ng | 1.52.0 | 1.52.0 | — | ✅ | System MSI — Kokoro phonemizer |

## Model Files

| Model | Quant | Size | Path | Status |
|:------|:------|:-----|:-----|:-------|
| MiniCPM-V 4.5 Official | Q6_K | 6.26 GB | `models/minicpm-v4.5-official/model-q6_k.gguf` | ✅ |
| MiniCPM-V 4.5 mmproj | F16 | 1.02 GB | `models/minicpm-v4.5-official/mmproj-f16.gguf` | ✅ |
| MiniCPM-V 4.5 Abliterated | Q6_K | — | `models/minicpm-v4.5-abliterated/` | ⏳ Onay bekleniyor |
| Qwen2.5-VL-7B-Instruct | Q8_0 | 7.72 GB | `models/Qwen2.5-VL-7B/Qwen_Qwen2.5-VL-7B-Instruct-Q8_0.gguf` | ✅ |
| Qwen2.5-VL-7B mmproj | F16 | 1.29 GB | `models/Qwen2.5-VL-7B/mmproj-Qwen_Qwen2.5-VL-7B-Instruct-f16.gguf` | ✅ |
| Qwen3-VL-8B-Instruct | Q8_0 | ~8.5 GB | `models/qwen3-vl-8b-instruct/` | ⏳ İndirilmedi |
| Qwen3-VL-8B mmproj | F16 | ~1.3 GB | `models/qwen3-vl-8b-instruct/` | ⏳ İndirilmedi |
| MarianMT opus-mt-tr-en | float16 | ~300 MB | `models/opus-mt-tr-en/` | ✅ |
| Whisper large-v3-turbo | CTranslate2 FP16 | ~1.5 GB | `models/whisper-large-v3-turbo/` | ✅ |

## VRAM Budget (RTX 5080 — 16 GB)

| Component | Estimated VRAM | Measured | Idle Unload | Notes |
|:----------|:---------------|:---------|:------------|:------|
| LLM (Q6_K, full offload) | ~7 GB | — | ❌ Always warm | n_gpu_layers=-1 |
| mmproj (F16) | ~1.1 GB | — | ❌ With LLM | Vision encoder |
| STT (large-v3-turbo) | ~3 GB | — | ✅ 3 min | CTranslate2 |
| TTS (Kokoro) | ~2 GB | — | ✅ 3 min | |
| Translator (MarianMT) | ~600 MB | **146 MB** | ✅ 3 min | PyTorch float16 |
| **Active total** | **~12.1 GB** | | | 76% of 16 GB |
| **Idle total** | **~7 GB** | | | 44% — LLM only |

## Verified Smoke Commands

```powershell
# Python
python --version  # 3.12.10

# CUDA
python -c "import torch; print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')"
# CUDA: True, GPU: NVIDIA GeForce RTX 5080

# Compute capability
python -c "import torch; print(torch.cuda.get_device_capability(0))"
# (12, 0)

# llama-cpp-python
python -c "import llama_cpp; print(llama_cpp.__version__)"
# 0.3.21

# LLM inference
python -c "from llama_cpp import Llama; m=Llama(model_path='models/minicpm-v4.5-official/model-q6_k.gguf',n_gpu_layers=-1,n_ctx=2048,verbose=False); r=m.create_chat_completion(messages=[{'role':'user','content':'Hello'}],max_tokens=16); print(r['choices'][0]['message']['content'])"

# Full test suite
python -m pytest -q --no-header
# 568 passed, 1 skipped
```
