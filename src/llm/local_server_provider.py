"""
VoxDesk — LocalLlamaServerProvider
HTTP client for a locally-managed llama-server sidecar.

Architecture:
  VoxDesk → HTTP POST → http://127.0.0.1:<port>/v1/chat/completions
  → local llama-server process (app-managed sidecar)
  → local GGUF model + mmproj

Privacy guarantee:
  - Only localhost/127.0.0.1 base_url accepted
  - Remote URLs rejected at construction time
  - base64 image payloads NEVER logged
  - No cloud, no telemetry, no external network calls
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlparse

import httpx

from src.config import LocalLlamaServerConfig, get_config
from src.llm.types import ChatMessage
from src.llm.history import ConversationHistory

logger = logging.getLogger("voxdesk.llm.local_server")

# Allowed hostnames — anything else is rejected
_LOCALHOST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class LocalServerError(RuntimeError):
    """Error communicating with local llama-server."""
    pass


class LocalLlamaServerProvider:
    """
    LLM provider that talks to a local llama-server via OpenAI-compatible API.

    Lifecycle:
      1. __init__(config) → validate paths, enforce localhost
      2. health_check() → verify server is reachable
      3. chat(message, image_artifact) → async inference
      4. chat_stream(message, image_artifact) → async streaming

    Design:
      - HTTP client (httpx.AsyncClient) for non-blocking requests
      - Supports text-only and multimodal (image_url) payloads
      - History managed via ConversationHistory
      - Never logs base64 image data
    """

    def __init__(self, config: LocalLlamaServerConfig) -> None:
        self._config = config
        self._personality = get_config().personality

        # ── Privacy enforcement: localhost only ──
        parsed = urlparse(config.base_url)
        hostname = parsed.hostname or ""
        if hostname not in _LOCALHOST_HOSTS:
            raise ValueError(
                f"SECURITY: LocalLlamaServerProvider rejects non-localhost base_url: "
                f"'{config.base_url}'. Only 127.0.0.1/localhost/::1 allowed. "
                f"This is a privacy-first local-only provider."
            )

        self._base_url = config.base_url.rstrip("/")
        self._completions_url = f"{self._base_url}/v1/chat/completions"

        # ── Model path validation ──
        self._model_path = self._validate_path(config.model_path, "model_path")
        self._mmproj_path = (
            self._validate_path(config.mmproj_path, "mmproj_path")
            if config.mmproj_path
            else None
        )

        # ── Internal state ──
        self._history = ConversationHistory(
            context_limit=config.context_messages,
        )
        self._metrics = None
        self._client: httpx.AsyncClient | None = None
        self._server_available = False

        logger.info(
            f"LocalLlamaServerProvider initialized:\n"
            f"  base_url={self._base_url}\n"
            f"  model={self._model_path.name}\n"
            f"  mmproj={'yes' if self._mmproj_path else 'no'}\n"
            f"  temperature={config.temperature}\n"
            f"  top_p={config.top_p}, top_k={config.top_k}"
        )

    @staticmethod
    def _validate_path(path_str: str, field_name: str) -> Path:
        """Validate local file path exists. Never downloads."""
        if not path_str:
            raise FileNotFoundError(
                f"LocalLlamaServer config '{field_name}' is not set. "
                f"Place GGUF files under models/ and update config."
            )
        path = Path(path_str)
        if not path.exists():
            raise FileNotFoundError(
                f"Local model file missing: {path}\n"
                f"Place the required GGUF file under models/ directory."
            )
        return path

    # ── Properties ──

    @property
    def model_name(self) -> str:
        return self._model_path.name

    @property
    def is_loaded(self) -> bool:
        return self._server_available

    @property
    def has_vision(self) -> bool:
        return self._mmproj_path is not None

    # ── HTTP Client ──

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0),
                limits=httpx.Limits(max_connections=4),
            )
        return self._client

    async def health_check(self) -> bool:
        """Check if the local llama-server is reachable."""
        try:
            client = self._get_client()
            resp = await client.get(f"{self._base_url}/health", timeout=5.0)
            self._server_available = resp.status_code == 200
            if self._server_available:
                logger.info("Local llama-server health check: OK")
            else:
                logger.warning(f"Local llama-server health check failed: {resp.status_code}")
            return self._server_available
        except Exception as e:
            self._server_available = False
            logger.warning(f"Local llama-server unreachable: {e}")
            return False

    # ── Injection ──

    def set_metrics(self, metrics) -> None:
        self._metrics = metrics

    def set_personality(self, personality) -> None:
        self._personality = personality
        logger.info(f"Personality changed: {personality.name}")

    def set_model(self, model_name: str) -> None:
        logger.warning(f"set_model({model_name}) — hot-swap not available for local server")

    # ── Message Building ──

    def _build_system_prompt(self, response_mode: str = "text") -> str:
        """Build system prompt from personality config."""
        p = self._personality
        sections: list[str] = []

        if p.system_prompt:
            sections.append(p.system_prompt.strip())
        if p.screen_analysis_prompt:
            sections.append(p.screen_analysis_prompt.strip())
        if p.emotion_rules:
            sections.append(p.emotion_rules.strip())
        if p.response_format:
            sections.append(p.response_format.strip())

        if response_mode == "voice":
            sections.append("ŞU AN SES MODU: Cevabın sesli okunacak. Markdown kullanma, doğal konuş.")

        return "\n\n".join(sections)

    def _build_messages(
        self,
        user_message: str,
        response_mode: str = "text",
        image_artifact=None,
    ) -> list[dict]:
        """
        Build OpenAI-compatible message list.
        When image_artifact is present: multimodal with image_url.
        Otherwise: text-only with history.
        """
        messages: list[dict] = []

        # System prompt
        system_prompt = self._build_system_prompt(response_mode=response_mode)
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if not user_message.strip() and image_artifact:
            user_message = "Ekranımda ne görüyorsun? Detaylı anlat."

        if image_artifact and self.has_vision:
            # ── MULTIMODAL: image_url content ──
            # PRIVACY: base64 is embedded in payload but NEVER logged
            b64 = base64.b64encode(image_artifact.image_bytes).decode("utf-8")
            mime = getattr(image_artifact, 'mime_type', None) or "image/jpeg"

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
            # Log WITHOUT base64 data
            logger.info(
                f"📸 Multimodal request: {image_artifact.source} "
                f"({len(image_artifact.image_bytes)} bytes, {mime})"
            )
        else:
            # ── TEXT-ONLY with history ──
            for msg in self._history.get_context_window():
                messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": user_message})

        return messages

    # ── Inference ──

    async def chat(
        self,
        message: str,
        image_bytes: bytes | None = None,
        response_mode: str = "text",
        image_source: str = "unknown",
        image_artifact=None,
    ) -> str:
        """Async chat via local llama-server."""
        # Build backward-compat artifact from raw bytes if needed
        if image_artifact is None and image_bytes is not None and self.has_vision:
            try:
                from src.image_artifact import build_artifact_from_bytes
                image_artifact = build_artifact_from_bytes(image_bytes, source=image_source)
            except Exception as e:
                logger.warning(f"Image artifact build failed: {e}")

        messages = self._build_messages(message, response_mode, image_artifact)
        _t0 = time.perf_counter()

        try:
            client = self._get_client()
            payload = {
                "messages": messages,
                "temperature": self._config.temperature,
                "top_p": self._config.top_p,
                "max_tokens": self._config.max_tokens,
                "stream": False,
            }
            # top_k may not be supported by all OpenAI-compat APIs, add only if non-zero
            if self._config.top_k > 0:
                payload["top_k"] = self._config.top_k

            resp = await client.post(self._completions_url, json=payload)

            if resp.status_code != 200:
                error_text = resp.text[:500]
                raise LocalServerError(
                    f"Local llama-server returned {resp.status_code}: {error_text}"
                )

            data = resp.json()
            assistant_content = data["choices"][0]["message"]["content"].strip()

            _elapsed_ms = (time.perf_counter() - _t0) * 1000
            if self._metrics:
                self._metrics.record_latency("llm_latency_ms", _elapsed_ms)

            # Usage log
            usage = data.get("usage", {})
            if usage:
                logger.debug(
                    f"LLM tokens — prompt: {usage.get('prompt_tokens')}, "
                    f"completion: {usage.get('completion_tokens')}, "
                    f"latency: {_elapsed_ms:.0f}ms"
                )

            self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)

            self._server_available = True
            return assistant_content

        except httpx.ConnectError as e:
            self._server_available = False
            raise LocalServerError(
                f"Local llama-server unreachable at {self._base_url}: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Local server chat error: {e}")
            if self._metrics:
                self._metrics.increment("llm_errors_total")
            raise RuntimeError(f"Local server chat failed: {e}") from e

    async def chat_stream(
        self,
        message: str,
        image_bytes: bytes | None = None,
        response_mode: str = "text",
        image_source: str = "unknown",
        image_artifact=None,
    ) -> AsyncGenerator[str, None]:
        """Async streaming chat via local llama-server."""
        if image_artifact is None and image_bytes is not None and self.has_vision:
            try:
                from src.image_artifact import build_artifact_from_bytes
                image_artifact = build_artifact_from_bytes(image_bytes, source=image_source)
            except Exception as e:
                logger.warning(f"Image artifact build failed: {e}")

        messages = self._build_messages(message, response_mode, image_artifact)
        _t0 = time.perf_counter()

        try:
            client = self._get_client()
            payload = {
                "messages": messages,
                "temperature": self._config.temperature,
                "top_p": self._config.top_p,
                "max_tokens": self._config.max_tokens,
                "stream": True,
            }
            if self._config.top_k > 0:
                payload["top_k"] = self._config.top_k

            full_response: list[str] = []
            _first_token = True

            async with client.stream("POST", self._completions_url, json=payload) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    raise LocalServerError(
                        f"Local llama-server stream error {resp.status_code}: {body[:500]}"
                    )

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break

                    import json
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        if _first_token:
                            token = token.lstrip()
                            _first_token = False
                            if not token:
                                continue
                        full_response.append(token)
                        yield token

            _elapsed_ms = (time.perf_counter() - _t0) * 1000
            if self._metrics:
                self._metrics.record_latency("llm_latency_ms", _elapsed_ms)

            assistant_content = "".join(full_response)
            self._history.add_user_message(message)
            self._history.add_assistant_message(assistant_content)
            self._server_available = True

        except httpx.ConnectError as e:
            self._server_available = False
            raise LocalServerError(
                f"Local llama-server unreachable at {self._base_url}: {e}"
            ) from e
        except Exception as e:
            logger.error(f"Local server stream error: {e}")
            if self._metrics:
                self._metrics.increment("llm_errors_total")
            raise RuntimeError(f"Local server stream failed: {e}") from e

    # ── History ──

    def get_history(self) -> list[ChatMessage]:
        return self._history.messages

    def clear_history(self) -> None:
        self._history.clear()

    def export_history(self) -> list[dict]:
        return self._history.export()

    # ── Protocol ──

    def health(self) -> dict:
        return {
            "provider": "local-llama-server",
            "model": self._model_path.name,
            "loaded": self._server_available,
            "has_vision": self.has_vision,
            "base_url": self._base_url,
            "history_length": len(self._history),
        }

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def unload(self) -> None:
        """No-op for server provider — sidecar handles model lifecycle."""
        pass
