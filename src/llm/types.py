"""
VoxDesk — LLM Types & Constants
Provider-agnostic veri yapıları ve sabitler.
Hiçbir runtime bağımlılığı yok — sadece stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ChatMessage:
    """Konuşma geçmişindeki tek bir mesaj."""
    role: str           # "user", "assistant", "system"
    content: str
    visual_memo: str | None = None  # Image yerine metin memo — verimli context
    timestamp: float = 0.0


# Visual memo prompt — LLM ekran görüntüsü hakkında detaylı memo yazar
VISUAL_MEMO_PROMPT = (
    "Ekranda gördüğün her şeyi detaylı bir şekilde tanımla. "
    "Açık olan uygulamalar, pencere başlıkları, kod içerikleri, "
    "metin, butonlar, renkler, layout — her detayı yaz. "
    "Bu memo sonraki konuşmalarda kullanılacak. Kısa tutma, detaylı yaz."
)
