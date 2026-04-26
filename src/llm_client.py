"""
VoxDesk — Ollama Vision LLM Client
Lokal Ollama API ile görsel analiz ve chat.
Async client ile non-blocking, visual memo sistemi ile verimli context.
"""

from __future__ import annotations

import asyncio
import base64
import time
import logging
from dataclasses import dataclass
from typing import AsyncGenerator

import ollama

from src.config import get_config, PersonalityConfig

logger = logging.getLogger("voxdesk.llm")

# Visual memo prompt — LLM ekran görüntüsü hakkında detaylı memo yazar
VISUAL_MEMO_PROMPT = (
    "Ekranda gördüğün her şeyi detaylı bir şekilde tanımla. "
    "Açık olan uygulamalar, pencere başlıkları, kod içerikleri, "
    "metin, butonlar, renkler, layout — her detayı yaz. "
    "Bu memo sonraki konuşmalarda kullanılacak. Kısa tutma, detaylı yaz."
)


@dataclass
class ChatMessage:
    role: str           # "user", "assistant", "system"
    content: str
    visual_memo: str | None = None  # Image yerine metin memo — verimli context
    timestamp: float = 0.0


class VisionLLM:
    """
    Ollama vision model ile iletişim katmanı.
    System prompt, kişilik, conversation history yönetimi.
    """

    def __init__(self):
        config = get_config()
        self.model = config.llm.model
        self.temperature = config.llm.temperature
        self.max_tokens = config.llm.max_tokens
        self.context_limit = config.llm.context_messages
        self.fallback_models = config.llm.fallback_models
        self.personality = config.personality

        self._history: list[ChatMessage] = []
        self._async_client = ollama.AsyncClient()  # Non-blocking async client
        self._last_visual_memo: str | None = None

    def _build_system_prompt(self) -> str:
        """Kişilik profilinden system prompt oluştur."""
        return self.personality.system_prompt

    def _build_messages(
        self,
        user_message: str,
        image_bytes: bytes | None = None,
    ) -> list[dict]:
        """Ollama API formatında mesaj listesi oluştur."""
        messages = []

        # System prompt
        system_prompt = self._build_system_prompt()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Conversation history — image yerine visual memo kullan
        recent = self._history[-self.context_limit:] if self._history else []
        for msg in recent:
            content = msg.content
            # Visual memo varsa context'e ekle
            if msg.visual_memo:
                content = f"[Ekran Notu: {msg.visual_memo}]\n\n{content}"
            messages.append({"role": msg.role, "content": content})

        # Yeni kullanıcı mesajı — sadece ŞİMDİKİ mesaja image ekle
        user_entry = {"role": "user", "content": user_message}
        if image_bytes:
            user_entry["images"] = [base64.b64encode(image_bytes).decode("utf-8")]
        messages.append(user_entry)

        return messages

    async def _generate_visual_memo(self, image_bytes: bytes) -> str:
        """
        Ekran görüntüsü hakkında detaylı visual memo oluştur.
        Bu memo, image yerine history'de tutulur — token efficient.
        """
        try:
            response = await self._async_client.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": VISUAL_MEMO_PROMPT,
                    "images": [base64.b64encode(image_bytes).decode("utf-8")],
                }],
                options={"temperature": 0.3, "num_predict": 512},
            )
            memo = response.message.content
            self._last_visual_memo = memo
            logger.debug(f"Visual memo: {memo[:100]}...")
            return memo
        except Exception as e:
            logger.error(f"Visual memo hatası: {e}")
            return "Ekran okunamadı."

    async def chat(
        self,
        message: str,
        image_bytes: bytes | None = None,
    ) -> str:
        """
        Async chat — non-blocking, event loop'u dondurmaz.
        """
        messages = self._build_messages(message, image_bytes)

        try:
            response = await self._async_client.chat(
                model=self.model,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )

            assistant_content = response.message.content

            # History'ye hemen ekle (memo sonra gelecek)
            user_msg = ChatMessage(
                role="user", content=message,
                visual_memo=None,
                timestamp=time.time(),
            )
            self._history.append(user_msg)
            self._history.append(ChatMessage(
                role="assistant", content=assistant_content,
                timestamp=time.time(),
            ))

            # Visual memo arka planda üret — cevap zaten döndü,
            # kullanıcı beklemez, memo sonraki context için hazırlanır
            if image_bytes:
                async def _bg_memo():
                    memo = await self._generate_visual_memo(image_bytes)
                    user_msg.visual_memo = memo
                asyncio.create_task(_bg_memo())

            return assistant_content

        except Exception as e:
            logger.error(f"LLM chat hatası ({self.model}): {e}")
            for fallback in self.fallback_models:
                try:
                    logger.info(f"Fallback model deneniyor: {fallback}")
                    response = await self._async_client.chat(
                        model=fallback, messages=messages,
                    )
                    return response.message.content
                except Exception:
                    continue
            return f"Hata: Hiçbir model çalışmadı — {e}"

    async def chat_stream(
        self,
        message: str,
        image_bytes: bytes | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Async streaming chat — event loop'u bloke etmez.
        ollama.AsyncClient ile native async streaming.
        """
        messages = self._build_messages(message, image_bytes)
        full_response = []

        try:
            stream = await self._async_client.chat(
                model=self.model,
                messages=messages,
                stream=True,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )

            async for chunk in stream:
                token = chunk.message.content
                full_response.append(token)
                yield token

            # History'ye hemen ekle, memo arka planda gelecek
            assistant_content = "".join(full_response)
            user_msg = ChatMessage(
                role="user", content=message,
                visual_memo=None,
                timestamp=time.time(),
            )
            self._history.append(user_msg)
            self._history.append(ChatMessage(
                role="assistant", content=assistant_content,
                timestamp=time.time(),
            ))

            # Memo arka planda üret
            if image_bytes:
                async def _bg_memo():
                    memo = await self._generate_visual_memo(image_bytes)
                    user_msg.visual_memo = memo
                asyncio.create_task(_bg_memo())

        except Exception as e:
            logger.error(f"LLM stream hatası: {e}")
            yield f"Hata: {e}"

    def get_history(self) -> list[ChatMessage]:
        """Konuşma geçmişini döndür."""
        return self._history.copy()

    def clear_history(self) -> None:
        """Konuşma geçmişini temizle."""
        self._history.clear()
        logger.info("Konuşma geçmişi temizlendi")

    def set_model(self, model_name: str) -> None:
        """Aktif modeli değiştir."""
        self.model = model_name
        logger.info(f"Model değiştirildi: {model_name}")

    def set_personality(self, personality: PersonalityConfig) -> None:
        """Kişilik profilini değiştir."""
        self.personality = personality
        logger.info(f"Kişilik değiştirildi: {personality.name}")

    async def list_models(self) -> list[dict]:
        """Ollama'da yüklü modelleri listele (lokal, async)."""
        try:
            models = await self._async_client.list()
            return [
                {
                    "name": m.model,
                    "size": m.size,
                    "modified_at": str(m.modified_at) if m.modified_at else None,
                }
                for m in models.models
            ]
        except Exception as e:
            logger.error(f"Model listesi alınamadı: {e}")
            return []

    def export_history(self) -> list[dict]:
        """History'yi export edilebilir formata dönüştür."""
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "visual_memo": msg.visual_memo,
            }
            for msg in self._history
        ]
