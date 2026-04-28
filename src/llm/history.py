"""
VoxDesk — Conversation History Manager
Provider-agnostic konuşma geçmişi yönetimi.
Model yüklemesi gerektirmez — saf Python logic.

Design:
  - TEXT ONLY: History'de sadece metin saklanır. Image hiçbir şekilde tutulmaz.
  - Token budget: Toplam history ~2K token'ı aştığında eski mesajlar otomatik silinir,
    en yeni ~2K token'lık kısım korunur.
  - Context window: Son N mesajı döndürür (LLM context'e gönderilecek kısım).
"""

from __future__ import annotations

import time
import logging

from src.llm.types import ChatMessage

logger = logging.getLogger("voxdesk.llm.history")

# Token budget: ~2K token ≈ 8000 karakter (1 token ≈ 4 char tahmini)
MAX_HISTORY_CHARS = 8000


class ConversationHistory:
    """
    Text-only konuşma geçmişi — otomatik token budget yönetimi.

    - Image/visual memo history'de TUTULMAZ
    - Token sınırına yaklaşınca eski mesajlar auto-flush
    - Context window ile son N mesajı döndürür
    """

    def __init__(self, context_limit: int = 6) -> None:
        self._messages: list[ChatMessage] = []
        self._context_limit = context_limit

    @property
    def messages(self) -> list[ChatMessage]:
        """Tüm mesaj listesinin kopyasını döndür."""
        return self._messages.copy()

    def _total_chars(self) -> int:
        """Toplam history karakter sayısı."""
        return sum(len(m.content) for m in self._messages)

    def _auto_trim(self) -> None:
        """
        Token budget aşıldığında eski mesajları sil.
        En yeni ~2K token'lık (8000 char) kısmı koru.
        """
        total = self._total_chars()
        if total <= MAX_HISTORY_CHARS:
            return

        # En yeniden eskiye doğru tara, bütçe dolana kadar tut
        kept: list[ChatMessage] = []
        budget = 0
        for msg in reversed(self._messages):
            budget += len(msg.content)
            if budget > MAX_HISTORY_CHARS:
                break
            kept.append(msg)
        kept.reverse()

        removed = len(self._messages) - len(kept)
        self._messages = kept
        logger.info(
            f"History auto-trimmed: {removed} mesaj silindi, "
            f"{len(kept)} mesaj kaldı ({self._total_chars()} chars)"
        )

    def get_context_window(self) -> list[ChatMessage]:
        """Son N mesajı döndür — LLM context'e gönderilecek kısım."""
        if not self._messages:
            return []
        return self._messages[-self._context_limit:]

    def add_user_message(self, content: str, visual_memo: str | None = None) -> ChatMessage:
        """Kullanıcı mesajı ekle (TEXT ONLY — image bilgisi saklanmaz)."""
        msg = ChatMessage(
            role="user",
            content=content,
            visual_memo=visual_memo,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        self._auto_trim()
        return msg

    def add_assistant_message(self, content: str) -> ChatMessage:
        """Asistan yanıtı ekle."""
        msg = ChatMessage(
            role="assistant",
            content=content,
            timestamp=time.time(),
        )
        self._messages.append(msg)
        self._auto_trim()
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

