"""
VoxDesk — LLM Client Tests
Message building, history management, visual memo, streaming, fallback.
Ollama sunucusu GEREKMİYOR — tüm çağrılar mock'lanır.
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.llm_client import VisionLLM, ChatMessage, VISUAL_MEMO_PROMPT


# ── Shared fixture ───────────────────────────────────────────

def _make_llm(**overrides):
    """Mock config ile VisionLLM oluştur."""
    defaults = {
        "model": "test-model",
        "temperature": 0.7,
        "max_tokens": 1024,
        "context_messages": 5,
        "fallback_models": [],
        "system_prompt": "You are a helpful AI assistant.",
        "personality_name": "voxly",
    }
    defaults.update(overrides)

    with patch("src.llm_client.get_config") as mock_cfg:
        cfg = MagicMock()
        cfg.llm.model = defaults["model"]
        cfg.llm.temperature = defaults["temperature"]
        cfg.llm.max_tokens = defaults["max_tokens"]
        cfg.llm.context_messages = defaults["context_messages"]
        cfg.llm.fallback_models = defaults["fallback_models"]
        cfg.personality.system_prompt = defaults["system_prompt"]
        cfg.personality.name = defaults["personality_name"]
        mock_cfg.return_value = cfg
        return VisionLLM()


# ── ChatMessage Dataclass ────────────────────────────────────

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


# ── VisionLLM — Message Building ─────────────────────────────

class TestMessageBuilding:
    """_build_messages() doğru Ollama formatı üretiyor mu?"""

    @pytest.fixture
    def llm(self):
        return _make_llm()

    def test_system_prompt_included(self, llm):
        msgs = llm._build_messages("Merhaba")
        assert msgs[0]["role"] == "system"
        assert "helpful" in msgs[0]["content"] or "assistant" in msgs[0]["content"]

    def test_empty_system_prompt_excluded(self):
        """Boş system prompt → system mesajı eklenmemeli."""
        llm = _make_llm(system_prompt="")
        msgs = llm._build_messages("test")
        # System mesajı olmamalı — doğrudan user mesajı
        assert msgs[0]["role"] == "user"

    def test_user_message_at_end(self, llm):
        msgs = llm._build_messages("test mesaj")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "test mesaj"

    def test_image_attached_to_current_message(self, llm):
        fake_img = b"\xff\xd8\xff\xe0" * 10
        msgs = llm._build_messages("ekrana bak", image_bytes=fake_img)
        assert "images" in msgs[-1]
        assert len(msgs[-1]["images"]) == 1
        # Base64 encoded string olmalı
        import base64
        decoded = base64.b64decode(msgs[-1]["images"][0])
        assert decoded == fake_img

    def test_no_image_when_none(self, llm):
        msgs = llm._build_messages("text only")
        assert "images" not in msgs[-1]

    def test_history_included_in_messages(self, llm):
        llm._history.append(ChatMessage(role="user", content="önceki soru"))
        llm._history.append(ChatMessage(role="assistant", content="önceki cevap"))

        msgs = llm._build_messages("yeni soru")
        # system + 2 history + 1 current = 4
        assert len(msgs) == 4
        assert msgs[1]["content"] == "önceki soru"
        assert msgs[2]["content"] == "önceki cevap"

    def test_visual_memo_prepended_to_content(self, llm):
        llm._history.append(ChatMessage(
            role="user", content="koduma bak",
            visual_memo="VS Code'da Python dosyası açık",
        ))
        msgs = llm._build_messages("devam")
        assert "[Ekran Notu:" in msgs[1]["content"]
        assert "VS Code" in msgs[1]["content"]
        # Orijinal content da korunmalı
        assert "koduma bak" in msgs[1]["content"]

    def test_history_images_not_in_messages(self, llm):
        """Geçmiş mesajlarda image olmamalı — sadece memo."""
        llm._history.append(ChatMessage(
            role="user", content="eski", visual_memo="memo var",
        ))
        msgs = llm._build_messages("yeni")
        # History mesajında images key'i olmamalı
        assert "images" not in msgs[1]

    def test_context_limit_enforced(self, llm):
        """context_messages limiti aşılmamalı."""
        for i in range(20):
            llm._history.append(ChatMessage(role="user", content=f"msg {i}"))
        msgs = llm._build_messages("son")
        # system(1) + history(5 limit) + current(1) = 7
        assert len(msgs) == 7

    def test_context_limit_takes_latest(self, llm):
        """Context limiti en SON mesajları almalı."""
        for i in range(20):
            llm._history.append(ChatMessage(role="user", content=f"msg_{i}"))
        msgs = llm._build_messages("query")
        # History'deki son 5 mesaj: msg_15..msg_19
        history_contents = [m["content"] for m in msgs[1:-1]]  # system ve current hariç
        assert "msg_19" in history_contents[-1]
        assert "msg_0" not in history_contents[0]


# ── VisionLLM — History Management ───────────────────────────

class TestHistoryManagement:
    """Konuşma geçmişi CRUD operasyonları."""

    @pytest.fixture
    def llm(self):
        return _make_llm(context_messages=10, system_prompt="")

    def test_history_starts_empty(self, llm):
        assert len(llm.get_history()) == 0

    def test_clear_history(self, llm):
        llm._history.append(ChatMessage(role="user", content="x"))
        llm._history.append(ChatMessage(role="assistant", content="y"))
        assert len(llm._history) == 2
        llm.clear_history()
        assert len(llm._history) == 0

    def test_export_history_format(self, llm):
        llm._history.append(ChatMessage(
            role="user", content="test",
            visual_memo="memo", timestamp=123.0,
        ))
        exported = llm.export_history()
        assert len(exported) == 1
        assert exported[0]["role"] == "user"
        assert exported[0]["content"] == "test"
        assert exported[0]["visual_memo"] == "memo"
        assert exported[0]["timestamp"] == 123.0

    def test_export_history_all_keys_present(self, llm):
        """Export edilen her dict'te 4 key olmalı."""
        llm._history.append(ChatMessage(role="assistant", content="cevap"))
        exported = llm.export_history()
        required_keys = {"role", "content", "timestamp", "visual_memo"}
        assert set(exported[0].keys()) == required_keys

    def test_get_history_returns_copy(self, llm):
        """get_history() orijinal list'i değiştirmemeli."""
        llm._history.append(ChatMessage(role="user", content="x"))
        h = llm.get_history()
        h.clear()
        assert len(llm._history) == 1  # orijinal değişmemeli

    def test_set_model(self, llm):
        llm.set_model("new-model")
        assert llm.model == "new-model"

    def test_set_personality(self, llm):
        from src.config import PersonalityConfig
        p = PersonalityConfig(name="NewBot", system_prompt="You are new.")
        llm.set_personality(p)
        assert llm.personality.name == "NewBot"
        assert llm.personality.system_prompt == "You are new."


# ── VisionLLM — Chat (Mocked Ollama) ─────────────────────────

class TestChatMocked:
    """Ollama mock'lanarak chat akışı test edilir."""

    @pytest.fixture
    def llm(self):
        return _make_llm(
            fallback_models=["fallback-model"],
            system_prompt="Sen test bot'sun.",
            personality_name="TestBot",
        )

    @pytest.mark.asyncio
    async def test_chat_returns_text(self, llm):
        mock_response = MagicMock()
        mock_response.message.content = "Hello there!"
        llm._async_client.chat = AsyncMock(return_value=mock_response)

        result = await llm.chat("Selam")
        assert result == "Hello there!"

    @pytest.mark.asyncio
    async def test_chat_appends_history(self, llm):
        mock_response = MagicMock()
        mock_response.message.content = "Cevap"
        llm._async_client.chat = AsyncMock(return_value=mock_response)

        await llm.chat("Soru")
        assert len(llm._history) == 2
        assert llm._history[0].role == "user"
        assert llm._history[0].content == "Soru"
        assert llm._history[1].role == "assistant"
        assert llm._history[1].content == "Cevap"

    @pytest.mark.asyncio
    async def test_chat_timestamps_set(self, llm):
        """History'deki mesajlar timestamp içermeli."""
        mock_response = MagicMock()
        mock_response.message.content = "ok"
        llm._async_client.chat = AsyncMock(return_value=mock_response)

        before = time.time()
        await llm.chat("test")
        after = time.time()

        assert llm._history[0].timestamp >= before
        assert llm._history[0].timestamp <= after

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_chat_with_image_triggers_memo_task(self, llm):
        """Image'lı chat → asyncio.create_task çağrılmalı."""
        mock_response = MagicMock()
        mock_response.message.content = "Ekranı gördüm"
        llm._async_client.chat = AsyncMock(return_value=mock_response)

        with patch("src.llm_client.asyncio.create_task") as mock_task:
            await llm.chat("ekrana bak", image_bytes=b"fake_jpeg")
            mock_task.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_chat_without_image_no_memo_task(self, llm):
        """Image'sız chat → create_task çağrılmamalı."""
        mock_response = MagicMock()
        mock_response.message.content = "ok"
        llm._async_client.chat = AsyncMock(return_value=mock_response)

        with patch("src.llm_client.asyncio.create_task") as mock_task:
            await llm.chat("text only")
            mock_task.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_chat_fallback_on_error(self, llm):
        """Primary model hata verince fallback denenmeli."""
        fallback_response = MagicMock()
        fallback_response.message.content = "Fallback cevap"

        call_count = 0
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Model yüklenemedi")
            return fallback_response

        llm._async_client.chat = AsyncMock(side_effect=side_effect)
        result = await llm.chat("test")
        assert result == "Fallback cevap"

    @pytest.mark.asyncio
    async def test_chat_all_fallbacks_fail(self):
        """Tüm modeller başarısız → hata mesajı döndürmeli."""
        llm = _make_llm(fallback_models=["fb1", "fb2"])
        llm._async_client.chat = AsyncMock(side_effect=Exception("fail"))

        result = await llm.chat("test")
        assert "Hata" in result

    @pytest.mark.asyncio
    async def test_list_models_returns_list(self, llm):
        mock_models = MagicMock()
        mock_model = MagicMock()
        mock_model.model = "test:latest"
        mock_model.size = 4000000000
        mock_model.modified_at = None
        mock_models.models = [mock_model]
        llm._async_client.list = AsyncMock(return_value=mock_models)

        models = await llm.list_models()
        assert len(models) == 1
        assert models[0]["name"] == "test:latest"
        assert models[0]["size"] == 4000000000
        assert models[0]["modified_at"] is None

    @pytest.mark.asyncio
    async def test_list_models_error_returns_empty(self, llm):
        llm._async_client.list = AsyncMock(side_effect=Exception("connection"))
        models = await llm.list_models()
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_multiple(self, llm):
        """Birden fazla model varsa hepsi dönmeli."""
        mock_models = MagicMock()
        m1, m2 = MagicMock(), MagicMock()
        m1.model, m1.size, m1.modified_at = "model-a", 1e9, None
        m2.model, m2.size, m2.modified_at = "model-b", 2e9, None
        mock_models.models = [m1, m2]
        llm._async_client.list = AsyncMock(return_value=mock_models)

        models = await llm.list_models()
        assert len(models) == 2


# ── VisionLLM — Streaming Chat (Mocked) ──────────────────────

class TestChatStreamMocked:
    """Streaming chat async generator testi."""

    @pytest.fixture
    def llm(self):
        return _make_llm(context_messages=10)

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self, llm):
        """Streaming chat token'ları doğru yield etmeli."""
        chunks = []
        for word in ["Mer", "ha", "ba", "!"]:
            chunk = MagicMock()
            chunk.message.content = word
            chunks.append(chunk)

        async def mock_stream():
            for c in chunks:
                yield c

        llm._async_client.chat = AsyncMock(return_value=mock_stream())

        tokens = []
        async for token in llm.chat_stream("Selam"):
            tokens.append(token)

        assert tokens == ["Mer", "ha", "ba", "!"]

    @pytest.mark.asyncio
    async def test_stream_appends_history(self, llm):
        """Streaming bittikten sonra history'ye eklenmeli."""
        chunks = []
        for word in ["Ce", "vap"]:
            chunk = MagicMock()
            chunk.message.content = word
            chunks.append(chunk)

        async def mock_stream():
            for c in chunks:
                yield c

        llm._async_client.chat = AsyncMock(return_value=mock_stream())

        async for _ in llm.chat_stream("Soru"):
            pass

        assert len(llm._history) == 2
        assert llm._history[0].content == "Soru"
        assert llm._history[1].content == "Cevap"

    @pytest.mark.asyncio
    async def test_stream_error_yields_error_message(self, llm):
        """Streaming hatası → hata mesajı yield etmeli."""
        llm._async_client.chat = AsyncMock(side_effect=Exception("timeout"))

        tokens = []
        async for token in llm.chat_stream("test"):
            tokens.append(token)

        assert len(tokens) == 1
        assert "Hata" in tokens[0]
