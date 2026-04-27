"""
VoxDesk — Conversation History Manager
Provider-agnostic konuşma geçmişi yönetimi.
Model yüklemesi gerektirmez — saf Python logic.
"""

from __future__ import annotations

import time
import logging

from src.llm.types import ChatMessage

logger = logging.getLogger("voxdesk.llm.history")


class ConversationHistory:
    """
    Konuşma geçmişi — context windowing, export, visual memo desteği.

    Provider'dan bağımsız:
    - ChatMessage listesi tutar
    - Context limit ile son N mesajı döndürür
    - Visual memo'ları mesajlara enjekte eder
    - Export/import JSON formatında yapılır
    """

    def __init__(self, context_limit: int = 10) -> None:
        self._messages: list[ChatMessage] = []
        self._context_limit = context_limit

    @property
    def messages(self) -> list[ChatMessage]:
        """Tüm mesaj listesinin kopyasını döndür."""
        return self._messages.copy()

    def get_context_window(self) -> list[ChatMessage]:
        """Son N mesajı döndür — LLM context'e gönderilecek kısım."""
        if not self._messages:
            return []
        return self._messages[-self._context_limit:]

    def add_user_message(
        self,
        content: str,
        visual_memo: str | None = None,
    ) -> ChatMessage:
        """Kullanıcı mesajı ekle. Döndürülen referansa memo sonra eklenebilir."""
        msg = ChatMessage(
            role="user",
            content=content,
            visual_memo=visual_memo,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        return msg

    def add_assistant_message(self, content: str) -> ChatMessage:
        """Asistan yanıtı ekle."""
        msg = ChatMessage(
            role="assistant",
            content=content,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        return msg

    def clear(self) -> None:
        """Tüm geçmişi temizle."""
        count = len(self._messages)
        self._messages.clear()
        logger.info(f"Konuşma geçmişi temizlendi ({count} mesaj)")

    def export(self) -> list[dict]:
        """History'yi JSON-serializable formata dönüştür."""
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp,
                "visual_memo": msg.visual_memo,
            }
            for msg in self._messages
        ]

    def __len__(self) -> int:
        return len(self._messages)

    def __bool__(self) -> bool:
        return bool(self._messages)
