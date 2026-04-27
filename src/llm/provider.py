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

        # Vision support — mmproj varsa clip model olarak ekle
        if self._mmproj_path:
            kwargs["clip_model_path"] = str(self._mmproj_path)

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

    # ── Message Building ──────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Kişilik profilinden system prompt oluştur."""
        return self._personality.system_prompt

    def _build_messages(
        self,
        user_message: str,
        image_bytes: bytes | None = None,
    ) -> list[dict]:
        """
        llama-cpp-python chat completion formatında mesaj listesi oluştur.

        Format: OpenAI-compatible
          - text: {"role": "user", "content": "..."}
          - vision: {"role": "user", "content": [
                {"type": "text", "text": "..."},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
            ]}
        """
        messages: list[dict] = []

        # System prompt
        system_prompt = self._build_system_prompt()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Conversation history — image yerine visual memo kullan
        for msg in self._history.get_context_window():
            content = msg.content
            if msg.visual_memo:
                content = f"[Ekran Notu: {msg.visual_memo}]\n\n{content}"
            messages.append({"role": msg.role, "content": content})

        # Yeni kullanıcı mesajı
        if image_bytes and self.has_vision:
            # Vision format — OpenAI-compatible content list
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_message},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                        },
                    },
                ],
            })
        else:
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
            stream=True,
        )

    # ── Async Public API ──────────────────────────────────────

    async def chat(
        self,
        message: str,
        image_bytes: bytes | None = None,
    ) -> str:
        """
        Async chat — non-blocking, event loop'u dondurmaz.
        Sync llama-cpp → async bridge (run_in_executor).
        """
        messages = self._build_messages(message, image_bytes)
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

            # Response extraction
            assistant_content = response["choices"][0]["message"]["content"]

            # History update
            user_msg = self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)

            # Visual memo arka planda üret
            if image_bytes and self.has_vision:
                asyncio.create_task(self._bg_visual_memo(user_msg, image_bytes))

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
    ) -> AsyncGenerator[str, None]:
        """
        Async streaming chat — token-by-token yield.
        Sync generator → async bridge (run_in_executor + queue).
        """
        messages = self._build_messages(message, image_bytes)
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
            while True:
                token = await queue.get()
                if token is None:
                    break
                full_response.append(token)
                yield token

            # Future'ın hatasını yakala
            await stream_future

            # Latency recording
            _elapsed_ms = (time.perf_counter() - _t0) * 1000
            if self._metrics:
                self._metrics.record_latency("llm_latency_ms", _elapsed_ms)

            # History update
            assistant_content = "".join(full_response)
            user_msg = self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)

            # Visual memo arka planda üret
            if image_bytes and self.has_vision:
                asyncio.create_task(self._bg_visual_memo(user_msg, image_bytes))

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
                    max_tokens=512,
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
