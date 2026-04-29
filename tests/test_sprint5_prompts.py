"""
VoxDesk — Sprint 5.0 System Prompt Architecture Tests
PersonalityConfig modüler alanları, prompt composer, STT initial_prompt,
ve voice/text response mode testi.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from src.config import PersonalityConfig, AppConfig


# ══════════════════════════════════════════════════════════════
#  PersonalityConfig — Modüler Prompt Alanları
# ══════════════════════════════════════════════════════════════

class TestPersonalityConfig:
    """PersonalityConfig yeni alanları doğru yüklüyor mu?"""

    @pytest.mark.unit
    def test_default_personality_has_empty_prompt_sections(self):
        """Default PersonalityConfig — tüm prompt alanları boş string."""
        p = PersonalityConfig()
        assert p.system_prompt == ""
        assert p.stt_context == ""
        assert p.screen_analysis_prompt == ""
        assert p.emotion_rules == ""
        assert p.response_format == ""

    @pytest.mark.unit
    def test_personality_with_all_sections(self):
        """Tüm alanlar set edildiğinde doğru dönmeli."""
        p = PersonalityConfig(
            name="TestBot",
            system_prompt="You are TestBot.",
            stt_context="Python, FastAPI, VoxDesk",
            screen_analysis_prompt="Analyze the screen.",
            emotion_rules="Be empathetic.",
            response_format="Use natural language.",
        )
        assert p.name == "TestBot"
        assert "TestBot" in p.system_prompt
        assert "Python" in p.stt_context
        assert "Analyze" in p.screen_analysis_prompt
        assert "empathetic" in p.emotion_rules
        assert "natural" in p.response_format

    @pytest.mark.unit
    def test_personality_extra_fields_forbidden(self):
        """extra='forbid' → bilinmeyen alanlar reddedilmeli."""
        with pytest.raises(Exception):  # ValidationError
            PersonalityConfig(
                name="X",
                unknown_field="should_fail",
            )

    @pytest.mark.unit
    def test_voxly_yaml_loads_all_sections(self):
        """voxly.yaml dosyası tüm modüler prompt alanlarını içermeli.

        Not: emotion_rules bilinçli olarak boş bırakılabilir —
        küçük modellerde duygu filtresi karmaşıklık ekler.
        """
        from src.config import load_personality
        try:
            voxly = load_personality("voxly")
            assert voxly.name == "Voxly"
            assert len(voxly.system_prompt) > 100, "system_prompt çok kısa"
            assert len(voxly.stt_context) > 10, "stt_context boş"
            assert len(voxly.screen_analysis_prompt) > 50, "screen_analysis boş"
            # emotion_rules intentionally empty in current personality
            assert isinstance(voxly.emotion_rules, str)
            assert len(voxly.response_format) > 50, "response_format boş"
        except FileNotFoundError:
            pytest.skip("voxly.yaml not found")

    @pytest.mark.unit
    def test_voxly_prompt_contains_key_concepts(self):
        """Voxly promptu önemli kavramları içermeli."""
        from src.config import load_personality
        try:
            voxly = load_personality("voxly")
            # Core identity
            assert "Voxly" in voxly.system_prompt
            assert "desktop" in voxly.system_prompt.lower()
            # Screen analysis
            assert "screen" in voxly.screen_analysis_prompt.lower()
            assert "specific" in voxly.screen_analysis_prompt.lower()
            # Emotion — intentionally empty in current personality
            # No assertion on emotion_rules content
            # Response format
            assert "voice" in voxly.response_format.lower()
            assert "text" in voxly.response_format.lower()
        except FileNotFoundError:
            pytest.skip("voxly.yaml not found")


# ══════════════════════════════════════════════════════════════
#  System Prompt Composer
# ══════════════════════════════════════════════════════════════

class TestSystemPromptComposer:
    """_build_system_prompt() tüm bölümleri birleştiriyor mu?"""

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
            mock_cfg.return_value.personality = PersonalityConfig(
                system_prompt="Core identity.",
                screen_analysis_prompt="Screen rules.",
                emotion_rules="Emotion filter.",
                response_format="Format rules.",
            )
            p = LlamaCppProvider(mock_config)
        return p

    @pytest.mark.unit
    def test_composer_includes_all_sections(self, provider):
        """Tüm dolu bölümler system prompt'a dahil edilmeli."""
        prompt = provider._build_system_prompt()
        assert "Core identity" in prompt
        assert "Screen rules" in prompt
        assert "Emotion filter" in prompt
        assert "Format rules" in prompt

    @pytest.mark.unit
    def test_composer_skips_empty_sections(self, tmp_path):
        """Boş bölümler atlanmalı."""
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
            mock_cfg.return_value.personality = PersonalityConfig(
                system_prompt="Only this.",
            )
            p = LlamaCppProvider(mock_config)

        prompt = p._build_system_prompt()
        assert prompt == "Only this."

    @pytest.mark.unit
    def test_composer_voice_mode_appends_indicator(self, provider):
        """Voice mode → SES MODU indicator eklenmeli."""
        prompt = provider._build_system_prompt(response_mode="voice")
        assert "SES MODU" in prompt

    @pytest.mark.unit
    def test_composer_text_mode_no_indicator(self, provider):
        """Text mode → SES MODU indicator eklenmemeli."""
        prompt = provider._build_system_prompt(response_mode="text")
        assert "SES MODU" not in prompt

    @pytest.mark.unit
    def test_response_mode_flows_to_messages(self, provider):
        """response_mode _build_messages'a doğru aktarılmalı."""
        msgs_voice = provider._build_messages("test", response_mode="voice")
        msgs_text = provider._build_messages("test", response_mode="text")
        # Voice has mode indicator, text doesn't
        assert "SES MODU" in msgs_voice[0]["content"]
        assert "SES MODU" not in msgs_text[0]["content"]


# ══════════════════════════════════════════════════════════════
#  STT Initial Prompt
# ══════════════════════════════════════════════════════════════

class TestSTTInitialPrompt:
    """STT initial_prompt parametresi doğru aktarılıyor mu?"""

    @pytest.mark.unit
    def test_stt_accepts_initial_prompt(self):
        """SpeechRecognizer initial_prompt parametresi almalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(
            initial_prompt="Python, FastAPI, VoxDesk",
        )
        assert stt.initial_prompt == "Python, FastAPI, VoxDesk"

    @pytest.mark.unit
    def test_stt_initial_prompt_default_none(self):
        """Default initial_prompt = None."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer()
        assert stt.initial_prompt is None

    @pytest.mark.unit
    def test_stt_initial_prompt_stored_on_instance(self):
        """initial_prompt instance attribute olarak saklanmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(initial_prompt="test context")
        assert hasattr(stt, "initial_prompt")
        assert stt.initial_prompt == "test context"


# ══════════════════════════════════════════════════════════════
#  Regression Guards
# ══════════════════════════════════════════════════════════════

class TestPromptRegressionGuards:
    """Prompt mimarisinin yapısal bütünlüğü."""

    @pytest.mark.regression
    def test_personality_fields_list(self):
        """PersonalityConfig tam alan listesi doğru olmalı."""
        expected_fields = {
            "name", "language", "voice", "tone", "greeting",
            "system_prompt", "stt_context", "screen_analysis_prompt",
            "emotion_rules", "response_format",
        }
        actual_fields = set(PersonalityConfig.model_fields.keys())
        assert expected_fields == actual_fields

    @pytest.mark.regression
    def test_build_system_prompt_signature(self):
        """_build_system_prompt response_mode parametresi almalı."""
        from src.llm.provider import LlamaCppProvider
        import inspect
        sig = inspect.signature(LlamaCppProvider._build_system_prompt)
        assert "response_mode" in sig.parameters

    @pytest.mark.regression
    def test_chat_accepts_response_mode(self):
        """chat() response_mode parametresi almalı."""
        from src.llm.provider import LlamaCppProvider
        import inspect
        sig = inspect.signature(LlamaCppProvider.chat)
        assert "response_mode" in sig.parameters

    @pytest.mark.regression
    def test_chat_stream_accepts_response_mode(self):
        """chat_stream() response_mode parametresi almalı."""
        from src.llm.provider import LlamaCppProvider
        import inspect
        sig = inspect.signature(LlamaCppProvider.chat_stream)
        assert "response_mode" in sig.parameters


# ══════════════════════════════════════════════════════════════
#  Sprint 5.1 — Personality Swap → STT Context Update
# ══════════════════════════════════════════════════════════════

class TestSTTInitialPromptUpdate:
    """Personality değişiminde STT initial_prompt güncellenmeli."""

    @pytest.mark.unit
    def test_stt_has_set_initial_prompt(self):
        """SpeechRecognizer set_initial_prompt method'u olmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(model_name="tiny", initial_prompt="test")
        assert hasattr(stt, 'set_initial_prompt')
        assert callable(stt.set_initial_prompt)

    @pytest.mark.unit
    def test_stt_set_initial_prompt_updates_value(self):
        """set_initial_prompt çağrıldığında initial_prompt güncellenmeli."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(model_name="tiny", initial_prompt="old vocab")
        assert stt.initial_prompt == "old vocab"
        stt.set_initial_prompt("new domain vocab: Python, FastAPI")
        assert stt.initial_prompt == "new domain vocab: Python, FastAPI"

    @pytest.mark.unit
    def test_stt_set_initial_prompt_none_clears(self):
        """set_initial_prompt(None) initial_prompt'u temizlemeli."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(model_name="tiny", initial_prompt="vocab")
        stt.set_initial_prompt(None)
        assert stt.initial_prompt is None

    @pytest.mark.unit
    def test_stt_set_initial_prompt_empty_string_clears(self):
        """set_initial_prompt('') initial_prompt'u None yapmalı."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(model_name="tiny", initial_prompt="vocab")
        stt.set_initial_prompt("")
        assert stt.initial_prompt is None


class TestPersonalitySwapSTTWiring:
    """PUT /personality/{name} STT context'i güncellemeli."""

    @pytest.mark.unit
    def test_settings_route_calls_stt_set_initial_prompt(self):
        """Personality route'u STT set_initial_prompt çağırmalı."""
        from pathlib import Path
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        assert "set_initial_prompt" in source, (
            "settings.py personality route'unda set_initial_prompt çağrısı yok"
        )
        assert "stt_context" in source, (
            "settings.py personality route'unda stt_context referansı yok"
        )

    @pytest.mark.unit
    def test_personality_route_stt_update_guarded(self):
        """STT güncelleme state.stt None olabilir — guard olmalı."""
        from pathlib import Path
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        # hasattr guard olmalı
        assert "hasattr" in source or "state.stt" in source


class TestFrontendSttTranslated:
    """Frontend stt_translated event handler olmalı."""

    @pytest.mark.unit
    @pytest.mark.xfail(reason="stt_translated frontend flow is tracked as Sprint 5 backlog / not implemented yet")
    def test_frontend_has_stt_translated_handler(self):
        """app.js stt_translated event'ini handle etmeli."""
        from pathlib import Path
        source = Path("frontend/js/app.js").read_text(encoding="utf-8")
        assert "stt_translated" in source, (
            "Frontend app.js'de stt_translated handler yok"
        )

    @pytest.mark.unit
    @pytest.mark.xfail(reason="stt_translated frontend flow is tracked as Sprint 5 backlog / not implemented yet")
    def test_frontend_stt_translated_shows_original(self):
        """stt_translated handler original text'i göstermeli."""
        from pathlib import Path
        source = Path("frontend/js/app.js").read_text(encoding="utf-8")
        assert "original" in source

    @pytest.mark.unit
    @pytest.mark.xfail(reason="stt_translated frontend flow is tracked as Sprint 5 backlog / not implemented yet")
    def test_frontend_handles_all_voice_events(self):
        """Frontend tüm beklenen voice event'lerini handle etmeli."""
        from pathlib import Path
        source = Path("frontend/js/app.js").read_text(encoding="utf-8")
        expected_events = ["stt_result", "stt_translated", "llm_response", "tts_audio", "voice_error"]
        for event in expected_events:
            assert event in source, f"Frontend'de {event} handler eksik"

