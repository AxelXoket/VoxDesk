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


# Visual memo prompt — LLM writes a detailed memo about the screen capture
VISUAL_MEMO_PROMPT = (
    "You are analyzing a screenshot of the user's screen. "
    "Write a detailed memo covering:\n"
    "1. ACTIVE WINDOW: Application name, window title, tab names\n"
    "2. TEXT CONTENT: Read and transcribe any visible text, code, terminal output, error messages verbatim\n"
    "3. UI STATE: Buttons, menus, dialogs, notifications, status bars\n"
    "4. LAYOUT: Panel arrangement, sidebar content, open tabs\n"
    "5. NOTABLE: Errors, warnings, unusual states, progress indicators\n\n"
    "Be EXACT — quote text you can read, name specific files, line numbers, error messages. "
    "This memo replaces the image in conversation history."
)
