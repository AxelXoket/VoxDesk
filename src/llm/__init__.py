"""
VoxDesk — LLM Package
Local-only inference via llama-cpp-python.

Usage:
    from src.llm import LlamaCppProvider, ChatMessage
"""

from src.llm.provider import LlamaCppProvider
from src.llm.types import ChatMessage

__all__ = ["LlamaCppProvider", "ChatMessage"]
