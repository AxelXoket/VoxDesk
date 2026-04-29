"""
VoxDesk — Sprint 5.3 Part 4b/5 Tests
Gemma4 Handler Fix + Budget Plumbing + Qwen3-VL Readiness + Validation Guards.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import LLMConfig


# ── Handler Resolution Tests ─────────────────────────────────

class TestHandlerResolution:
    """_resolve_handler_name auto-detect and explicit override."""

    def _make_provider(self, model_name: str, **config_overrides):
        """Create a minimal provider mock for handler resolution testing."""
        from src.llm.provider import LlamaCppProvider

        cfg = LLMConfig(**config_overrides)
        provider = object.__new__(LlamaCppProvider)
        provider._config = cfg
        provider._model_path = Path(f"models/{model_name}")
        provider._mmproj_path = Path("models/mmproj.gguf")
        return provider

    # -- Gemma 4 patterns --
    def test_gemma4_e4b(self):
        p = self._make_provider("gemma-4-E4B-it-Q8_0.gguf")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    def test_gemma4_e2b(self):
        p = self._make_provider("gemma-4-E2B-it-Q4_K_M.gguf")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    def test_gemma4_generic(self):
        p = self._make_provider("gemma4-something.gguf")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    def test_gemma4_hyphen(self):
        p = self._make_provider("gemma-4-26b-moe.gguf")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    # -- Gemma 3 patterns --
    def test_gemma3_specific(self):
        p = self._make_provider("gemma-3-12b-it-Q6_K.gguf")
        assert p._resolve_handler_name() == "Gemma3ChatHandler"

    def test_gemma_generic_fallback(self):
        p = self._make_provider("gemma-something.gguf")
        assert p._resolve_handler_name() == "Gemma3ChatHandler"

    # -- Qwen3-VL patterns (Part 5) --
    def test_qwen3_vl_hyphen(self):
        p = self._make_provider("Qwen3-VL-8B-Instruct-Q4_K_M.gguf")
        assert p._resolve_handler_name() == "Qwen3VLChatHandler"

    def test_qwen3vl_no_hyphen(self):
        p = self._make_provider("qwen3vl-8b-instruct.gguf")
        assert p._resolve_handler_name() == "Qwen3VLChatHandler"

    def test_qwen3_vl_underscore(self):
        p = self._make_provider("qwen3_vl_8b.gguf")
        assert p._resolve_handler_name() == "Qwen3VLChatHandler"

    def test_qwen3_generic(self):
        p = self._make_provider("qwen3-something.gguf")
        assert p._resolve_handler_name() == "Qwen3VLChatHandler"

    # -- Qwen2.5-VL patterns (backward compat) --
    def test_qwen25_vl(self):
        p = self._make_provider("Qwen_Qwen2.5-VL-7B-Q8_0.gguf")
        assert p._resolve_handler_name() == "Qwen25VLChatHandler"

    def test_qwen_generic_falls_to_qwen25(self):
        """Generic 'qwen' without version falls to Qwen25VLChatHandler."""
        p = self._make_provider("qwen-some-model.gguf")
        assert p._resolve_handler_name() == "Qwen25VLChatHandler"

    # -- Other handlers --
    def test_minicpm(self):
        p = self._make_provider("MiniCPM-V-2_6-Q4.gguf")
        assert p._resolve_handler_name() == "MiniCPMv26ChatHandler"

    def test_llava(self):
        p = self._make_provider("llava-v1.6-Q5.gguf")
        assert p._resolve_handler_name() == "Llava16ChatHandler"

    def test_unknown_model(self):
        p = self._make_provider("totally-unknown-model.gguf")
        assert p._resolve_handler_name() is None

    # -- Explicit override --
    def test_explicit_override_gemma4(self):
        p = self._make_provider("some-model.gguf", chat_handler="gemma4")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    def test_explicit_override_qwen25vl(self):
        p = self._make_provider("gemma-4-model.gguf", chat_handler="qwen25vl")
        assert p._resolve_handler_name() == "Qwen25VLChatHandler"

    def test_explicit_override_qwen3vl(self):
        p = self._make_provider("some-model.gguf", chat_handler="qwen3vl")
        assert p._resolve_handler_name() == "Qwen3VLChatHandler"

    def test_explicit_auto_falls_through_to_pattern(self):
        p = self._make_provider("gemma-4-E4B.gguf", chat_handler="auto")
        assert p._resolve_handler_name() == "Gemma4ChatHandler"

    def test_invalid_explicit_override(self):
        p = self._make_provider("model.gguf", chat_handler="invalid_handler")
        assert p._resolve_handler_name() is None


# ── Budget Plumbing Tests ─────────────────────────────────────

class TestBudgetPlumbing:
    """_apply_vision_budget preset resolution and n_ubatch guard."""

    def _make_provider(self, preset=None, n_ubatch=None):
        from src.llm.provider import LlamaCppProvider
        cfg = LLMConfig(vision_budget_preset=preset, n_ubatch=n_ubatch)
        provider = object.__new__(LlamaCppProvider)
        provider._config = cfg
        return provider

    def test_null_preset_no_injection(self):
        p = self._make_provider(preset=None)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert "image_min_tokens" not in kwargs
        assert "image_max_tokens" not in kwargs

    def test_screen_fast(self):
        p = self._make_provider(preset="screen_fast", n_ubatch=2048)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert kwargs["image_min_tokens"] == 280
        assert kwargs["image_max_tokens"] == 280

    def test_screen_balanced(self):
        p = self._make_provider(preset="screen_balanced", n_ubatch=2048)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert kwargs["image_min_tokens"] == 560
        assert kwargs["image_max_tokens"] == 560

    def test_screen_ocr(self):
        p = self._make_provider(preset="screen_ocr", n_ubatch=2048)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert kwargs["image_min_tokens"] == 1120
        assert kwargs["image_max_tokens"] == 1120

    def test_budget_non_gemma4_handler_rejected(self):
        p = self._make_provider(preset="screen_ocr", n_ubatch=2048)
        kwargs = {}
        p._apply_vision_budget("Qwen25VLChatHandler", kwargs)
        assert "image_min_tokens" not in kwargs  # Not applied

    def test_budget_missing_n_ubatch_rejected(self):
        p = self._make_provider(preset="screen_ocr", n_ubatch=None)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert "image_min_tokens" not in kwargs  # Not applied — crash guard

    def test_budget_insufficient_n_ubatch_rejected(self):
        p = self._make_provider(preset="screen_ocr", n_ubatch=512)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert "image_min_tokens" not in kwargs  # 512 < 1120

    def test_budget_sufficient_n_ubatch_accepted(self):
        p = self._make_provider(preset="screen_ocr", n_ubatch=1120)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert kwargs["image_min_tokens"] == 1120  # Exactly equal — accepted

    def test_invalid_preset_rejected(self):
        p = self._make_provider(preset="invalid_preset", n_ubatch=2048)
        kwargs = {}
        p._apply_vision_budget("Gemma4ChatHandler", kwargs)
        assert "image_min_tokens" not in kwargs


# ── Config Backward Compatibility Tests ───────────────────────

class TestConfigBackwardCompat:

    def test_default_values(self):
        cfg = LLMConfig()
        assert cfg.chat_handler == "auto"
        assert cfg.enable_thinking is False
        assert cfg.vision_budget_preset is None
        assert cfg.n_ubatch is None

    def test_old_config_still_works(self):
        """Config without new fields should work fine."""
        cfg = LLMConfig(provider="llama-cpp", n_gpu_layers=-1, n_ctx=8192)
        assert cfg.chat_handler == "auto"
        assert cfg.vision_budget_preset is None

    def test_explicit_budget_config(self):
        cfg = LLMConfig(
            vision_budget_preset="screen_balanced",
            n_ubatch=2048,
            chat_handler="gemma4",
            enable_thinking=True,
        )
        assert cfg.vision_budget_preset == "screen_balanced"
        assert cfg.n_ubatch == 2048
        assert cfg.chat_handler == "gemma4"
        assert cfg.enable_thinking is True

    def test_qwen3vl_config(self):
        cfg = LLMConfig(chat_handler="qwen3vl")
        assert cfg.chat_handler == "qwen3vl"


# ── n_ubatch Config Tests ─────────────────────────────────────

class TestNUbatchConfig:

    def test_n_ubatch_null_default(self):
        cfg = LLMConfig()
        assert cfg.n_ubatch is None

    def test_n_ubatch_explicit(self):
        cfg = LLMConfig(n_ubatch=2048)
        assert cfg.n_ubatch == 2048


# ── Version Helper Test ───────────────────────────────────────

class TestVersionHelper:

    def test_get_version(self):
        from src.llm.provider import LlamaCppProvider
        ver = LlamaCppProvider._get_llama_cpp_version()
        # Should return a string, never crash
        assert isinstance(ver, str)


# ── Existing System Guard Tests ───────────────────────────────

class TestExistingSystemGuards:

    def test_history_still_text_only(self):
        from src.llm.history import ConversationHistory
        h = ConversationHistory()
        h.add_user_message("describe my screen")
        h.add_assistant_message("I see an IDE")
        for msg in h.export():
            assert "base64" not in msg["content"].lower()

    def test_debug_export_default_off(self):
        from src.config import FeaturesConfig
        assert FeaturesConfig().enable_debug_capture_export is False

    def test_capture_quality_parity_preserved(self):
        from src.config import CaptureConfig
        cfg = CaptureConfig(
            resize_width=1280, jpeg_quality=85,
            inference_resize_width=1920, inference_jpeg_quality=92,
        )
        assert cfg.effective_inference_resize_width == 1920
        assert cfg.effective_inference_jpeg_quality == 92
        assert cfg.effective_preview_resize_width == 1280
        assert cfg.effective_preview_jpeg_quality == 85
