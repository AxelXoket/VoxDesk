"""
VoxDesk - Clearance Stage Blocker Fix Tests
Tests for F-01, F-07, F-03, F-11 from the verified clearance audit.
"""

import pytest
import re
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


# ══════════════════════════════════════════════════════════════
#  F-01: POST /api/chat must respect screen_context_enabled
# ══════════════════════════════════════════════════════════════

class TestF01ScreenContextGuard:
    """POST /api/chat must not send screen context when screen_context_enabled=False."""

    @pytest.mark.unit
    def test_post_chat_source_has_screen_context_guard(self):
        """chat() function must check screen_context_enabled before get_best_frame()."""
        chat_py = Path(__file__).parent.parent / "src" / "routes" / "chat.py"
        content = chat_py.read_text(encoding="utf-8")
        # Find the POST /api/chat handler (async def chat)
        chat_fn_start = content.index("async def chat(request: ChatRequest)")
        rest = content[chat_fn_start:]
        next_fn = rest.find("\nasync def ", 1)
        if next_fn > 0:
            chat_section = rest[:next_fn]
        else:
            chat_section = rest
        assert "screen_context_enabled" in chat_section, (
            "POST /api/chat does NOT check screen_context_enabled - PRIVACY GAP"
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_chat_disabled_screen_sends_no_image(self):
        """When screen_context_enabled=False, POST /api/chat must not create image artifact."""
        from src.main import AppState
        from src.routes.chat import chat, ChatRequest

        state = AppState()
        state.screen_context_enabled = False
        state.llm = AsyncMock()
        state.llm.chat = AsyncMock(return_value="test response")
        state.llm.model_name = "test-model"
        state.capture = MagicMock()
        state.capture.get_best_frame = MagicMock(return_value=MagicMock())

        request = ChatRequest(message="hello", include_screen=True)

        with patch("src.main.get_app_state", return_value=state):
            response = await chat(request)

        # LLM must be called with image_artifact=None
        state.llm.chat.assert_called_once()
        call_kwargs = state.llm.chat.call_args
        actual_artifact = call_kwargs.kwargs.get("image_artifact")
        assert actual_artifact is None, (
            "POST /api/chat sent image_artifact despite screen_context_enabled=False"
        )
        assert response.has_image is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_post_chat_enabled_screen_allows_image(self):
        """When screen_context_enabled=True, POST /api/chat should create image artifact."""
        from src.main import AppState
        from src.routes.chat import chat, ChatRequest

        state = AppState()
        state.screen_context_enabled = True
        state.llm = AsyncMock()
        state.llm.chat = AsyncMock(return_value="test response")
        state.llm.model_name = "test-model"

        fake_frame = MagicMock()
        fake_frame.image_bytes = b"\xff\xd8\xff\xe0" * 10
        state.capture = MagicMock()
        state.capture.get_best_frame = MagicMock(return_value=fake_frame)

        fake_artifact = MagicMock()

        request = ChatRequest(message="hello", include_screen=True)

        with patch("src.main.get_app_state", return_value=state), \
             patch("src.image_artifact.build_artifact_from_frame", return_value=fake_artifact):
            response = await chat(request)

        # LLM must be called with an image_artifact
        state.llm.chat.assert_called_once()
        call_kwargs = state.llm.chat.call_args
        actual_artifact = call_kwargs.kwargs.get("image_artifact")
        assert actual_artifact is not None, (
            "POST /api/chat did not send image_artifact when screen_context_enabled=True"
        )
        assert response.has_image is True


# ══════════════════════════════════════════════════════════════
#  F-07: History export must not leak absolute filesystem path
# ══════════════════════════════════════════════════════════════

class TestF07HistoryPathLeak:
    """POST /api/history/export must return safe filename, not absolute path."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_export_response_not_absolute_path(self, tmp_path):
        """Export response 'file' field must not be an absolute path."""
        from src.routes.history import export_history

        mock_state = MagicMock()
        mock_state.llm = MagicMock()
        mock_state.llm.export_history = MagicMock(return_value=[
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ])

        mock_config = MagicMock()
        mock_config.history.save_path = str(tmp_path)

        with patch("src.main.get_app_state", return_value=mock_state), \
             patch("src.config.get_config", return_value=mock_config):
            result = await export_history()

        assert result["status"] == "ok"
        file_value = result["file"]
        # Must not be absolute
        assert not Path(file_value).is_absolute(), (
            f"Export response leaks absolute path: {file_value}"
        )
        # Must not contain drive letter patterns
        assert not re.match(r"^[A-Za-z]:\\", file_value), (
            f"Export response contains drive letter: {file_value}"
        )
        # Must not contain user profile path fragments
        assert "Users" not in file_value and "home" not in file_value, (
            f"Export response contains user path: {file_value}"
        )
        # Must still have a useful filename
        assert "voxdesk_history_" in file_value
        assert file_value.endswith(".json")


# ══════════════════════════════════════════════════════════════
#  F-03: Model select must not silently fail on 501
# ══════════════════════════════════════════════════════════════

class TestF03ModelSelectFeedback:
    """Frontend model selector must not silently swallow 501 errors."""

    @pytest.mark.unit
    def test_updatemodel_checks_response_status(self):
        """settings.js updateModel must check response.ok or response.status."""
        settings_js = Path(__file__).parent.parent / "frontend" / "js" / "settings.js"
        content = settings_js.read_text(encoding="utf-8")
        # Find the updateModel function
        fn_start = content.index("async updateModel()")
        fn_section = content[fn_start:fn_start + 800]
        # Must check response status - not just silently catch
        assert ("res.ok" in fn_section or "res.status" in fn_section or
                "response.ok" in fn_section or "response.status" in fn_section), (
            "updateModel() does not check response status - silently swallows 501"
        )

    @pytest.mark.unit
    def test_updatemodel_has_user_feedback(self):
        """settings.js updateModel must show user-visible feedback on failure."""
        settings_js = Path(__file__).parent.parent / "frontend" / "js" / "settings.js"
        content = settings_js.read_text(encoding="utf-8")
        fn_start = content.index("async updateModel()")
        fn_section = content[fn_start:fn_start + 800]
        # Must have a user-visible feedback mechanism
        assert ("alert(" in fn_section or "showNotification" in fn_section or
                "textContent" in fn_section or "innerText" in fn_section or
                "classList" in fn_section or "showError" in fn_section), (
            "updateModel() does not show user feedback on failure"
        )

    @pytest.mark.unit
    def test_updatemodel_reverts_on_failure(self):
        """settings.js updateModel must revert selector value on failure."""
        settings_js = Path(__file__).parent.parent / "frontend" / "js" / "settings.js"
        content = settings_js.read_text(encoding="utf-8")
        fn_start = content.index("async updateModel()")
        fn_section = content[fn_start:fn_start + 800]
        assert "previousModel" in fn_section or "modelSelect.value =" in fn_section, (
            "updateModel() does not revert selector on failure"
        )


# ══════════════════════════════════════════════════════════════
#  F-11: Sidecar health must not stay stale after process crash
# ══════════════════════════════════════════════════════════════

class TestF11SidecarStaleHealth:
    """Sidecar is_healthy must reflect current process state."""

    @pytest.mark.unit
    def test_is_healthy_false_when_process_dead(self):
        """is_healthy must be False when _healthy=True but process has exited."""
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig

        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="fake.exe",
            model_path="fake.gguf",
        )
        mgr = SidecarManager(cfg)

        # Simulate: startup succeeded, then process died
        mgr._healthy = True
        mgr._process = MagicMock()
        mgr._process.poll.return_value = 1  # process exited with code 1

        assert mgr.is_healthy is False, (
            "is_healthy is True despite process being dead - stale health"
        )

    @pytest.mark.unit
    def test_is_healthy_true_when_process_running(self):
        """is_healthy must be True when _healthy=True and process is running."""
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig

        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="fake.exe",
            model_path="fake.gguf",
        )
        mgr = SidecarManager(cfg)

        mgr._healthy = True
        mgr._process = MagicMock()
        mgr._process.poll.return_value = None  # process still running

        assert mgr.is_healthy is True

    @pytest.mark.unit
    def test_is_healthy_true_when_no_process_reuse_mode(self):
        """is_healthy can be True with no _process (reusing existing server on port)."""
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig

        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="fake.exe",
            model_path="fake.gguf",
        )
        mgr = SidecarManager(cfg)

        # Simulate: start() found existing server, no subprocess spawned
        mgr._healthy = True
        mgr._process = None

        assert mgr.is_healthy is True, (
            "is_healthy should be True in reuse mode (no process, healthy flag set)"
        )

    @pytest.mark.unit
    def test_is_healthy_false_when_not_started(self):
        """is_healthy must be False when sidecar was never started."""
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig

        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="fake.exe",
            model_path="fake.gguf",
        )
        mgr = SidecarManager(cfg)
        assert mgr.is_healthy is False
