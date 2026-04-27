"""
VoxDesk — LLM Tests (Sprint 4)
ChatMessage, ConversationHistory, LlamaCppProvider.
GPU veya model GEREKMİYOR — tüm çağrılar mock'lanır.
"""

import pytest
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from src.llm.types import ChatMessage, VISUAL_MEMO_PROMPT
from src.llm.history import ConversationHistory


# ══════════════════════════════════════════════════════════════
#  ChatMessage Dataclass
# ══════════════════════════════════════════════════════════════

class TestChatMessage:
    """ChatMessage veri yapısı testleri."""

    def test_basic_creation(self):
        msg = ChatMessage(role="user", content="Merhaba")
        assert msg.role == "user"
        assert msg.content == "Merhaba"
        assert msg.visual_memo is None
        assert msg.timestamp == 0.0

    def test_with_visual_memo(self):
        ts = time.time()
        msg = ChatMessage(
            role="user", content="test",
            visual_memo="Ekranda VS Code açık",
            timestamp=ts,
        )
        assert msg.visual_memo == "Ekranda VS Code açık"
        assert msg.timestamp == ts

    def test_assistant_message(self):
        msg = ChatMessage(role="assistant", content="Cevap")
        assert msg.role == "assistant"

    def test_system_message(self):
        msg = ChatMessage(role="system", content="prompt")
        assert msg.role == "system"

    def test_visual_memo_mutation(self):
        """Visual memo sonradan güncellenebilmeli (bg task için)."""
        msg = ChatMessage(role="user", content="test")
        assert msg.visual_memo is None
        msg.visual_memo = "Yeni memo"
        assert msg.visual_memo == "Yeni memo"


# ══════════════════════════════════════════════════════════════
#  ConversationHistory
# ══════════════════════════════════════════════════════════════

class TestConversationHistory:
    """Provider-agnostic history manager testleri."""

    @pytest.fixture
    def history(self):
        return ConversationHistory(context_limit=5)

    def test_starts_empty(self, history):
        assert len(history) == 0
        assert not history
        assert history.messages == []

    def test_add_user_message(self, history):
        msg = history.add_user_message("Merhaba")
        assert msg.role == "user"
        assert msg.content == "Merhaba"
        assert msg.timestamp > 0
        assert len(history) == 1

    def test_add_assistant_message(self, history):
        msg = history.add_assistant_message("Cevap")
        assert msg.role == "assistant"
        assert msg.content == "Cevap"
        assert len(history) == 1

    def test_add_user_with_memo(self, history):
        msg = history.add_user_message("test", visual_memo="VS Code açık")
        assert msg.visual_memo == "VS Code açık"

    def test_clear(self, history):
        history.add_user_message("x")
        history.add_assistant_message("y")
        assert len(history) == 2
        history.clear()
        assert len(history) == 0

    def test_context_window_within_limit(self, history):
        history.add_user_message("a")
        history.add_assistant_message("b")
        window = history.get_context_window()
        assert len(window) == 2

    def test_context_window_enforces_limit(self, history):
        for i in range(20):
            history.add_user_message(f"msg {i}")
        window = history.get_context_window()
        assert len(window) == 5

    def test_context_window_takes_latest(self, history):
        for i in range(20):
            history.add_user_message(f"msg_{i}")
        window = history.get_context_window()
        assert window[-1].content == "msg_19"
        assert window[0].content == "msg_15"

    def test_export_format(self, history):
        history.add_user_message("test")
        history.messages[0].visual_memo = "memo"
        history.messages[0].timestamp = 123.0
        # We need to directly mutate - but messages returns copy
        # Let's use the internal state
        history._messages[0].visual_memo = "memo"
        history._messages[0].timestamp = 123.0
        exported = history.export()
        assert len(exported) == 1
        assert exported[0]["role"] == "user"
        assert exported[0]["content"] == "test"
        assert exported[0]["visual_memo"] == "memo"
        assert exported[0]["timestamp"] == 123.0

    def test_export_all_keys_present(self, history):
        history.add_assistant_message("cevap")
        exported = history.export()
        required_keys = {"role", "content", "timestamp", "visual_memo"}
        assert set(exported[0].keys()) == required_keys

    def test_messages_returns_copy(self, history):
        """messages property orijinal list'i değiştirmemeli."""
        history.add_user_message("x")
        msgs = history.messages
        msgs.clear()
        assert len(history) == 1  # orijinal değişmemeli

    def test_visual_memo_mutation_on_returned_ref(self, history):
        """add_user_message döndürdüğü referansa memo sonra eklenebilmeli."""
        msg = history.add_user_message("test")
        assert msg.visual_memo is None
        msg.visual_memo = "Ekran notu"
        assert history._messages[0].visual_memo == "Ekran notu"

    def test_bool_truthy_when_has_messages(self, history):
        assert not history
        history.add_user_message("x")
        assert history


# ══════════════════════════════════════════════════════════════
#  LlamaCppProvider — Construction & Validation
# ══════════════════════════════════════════════════════════════

class TestProviderConstruction:
    """Provider __init__ ve path validation testleri."""

    def test_missing_model_path_raises(self):
        """model_path None → FileNotFoundError."""
        from src.llm.provider import LlamaCppProvider
        mock_config = MagicMock()
        mock_config.model_path = None
        mock_config.mmproj_path = None

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            with pytest.raises(FileNotFoundError, match="model_path"):
                LlamaCppProvider(mock_config)

    def test_nonexistent_model_path_raises(self, tmp_path):
        """model_path dosya yok → FileNotFoundError."""
        from src.llm.provider import LlamaCppProvider
        mock_config = MagicMock()
        mock_config.model_path = str(tmp_path / "nonexistent.gguf")
        mock_config.mmproj_path = None

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            with pytest.raises(FileNotFoundError, match="Local model file missing"):
                LlamaCppProvider(mock_config)

    def test_valid_model_path_succeeds(self, tmp_path):
        """Geçerli model_path → başarılı construction."""
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 10

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            provider = LlamaCppProvider(mock_config)
            assert provider.model_name == "test.gguf"
            assert not provider.has_vision
            assert not provider.is_loaded

    def test_valid_model_with_mmproj(self, tmp_path):
        """model + mmproj → vision enabled."""
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "model.gguf"
        fake_mmproj = tmp_path / "mmproj.gguf"
        fake_model.write_bytes(b"GGUF")
        fake_mmproj.write_bytes(b"MMPROJ")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = str(fake_mmproj)
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 10

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            provider = LlamaCppProvider(mock_config)
            assert provider.has_vision

    def test_set_metrics_injection(self, tmp_path):
        """set_metrics post-creation injection çalışmalı."""
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 10

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            provider = LlamaCppProvider(mock_config)
            mock_metrics = MagicMock()
            provider.set_metrics(mock_metrics)
            assert provider._metrics is mock_metrics


# ══════════════════════════════════════════════════════════════
#  LlamaCppProvider — Message Building
# ══════════════════════════════════════════════════════════════

class TestProviderMessageBuilding:
    """_build_messages() OpenAI-compatible format üretiyor mu?"""

    @pytest.fixture
    def provider(self, tmp_path):
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 5

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_personality = MagicMock()
            mock_personality.system_prompt = "You are a helpful AI assistant."
            mock_cfg.return_value.personality = mock_personality
            p = LlamaCppProvider(mock_config)
        return p

    def test_system_prompt_included(self, provider):
        msgs = provider._build_messages("Merhaba")
        assert msgs[0]["role"] == "system"
        assert "helpful" in msgs[0]["content"] or "assistant" in msgs[0]["content"]

    def test_empty_system_prompt_excluded(self, tmp_path):
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 5

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_personality = MagicMock()
            mock_personality.system_prompt = ""
            mock_cfg.return_value.personality = mock_personality
            p = LlamaCppProvider(mock_config)

        msgs = p._build_messages("test")
        assert msgs[0]["role"] == "user"

    def test_user_message_at_end(self, provider):
        msgs = provider._build_messages("test mesaj")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "test mesaj"

    def test_no_image_when_none(self, provider):
        msgs = provider._build_messages("text only")
        assert isinstance(msgs[-1]["content"], str)

    def test_history_included_in_messages(self, provider):
        provider._history.add_user_message("önceki soru")
        provider._history.add_assistant_message("önceki cevap")

        msgs = provider._build_messages("yeni soru")
        # system + 2 history + 1 current = 4
        assert len(msgs) == 4
        assert msgs[1]["content"] == "önceki soru"
        assert msgs[2]["content"] == "önceki cevap"

    def test_visual_memo_prepended_to_content(self, provider):
        msg = provider._history.add_user_message("koduma bak")
        msg.visual_memo = "VS Code'da Python dosyası açık"
        msgs = provider._build_messages("devam")
        assert "[Ekran Notu:" in msgs[1]["content"]
        assert "VS Code" in msgs[1]["content"]
        assert "koduma bak" in msgs[1]["content"]

    def test_context_limit_enforced(self, provider):
        for i in range(20):
            provider._history.add_user_message(f"msg {i}")
        msgs = provider._build_messages("son")
        # system(1) + history(5 limit) + current(1) = 7
        assert len(msgs) == 7

    def test_context_limit_takes_latest(self, provider):
        for i in range(20):
            provider._history.add_user_message(f"msg_{i}")
        msgs = provider._build_messages("query")
        history_contents = [m["content"] for m in msgs[1:-1]]
        assert "msg_19" in history_contents[-1]
        assert "msg_0" not in history_contents[0]


# ══════════════════════════════════════════════════════════════
#  LlamaCppProvider — History Delegation
# ══════════════════════════════════════════════════════════════

class TestProviderHistoryDelegation:
    """Provider'ın history fonksiyonları doğru delege ediyor mu?"""

    @pytest.fixture
    def provider(self, tmp_path):
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 10

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            p = LlamaCppProvider(mock_config)
        return p

    def test_get_history_returns_copy(self, provider):
        provider._history.add_user_message("x")
        h = provider.get_history()
        h.clear()
        assert len(provider._history) == 1

    def test_clear_history(self, provider):
        provider._history.add_user_message("x")
        provider._history.add_assistant_message("y")
        provider.clear_history()
        assert len(provider._history) == 0

    def test_export_history(self, provider):
        provider._history.add_user_message("test")
        exported = provider.export_history()
        assert len(exported) == 1
        assert exported[0]["role"] == "user"

    def test_set_personality(self, provider):
        from src.config import PersonalityConfig
        p = PersonalityConfig(name="NewBot", system_prompt="You are new.")
        provider.set_personality(p)
        assert provider._personality.name == "NewBot"


# ══════════════════════════════════════════════════════════════
#  LlamaCppProvider — Chat (Mocked llama-cpp)
# ══════════════════════════════════════════════════════════════

class TestProviderChatMocked:
    """llama-cpp-python mock'lanarak chat akışı test edilir."""

    @pytest.fixture
    def provider(self, tmp_path):
        from src.llm.provider import LlamaCppProvider
        fake_model = tmp_path / "test.gguf"
        fake_model.write_bytes(b"GGUF")

        mock_config = MagicMock()
        mock_config.model_path = str(fake_model)
        mock_config.mmproj_path = None
        mock_config.n_gpu_layers = -1
        mock_config.n_ctx = 4096
        mock_config.chat_format = None
        mock_config.temperature = 0.7
        mock_config.max_tokens = 2048
        mock_config.context_messages = 10

        with patch("src.llm.provider.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock()
            p = LlamaCppProvider(mock_config)

        # Mock the underlying llama-cpp model
        mock_llm = MagicMock()
        p._llm = mock_llm
        p._loaded = True
        return p

    @pytest.mark.asyncio
    async def test_chat_returns_text(self, provider):
        provider._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "Hello there!"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        result = await provider.chat("Selam")
        assert result == "Hello there!"

    @pytest.mark.asyncio
    async def test_chat_appends_history(self, provider):
        provider._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "Cevap"}}],
            "usage": {},
        }
        await provider.chat("Soru")
        assert len(provider._history) == 2
        assert provider._history._messages[0].content == "Soru"
        assert provider._history._messages[1].content == "Cevap"

    @pytest.mark.asyncio
    async def test_chat_timestamps_set(self, provider):
        provider._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        before = time.time()
        await provider.chat("test")
        after = time.time()
        assert provider._history._messages[0].timestamp >= before
        assert provider._history._messages[0].timestamp <= after

    @pytest.mark.asyncio
    async def test_chat_records_latency(self, provider):
        provider._llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_metrics = MagicMock()
        provider.set_metrics(mock_metrics)
        await provider.chat("test")
        mock_metrics.record_latency.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_error_raises_runtime(self, provider):
        provider._llm.create_chat_completion.side_effect = Exception("GPU OOM")
        with pytest.raises(RuntimeError, match="LLM chat failed"):
            await provider.chat("test")

    @pytest.mark.asyncio
    async def test_chat_error_increments_metric(self, provider):
        provider._llm.create_chat_completion.side_effect = Exception("fail")
        mock_metrics = MagicMock()
        provider.set_metrics(mock_metrics)
        with pytest.raises(RuntimeError):
            await provider.chat("test")
        mock_metrics.increment.assert_called_with("llm_errors_total")
