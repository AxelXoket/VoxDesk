"""
VoxDesk — LlamaCppProvider
Local GGUF inference via llama-cpp-python.

Runtime Policy:
- No internet access
- No model downloads
- No from_pretrained / hf_hub_download
- Model file missing → FileNotFoundError (degraded mode)
- Sync llama-cpp → async bridge via run_in_executor
"""

from __future__ import annotations

import asyncio
import base64
import time
import logging
from pathlib import Path
from typing import AsyncGenerator

from src.config import LLMConfig, PersonalityConfig, get_config
from src.llm.types import ChatMessage, VISUAL_MEMO_PROMPT
from src.llm.history import ConversationHistory

logger = logging.getLogger("voxdesk.llm.provider")


class LlamaCppProvider:
    """
    llama-cpp-python ile local GGUF inference.

    Lifecycle:
      1. __init__(config) → path validation, lazy import
      2. chat(message, image_bytes) → async inference
      3. chat_stream(message, image_bytes) → async streaming
      4. unload() → release GPU memory

    Design:
      - Sync llama-cpp calls → async bridge (run_in_executor)
      - STT/TTS ile aynı kanıtlanmış pattern
      - History yönetimi ConversationHistory'ye delege edilir
      - Visual memo background task ile üretilir
    """

    def __init__(self, config: LLMConfig) -> None:
        # ── Config ───────────────────────────────────────────
        self._config = config
        self._personality: PersonalityConfig = get_config().personality

        # ── Path validation — NO download, NO from_pretrained ─
        self._model_path = self._resolve_path(config.model_path, "model_path")
        self._mmproj_path = (
            self._resolve_path(config.mmproj_path, "mmproj_path")
            if config.mmproj_path
            else None
        )

        # ── Internal state ───────────────────────────────────
        self._llm = None  # Lazy load — llama_cpp.Llama instance
        self._history = ConversationHistory(
            context_limit=config.context_messages,
        )
        self._metrics = None  # Post-creation injection via set_metrics()
        self._last_visual_memo: str | None = None
        self._loaded = False

        logger.info(
            f"LlamaCppProvider initialized: "
            f"model={self._model_path.name}, "
            f"mmproj={'yes' if self._mmproj_path else 'no'}, "
            f"n_gpu_layers={config.n_gpu_layers}, "
            f"n_ctx={config.n_ctx}"
        )

    # ── Static helpers ────────────────────────────────────────

    @staticmethod
    def _resolve_path(path_str: str | None, field_name: str) -> Path:
        """
        Local dosya yolunu çözümle ve varlığını doğrula.
        Eksikse FileNotFoundError — ASLA download denemesi yok.
        """
        if not path_str:
            raise FileNotFoundError(
                f"LLM config '{field_name}' is not set. "
                f"Place GGUF/mmproj files under models/ and update config."
            )
        path = Path(path_str)
        if not path.exists():
            raise FileNotFoundError(
                f"Local model file missing: {path}\n"
                f"Place the required GGUF file under models/ directory."
            )
        return path

    # ── Public properties ─────────────────────────────────────

    @property
    def model_name(self) -> str:
        """Model dosya adı — routes ve UI'da kullanılır."""
        return self._model_path.name

    @property
    def is_loaded(self) -> bool:
        """Model GPU belleğe yüklü mü?"""
        return self._loaded and self._llm is not None

    @property
    def has_vision(self) -> bool:
        """Vision (mmproj) desteği var mı?"""
        return self._mmproj_path is not None

    # ── Lifecycle ─────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Lazy model loading — ilk kullanımda GPU'ya yükle."""
        if self._llm is not None:
            return

        logger.info(f"Loading GGUF model: {self._model_path.name}...")
        _t0 = time.perf_counter()

        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError(
                "llama-cpp-python is not installed. "
                "Install with CUDA support:\n"
                "  $env:CMAKE_ARGS = '-DGGML_CUDA=on'\n"
                "  pip install llama-cpp-python --no-cache-dir"
            ) from e

        kwargs = {
            "model_path": str(self._model_path),
            "n_gpu_layers": self._config.n_gpu_layers,
            "n_ctx": self._config.n_ctx,
            "verbose": False,
        }

        # Part 4b: n_ubatch — explicit override if configured
        if self._config.n_ubatch is not None:
            kwargs["n_ubatch"] = self._config.n_ubatch

        # Vision support — mmproj varsa clip model + chat handler ekle
        if self._mmproj_path:
            kwargs["clip_model_path"] = str(self._mmproj_path)

            # Part 4b: Resolve handler name — explicit override or auto-detect
            handler_name = self._resolve_handler_name()

            if handler_name:
                handler_kwargs = {
                    "clip_model_path": str(self._mmproj_path),
                    "verbose": False,
                }

                # Part 4b: Gemma4-specific kwargs
                if handler_name == "Gemma4ChatHandler":
                    handler_kwargs["enable_thinking"] = self._config.enable_thinking
                    self._apply_vision_budget(handler_name, handler_kwargs)

                try:
                    import importlib
                    mod = importlib.import_module("llama_cpp.llama_chat_format")
                    HandlerClass = getattr(mod, handler_name)
                    kwargs["chat_handler"] = HandlerClass(**handler_kwargs)

                    # Part 4b: Detailed handler log
                    budget_preset = self._config.vision_budget_preset
                    logger.info(
                        f"Vision handler:\n"
                        f"  model={self._model_path.name}\n"
                        f"  handler={handler_name}\n"
                        f"  enable_thinking={self._config.enable_thinking}\n"
                        f"  vision_budget_preset={budget_preset}\n"
                        f"  image_min_tokens={handler_kwargs.get('image_min_tokens', 'null')}\n"
                        f"  image_max_tokens={handler_kwargs.get('image_max_tokens', 'null')}\n"
                        f"  n_ubatch={self._config.n_ubatch or 'null'}"
                    )
                except (AttributeError, ImportError) as e:
                    # Part 4b/5: Clear error for unavailable handlers — no silent fallback
                    if "Gemma4" in handler_name:
                        logger.error(
                            f"Gemma 4 model detected but {handler_name} is unavailable "
                            f"in installed llama-cpp-python. "
                            f"Installed version: {self._get_llama_cpp_version()}. "
                            f"Please upgrade llama-cpp-python to a version that includes "
                            f"{handler_name}. Falling back to auto-detect (degraded vision)."
                        )
                    elif "Qwen3" in handler_name:
                        logger.error(
                            f"Qwen3-VL model detected but {handler_name} is unavailable "
                            f"in installed llama-cpp-python v{self._get_llama_cpp_version()}. "
                            f"Do not assume Qwen25VLChatHandler compatibility. "
                            f"Run explicit experimental smoke or install a supported binding. "
                            f"Falling back to auto-detect (degraded vision)."
                        )
                    else:
                        logger.warning(f"{handler_name} not available: {e} — using auto-detect")
            else:
                logger.warning(f"No handler mapped for {self._model_path.name} — using auto-detect")

        # Chat format — None ise model metadata'dan auto-detect
        if self._config.chat_format:
            kwargs["chat_format"] = self._config.chat_format

        self._llm = Llama(**kwargs)
        self._loaded = True

        _elapsed = time.perf_counter() - _t0
        logger.info(
            f"Model loaded in {_elapsed:.1f}s: "
            f"{self._model_path.name} "
            f"({'vision' if self._mmproj_path else 'text-only'})"
        )

    def unload(self) -> None:
        """Model'i GPU belleğinden kaldır."""
        if self._llm is not None:
            del self._llm
            self._llm = None
            self._loaded = False
            logger.info("Model unloaded from GPU memory")

    # ── Part 4b: Handler Resolution ───────────────────────────

    # Ordered pattern list — more specific patterns first
    _HANDLER_PATTERNS: list[tuple[list[str], str]] = [
        (["gemma-4", "gemma4", "e4b", "e2b"],         "Gemma4ChatHandler"),
        (["gemma-3", "gemma3", "gemma"],               "Gemma3ChatHandler"),
        (["qwen3-vl", "qwen3vl", "qwen3_vl", "qwen3"], "Qwen3VLChatHandler"),
        (["qwen2.5-vl", "qwen25vl", "qwen2_5", "qwen"], "Qwen25VLChatHandler"),
        (["minicpm"],                                   "MiniCPMv26ChatHandler"),
        (["llava"],                                     "Llava16ChatHandler"),
    ]

    _EXPLICIT_HANDLER_MAP: dict[str, str] = {
        "gemma4":   "Gemma4ChatHandler",
        "gemma3":   "Gemma3ChatHandler",
        "qwen3vl":  "Qwen3VLChatHandler",
        "qwen25vl": "Qwen25VLChatHandler",
        "minicpm":  "MiniCPMv26ChatHandler",
        "llava":    "Llava16ChatHandler",
    }

    _VISION_BUDGET_PRESETS: dict[str, tuple[int, int]] = {
        "screen_fast":     (280, 280),
        "screen_balanced": (560, 560),
        "screen_ocr":      (1120, 1120),
    }

    def _resolve_handler_name(self) -> str | None:
        """
        Part 4b: Resolve vision chat handler name.
        Priority: explicit config override > model name pattern matching.
        """
        # 1. Explicit override
        explicit = self._config.chat_handler
        if explicit and explicit != "auto":
            handler = self._EXPLICIT_HANDLER_MAP.get(explicit)
            if handler:
                logger.info(f"Vision handler (explicit override): {explicit} → {handler}")
                return handler
            else:
                logger.error(
                    f"Invalid chat_handler override: '{explicit}'. "
                    f"Allowed: auto, {', '.join(self._EXPLICIT_HANDLER_MAP.keys())}"
                )
                return None

        # 2. Auto-detect from model name — ordered, most specific first
        model_lower = self._model_path.name.lower()
        for patterns, handler_name in self._HANDLER_PATTERNS:
            if any(p in model_lower for p in patterns):
                logger.info(f"Vision handler (auto-detect): {handler_name} (matched in {self._model_path.name})")
                return handler_name

        return None

    def _apply_vision_budget(self, handler_name: str, handler_kwargs: dict) -> None:
        """
        Part 4b: Apply vision budget preset to handler kwargs.
        Only Gemma4ChatHandler supports budget parameters.
        Validates n_ubatch >= image_max_tokens when budget is active.
        """
        preset = self._config.vision_budget_preset
        if not preset:
            return  # null = disabled, no production change

        # Validate handler support
        if handler_name != "Gemma4ChatHandler":
            logger.error(
                f"vision_budget_preset='{preset}' is only supported for "
                f"Gemma4ChatHandler. Current handler: {handler_name}. "
                f"Budget will NOT be applied."
            )
            return

        # Resolve preset
        if preset not in self._VISION_BUDGET_PRESETS:
            logger.error(
                f"Invalid vision_budget_preset: '{preset}'. "
                f"Allowed: {', '.join(self._VISION_BUDGET_PRESETS.keys())}"
            )
            return

        min_tokens, max_tokens = self._VISION_BUDGET_PRESETS[preset]

        # n_ubatch guard — crash prevention
        n_ubatch = self._config.n_ubatch
        if n_ubatch is None or n_ubatch < max_tokens:
            logger.error(
                f"Vision budget '{preset}' requires n_ubatch >= {max_tokens}. "
                f"Current n_ubatch={n_ubatch or 'null (default)'}. "
                f"Set llm.n_ubatch >= {max_tokens} in config. "
                f"Budget will NOT be applied to prevent crash."
            )
            return

        handler_kwargs["image_min_tokens"] = min_tokens
        handler_kwargs["image_max_tokens"] = max_tokens
        logger.info(f"Vision budget applied: {preset} → min={min_tokens}, max={max_tokens}")

    @staticmethod
    def _get_llama_cpp_version() -> str:
        """Get installed llama-cpp-python version for diagnostics."""
        try:
            import llama_cpp
            return getattr(llama_cpp, "__version__", "unknown")
        except ImportError:
            return "not installed"

    # ── Injection ─────────────────────────────────────────────

    def set_metrics(self, metrics) -> None:
        """Post-creation metrics injection — registry factory pattern'i bozmaz."""
        self._metrics = metrics

    def set_personality(self, personality: PersonalityConfig) -> None:
        """Kişilik profilini değiştir."""
        self._personality = personality
        logger.info(f"Kişilik değiştirildi: {personality.name}")

    def set_model(self, model_name: str) -> None:
        """Aktif modeli değiştir (hot-swap için)."""
        # Sprint 4 PoC: path-based, ileride implement edilecek
        logger.warning(f"set_model({model_name}) — hot-swap not yet implemented")

    # ── Image Metadata (Part 1.5) ──────────────────────────────

    def _log_image_metadata(
        self,
        image_bytes: bytes,
        source: str = "unknown",
        captured_at: float | None = None,
        jpeg_quality: int | None = None,
        original_size: tuple[int, int] | None = None,
        frame_id: int | None = None,
    ) -> None:
        """
        LLM inference öncesi image metadata logla ve debug export yap.
        Safe: path/secret/env leak yok.
        """
        from src.image_metadata import (
            build_image_metadata,
            log_image_context,
            export_debug_frame,
        )

        meta = build_image_metadata(
            source=source,
            image_bytes=image_bytes,
            original_size=original_size,
            jpeg_quality=jpeg_quality,
            frame_id=frame_id,
            captured_at=captured_at,
        )
        log_image_context(meta)

        # Debug export — flag-gated
        try:
            config = get_config()
            if config.features.enable_debug_capture_export:
                export_debug_frame(image_bytes, source)
        except Exception:
            pass  # Config/export failure should never block inference

    # ── Message Building ──────────────────────────────────────

    def _build_system_prompt(self, response_mode: str = "text") -> str:
        """
        Kişilik profilinden modüler system prompt oluştur.

        Bölümler:
          1. system_prompt     — Ana kişilik ve davranış kuralları
          2. screen_analysis   — Ekran yorumlama talimatları
          3. emotion_rules     — Duygu algılama/yansıtma filtresi
          4. response_format   — Çıktı biçim kuralları

        Args:
            response_mode: "voice" veya "text" — format kurallarını belirler
        """
        p = self._personality
        sections: list[str] = []

        # 1. Core identity
        if p.system_prompt:
            sections.append(p.system_prompt.strip())

        # 2. Screen analysis
        if p.screen_analysis_prompt:
            sections.append(p.screen_analysis_prompt.strip())

        # 3. Emotion rules
        if p.emotion_rules:
            sections.append(p.emotion_rules.strip())

        # 4. Response format
        if p.response_format:
            sections.append(p.response_format.strip())

        # 5. Mode indicator — concise, not verbose
        if response_mode == "voice":
            sections.append("ŞU AN SES MODU: Cevabın sesli okunacak. Markdown kullanma, doğal konuş.")

        return "\n\n".join(sections)

    def _build_messages(
        self,
        user_message: str,
        image_bytes: bytes | None = None,
        response_mode: str = "text",
        image_source: str = "unknown",
        image_artifact=None,
    ) -> list[dict]:
        """
        llama-cpp-python chat completion formatında mesaj listesi oluştur.

        Part 2: image_artifact verilmişse canonical path kullanır.
        Verilmemişse image_bytes'tan artifact oluşturur (backward compat).
        """
        from src.image_metadata import log_image_context, export_debug_frame

        messages: list[dict] = []

        # System prompt — response_mode ile mod-aware
        system_prompt = self._build_system_prompt(response_mode=response_mode)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # ── Resolve canonical artifact ──
        artifact = image_artifact
        if artifact is None and image_bytes is not None and self.has_vision:
            try:
                from src.image_artifact import build_artifact_from_bytes
                artifact = build_artifact_from_bytes(image_bytes, source=image_source)
            except Exception as e:
                logger.warning(f"Image artifact build failed: {e} — skipping image")
                artifact = None

        # Effective image bytes for prompt logic
        eff_image = artifact.image_bytes if artifact else image_bytes

        # Default prompt for image-only mode (no user text)
        if not user_message.strip() and eff_image:
            user_message = "Ekranımda ne görüyorsun? Detaylı anlat."

        if artifact and self.has_vision:
            # ── STATELESS VISION MODE (canonical artifact path) ──
            # System + image + user message only. No history.

            # Metadata log
            log_image_context(artifact.metadata)

            # Debug export — flag-gated
            try:
                config = get_config()
                if config.features.enable_debug_capture_export:
                    export_debug_frame(artifact.image_bytes, artifact.source)
            except Exception:
                pass

            # MIME-aware data URI
            b64 = base64.b64encode(artifact.image_bytes).decode("utf-8")
            mime = artifact.mime_type or "image/jpeg"
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}",
                        },
                    },
                ],
            })
        else:
            # ── TEXT-ONLY MODE ──
            # Include history for conversational continuity
            for msg in self._history.get_context_window():
                messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": user_message})

        return messages

    # ── Sync Inference (executor'da çalışır) ──────────────────

    def _sync_chat(
        self,
        messages: list[dict],
    ) -> dict:
        """
        Senkron chat completion — run_in_executor ile async bridge'lenir.
        Doğrudan çağırma; chat() veya chat_stream() kullan.
        """
        self._ensure_loaded()
        return self._llm.create_chat_completion(
            messages=messages,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            repeat_penalty=self._config.repeat_penalty,
        )

    def _sync_chat_stream(
        self,
        messages: list[dict],
    ):
        """
        Senkron streaming — chunk generator döndürür.
        Doğrudan çağırma; chat_stream() kullan.
        """
        self._ensure_loaded()
        return self._llm.create_chat_completion(
            messages=messages,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
            repeat_penalty=self._config.repeat_penalty,
            stream=True,
        )

    # ── Async Public API ──────────────────────────────────────

    async def chat(
        self,
        message: str,
        image_bytes: bytes | None = None,
        response_mode: str = "text",
        image_source: str = "unknown",
        image_artifact=None,
    ) -> str:
        """
        Async chat — non-blocking, event loop'u dondurmaz.
        Sync llama-cpp → async bridge (run_in_executor).
        """
        messages = self._build_messages(message, image_bytes, response_mode, image_source, image_artifact)
        _t0 = time.perf_counter()

        try:
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None, self._sync_chat, messages,
            )

            # Latency recording
            _elapsed_ms = (time.perf_counter() - _t0) * 1000
            if self._metrics:
                self._metrics.record_latency("llm_latency_ms", _elapsed_ms)

            # Token usage log
            usage = response.get("usage", {})
            if usage:
                logger.debug(
                    f"LLM tokens — prompt: {usage.get('prompt_tokens')}, "
                    f"completion: {usage.get('completion_tokens')}, "
                    f"latency: {_elapsed_ms:.0f}ms"
                )

            # Response extraction — strip leading whitespace/newlines
            assistant_content = response["choices"][0]["message"]["content"].strip()

            # History update — sadece metin sakla, image yok
            self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)

            return assistant_content

        except Exception as e:
            logger.error(f"LLM chat hatası ({self.model_name}): {e}")
            if self._metrics:
                self._metrics.increment("llm_errors_total")
            raise RuntimeError(f"LLM chat failed: {e}") from e

    async def chat_stream(
        self,
        message: str,
        image_bytes: bytes | None = None,
        response_mode: str = "text",
        image_source: str = "unknown",
        image_artifact=None,
    ) -> AsyncGenerator[str, None]:
        """
        Async streaming chat — token-by-token yield.
        Sync generator → async bridge (run_in_executor + queue).
        """
        messages = self._build_messages(message, image_bytes, response_mode, image_source, image_artifact)
        _t0 = time.perf_counter()

        try:
            loop = asyncio.get_running_loop()

            # Sync streaming'i executor'da çalıştır, queue ile async'e aktar
            queue: asyncio.Queue[str | None] = asyncio.Queue()

            def _stream_worker():
                """Executor'da çalışan sync stream consumer."""
                try:
                    for chunk in self._sync_chat_stream(messages):
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            loop.call_soon_threadsafe(queue.put_nowait, token)
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

            # Stream worker'ı arka planda başlat
            stream_future = loop.run_in_executor(None, _stream_worker)

            full_response: list[str] = []
            _first_token = True
            while True:
                token = await queue.get()
                if token is None:
                    break
                # Strip leading whitespace from first token
                if _first_token:
                    token = token.lstrip()
                    _first_token = False
                    if not token:
                        continue
                full_response.append(token)
                yield token

            # Future'ın hatasını yakala
            await stream_future

            # Latency recording
            _elapsed_ms = (time.perf_counter() - _t0) * 1000
            if self._metrics:
                self._metrics.record_latency("llm_latency_ms", _elapsed_ms)

            # History update — sadece metin sakla, image history'de tutulmaz
            assistant_content = "".join(full_response)
            self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)

        except Exception as e:
            logger.error(f"LLM stream hatası: {e}")
            if self._metrics:
                self._metrics.increment("llm_errors_total")
            raise RuntimeError(f"LLM stream failed: {e}") from e

    # ── Visual Memo ───────────────────────────────────────────

    async def _bg_visual_memo(
        self,
        user_msg: ChatMessage,
        image_bytes: bytes,
    ) -> None:
        """Arka planda visual memo üret — kullanıcı beklemez."""
        try:
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            messages = [{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISUAL_MEMO_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }]

            loop = asyncio.get_running_loop()

            def _sync_memo():
                self._ensure_loaded()
                return self._llm.create_chat_completion(
                    messages=messages,
                    temperature=0.3,
                    max_tokens=1024,
                )

            response = await loop.run_in_executor(None, _sync_memo)
            memo = response["choices"][0]["message"]["content"]
            user_msg.visual_memo = memo
            self._last_visual_memo = memo
            logger.debug(f"Visual memo: {memo[:100]}...")

        except Exception as e:
            logger.error(f"Visual memo hatası: {e}")
            user_msg.visual_memo = "Ekran okunamadı."

    # ── History Delegation ────────────────────────────────────

    def get_history(self) -> list[ChatMessage]:
        """Konuşma geçmişini döndür."""
        return self._history.messages

    def clear_history(self) -> None:
        """Konuşma geçmişini temizle."""
        self._history.clear()

    def export_history(self) -> list[dict]:
        """History'yi export edilebilir formata dönüştür."""
        return self._history.export()

    # ── Protocol Compliance ──────────────────────────────────

    def health(self) -> dict:
        """Provider durum raporu — LLMProvider protocol."""
        return {
            "provider": "llama-cpp",
            "model": self._model_path.name,
            "loaded": self.is_loaded,
            "has_vision": self.has_vision,
            "history_length": len(self._history),
            "last_visual_memo": self._last_visual_memo is not None,
        }

    async def aclose(self) -> None:
        """Async resource cleanup — LLMProvider protocol."""
        self.unload()
