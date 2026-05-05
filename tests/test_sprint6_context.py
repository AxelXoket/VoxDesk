"""
VoxDesk — Sprint 6.1 Tests
Screen context policy unification, API honesty, dead code cleanup.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock


# ══════════════════════════════════════════════════════════════
#  Voice V2 Screen Context Policy
# ══════════════════════════════════════════════════════════════

class TestVoiceV2ScreenContext:
    """voice_v2 must participate in unified screen context policy."""

    @pytest.mark.regression
    def test_voice_v2_no_longer_hardcodes_none(self):
        """voice_v2 must not hardcode image_bytes=None for LLM calls."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        # Old pattern: image_bytes=None in LLM call should be gone
        assert "image_bytes=None" not in source, \
            "voice_v2 still hardcodes image_bytes=None — screen context not unified"

    @pytest.mark.regression
    def test_voice_v2_uses_get_best_frame(self):
        """voice_v2 must use get_best_frame() for frame selection."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        assert "get_best_frame()" in source

    @pytest.mark.regression
    def test_voice_v2_uses_build_artifact_from_frame(self):
        """voice_v2 must use build_artifact_from_frame for image artifact."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        assert "build_artifact_from_frame" in source

    @pytest.mark.regression
    def test_voice_v2_uses_image_artifact_kwarg(self):
        """voice_v2 must send image_artifact= to LLM, not image_bytes=."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        assert "image_artifact=voice_artifact" in source

    @pytest.mark.regression
    def test_voice_v2_docstring_reflects_screen_policy(self):
        """voice_v2 docstring must mention unified screen context, not text-only."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        assert "text-only" not in source.split('"""')[1].lower(), \
            "voice_v2 module docstring still says text-only"

    @pytest.mark.regression
    def test_voice_v2_binary_and_legacy_both_have_screen(self):
        """Both _process_audio_buffer and _handle_legacy_audio must have screen context."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        # Count occurrences of the pattern — should be at least 2 (binary + legacy)
        count = source.count("voice_artifact = None")
        assert count >= 2, \
            f"Expected screen context in both paths, found {count} occurrences"


# ══════════════════════════════════════════════════════════════
#  Chat Routes Use get_best_frame()
# ══════════════════════════════════════════════════════════════

class TestChatFrameSelection:
    """Chat routes must use get_best_frame() not grab_now()."""

    @pytest.mark.regression
    def test_ws_chat_uses_get_best_frame(self):
        """WS chat must use get_best_frame() for screen context."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        ws_chat_section = source[source.find("async def ws_chat"):]
        # Should use get_best_frame, not grab_now for default screen context
        assert "get_best_frame()" in ws_chat_section

    @pytest.mark.regression
    def test_http_chat_uses_get_best_frame(self):
        """HTTP /chat must use get_best_frame() for screen context."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        http_section = source[:source.find("@router.websocket")]
        assert "get_best_frame()" in http_section


# ══════════════════════════════════════════════════════════════
#  grab_now() dxcam-first behavior
# ══════════════════════════════════════════════════════════════

class TestGrabNowDxcamFirst:
    """grab_now() must try dxcam first, then PIL fallback."""

    @pytest.mark.regression
    def test_grab_now_docstring_mentions_dxcam(self):
        """grab_now docstring must mention dxcam-first strategy."""
        source = Path("src/capture.py").read_text(encoding="utf-8")
        grab_section = source[source.find("def grab_now"):]
        docstring = grab_section.split('"""')[1]
        assert "dxcam" in docstring.lower()

    @pytest.mark.regression
    def test_grab_now_checks_camera_before_pil(self):
        """grab_now must check self._camera before falling back to PIL."""
        source = Path("src/capture.py").read_text(encoding="utf-8")
        grab_start = source.find("def grab_now")
        next_def = source.find("\n    def ", grab_start + 10)
        grab_section = source[grab_start:next_def] if next_def > grab_start else source[grab_start:]
        # Find the first non-docstring usage of camera and ImageGrab
        # Skip the docstring section
        doc_end = grab_section.find('"""', grab_section.find('"""') + 3) + 3
        code_section = grab_section[doc_end:]
        camera_pos = code_section.find("self._camera")
        pil_pos = code_section.find("ImageGrab")
        assert camera_pos >= 0, "grab_now must reference self._camera"
        assert pil_pos >= 0, "grab_now must reference ImageGrab as fallback"
        assert camera_pos < pil_pos, \
            "grab_now must check dxcam camera before PIL ImageGrab fallback"

    @pytest.mark.unit
    def test_grab_now_stale_fallback_logged(self):
        """grab_now must log warning when returning stale frame."""
        source = Path("src/capture.py").read_text(encoding="utf-8")
        grab_start = source.find("def grab_now")
        grab_section = source[grab_start:source.find("\n    def ", grab_start + 10)]
        assert "stale" in grab_section.lower()


# ══════════════════════════════════════════════════════════════
#  Frontend — No Manual Attachment Flow
# ══════════════════════════════════════════════════════════════

class TestFrontendScreenContextPolicy:
    """Frontend must not have manual image attachment as primary flow."""

    @pytest.mark.regression
    def test_chat_js_no_attachments_state(self):
        """chat.js must not have this.attachments state."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "this.attachments" not in source, \
            "chat.js still has attachment state — manual flow not removed"

    @pytest.mark.regression
    def test_chat_js_no_file_handling(self):
        """chat.js must not have handleFiles/processImage methods."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "handleFiles" not in source
        assert "processImage" not in source

    @pytest.mark.regression
    def test_chat_js_no_drag_drop(self):
        """chat.js must not have drag-and-drop image handling."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "dragenter" not in source
        assert "dragleave" not in source

    @pytest.mark.regression
    def test_websocket_sendchat_no_attachments(self):
        """websocket.js sendChat must not send attachments parameter."""
        source = Path("frontend/js/websocket.js").read_text(encoding="utf-8")
        send_section = source[source.find("sendChat"):]
        send_body = send_section[:send_section.find("}")]
        assert "attachments" not in send_body

    @pytest.mark.regression
    def test_index_html_no_upload_button(self):
        """index.html must not have upload button."""
        source = Path("frontend/index.html").read_text(encoding="utf-8")
        assert 'id="btnUpload"' not in source
        assert 'id="fileInput"' not in source

    @pytest.mark.regression
    def test_index_html_no_attachment_strip(self):
        """index.html must not have attachment strip."""
        source = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "attachmentStrip" not in source

    @pytest.mark.regression
    def test_index_html_no_drop_overlay(self):
        """index.html must not have drop overlay."""
        source = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "dropOverlay" not in source

    @pytest.mark.regression
    def test_screen_context_toggle_preserved(self):
        """Screen context ON/OFF toggle must still exist."""
        source = Path("frontend/index.html").read_text(encoding="utf-8")
        assert 'id="alwaysOnToggle"' in source


# ══════════════════════════════════════════════════════════════
#  API Honesty
# ══════════════════════════════════════════════════════════════

class TestAPIHonesty:
    """API endpoints must not return fake success."""

    @pytest.mark.regression
    def test_update_model_returns_501(self):
        """PUT /model must return HTTP 501 Not Implemented."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        model_section = source[source.find("async def update_model"):]
        model_body = model_section[:model_section.find("\n@router") if "\n@router" in model_section else len(model_section)]
        assert "501" in model_body
        assert "not_implemented" in model_body

    @pytest.mark.regression
    def test_toggle_va_no_pydantic_bypass(self):
        """toggle_voice_activation must not use object.__setattr__."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        assert "object.__setattr__" not in source, \
            "Pydantic config bypass still present in settings.py"

    @pytest.mark.regression
    def test_toggle_va_uses_app_state(self):
        """toggle_voice_activation must use AppState for runtime state."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        va_section = source[source.find("async def toggle_voice_activation"):]
        va_body = va_section[:va_section.find("\n@router") if "\n@router" in va_section else va_section.find("\nasync def")]
        assert "get_app_state" in va_body


# ══════════════════════════════════════════════════════════════
#  Dead Code Cleanup
# ══════════════════════════════════════════════════════════════

class TestDeadCodeCleanup:
    """Dead code must be removed from provider.py."""

    @pytest.mark.regression
    def test_bg_visual_memo_removed(self):
        """_bg_visual_memo must be removed from provider.py."""
        source = Path("src/llm/provider.py").read_text(encoding="utf-8")
        assert "_bg_visual_memo" not in source

    @pytest.mark.regression
    def test_last_visual_memo_field_removed(self):
        """_last_visual_memo field must be removed from provider.py."""
        source = Path("src/llm/provider.py").read_text(encoding="utf-8")
        assert "_last_visual_memo" not in source

    @pytest.mark.regression
    def test_visual_memo_prompt_import_removed(self):
        """VISUAL_MEMO_PROMPT must not be imported in provider.py."""
        source = Path("src/llm/provider.py").read_text(encoding="utf-8")
        assert "VISUAL_MEMO_PROMPT" not in source

    @pytest.mark.regression
    def test_visual_memo_types_still_exist(self):
        """ChatMessage.visual_memo must still exist (used by history/tests)."""
        from src.llm.types import ChatMessage, VISUAL_MEMO_PROMPT
        msg = ChatMessage(role="user", content="test")
        assert hasattr(msg, "visual_memo")
        assert VISUAL_MEMO_PROMPT  # non-empty string


# ══════════════════════════════════════════════════════════════
#  SecurityConfig Enforcement
# ══════════════════════════════════════════════════════════════

class TestSecurityConfigEnforcement:
    """max_ws_frame_bytes must be read from SecurityConfig."""

    @pytest.mark.regression
    def test_audio_protocol_uses_config(self):
        """audio_protocol must read max_ws_frame_bytes from config."""
        source = Path("src/audio_protocol.py").read_text(encoding="utf-8")
        assert "get_max_frame_bytes" in source
        assert "_get_security_config" in source


# ══════════════════════════════════════════════════════════════
#  Privacy Regression
# ══════════════════════════════════════════════════════════════

class TestPrivacyRegression:
    """Screen context changes must not weaken privacy."""

    @pytest.mark.regression
    def test_no_external_urls_in_voice_v2(self):
        """voice_v2 must not have external URLs."""
        import re
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        url_pattern = re.compile(
            r'(?:https?://|wss?://)'
            r'(?!(?:localhost|127\.0\.0\.1|0\.0\.0\.0))'
            r'[a-zA-Z0-9]'
        )
        matches = url_pattern.findall(source)
        assert not matches, f"External URLs in voice_v2: {matches}"

    @pytest.mark.regression
    def test_screen_context_off_means_no_artifact(self):
        """When include_screen is False, no artifact should be created."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        # HTTP path: "if request.include_screen and state.capture"
        assert "include_screen and state.capture" in source
