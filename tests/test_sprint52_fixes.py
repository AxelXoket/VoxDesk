"""
VoxDesk — Sprint 5.2 Fix Verification Tests
Her fix için targeted regression test — audit triage sonrası kanıtlama.

Kapsamı:
  P1: Path leak, Origin bypass, DNS removal, base64 decode, PCM dtype, pyproject guard
  P2: response_mode, finally block, history visual_memo/trim
  P3: Frontend fixes (statik analiz ile doğrulanabilenler)
  P4: WS connect return check, TTS/VA toggle endpoints
"""

import os
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch


# ══════════════════════════════════════════════════════════════
#  P1: Privacy / Security / Runtime
# ══════════════════════════════════════════════════════════════

class TestP1PathLeak:
    """BUG-034/035: API endpoints must NOT expose filesystem paths."""

    def test_settings_returns_basename_only(self):
        """GET /api/settings model field must be filename, not full path."""
        from src.routes.settings import SettingsResponse
        # Simulate full path config
        with patch("src.routes.settings.get_config") as mock_cfg:
            cfg = MagicMock()
            cfg.llm.model_path = "C:/models/Qwen2.5/qwen-vl-7b-Q8_0.gguf"
            cfg.tts.voice = "af_heart"
            cfg.tts.speed = 1.0
            cfg.tts.enabled = True
            cfg.capture.interval_seconds = 1.0
            cfg.personality.name = "voxly"
            cfg.stt.language = None
            cfg.voice_activation.enabled = False
            cfg.voice_activation.threshold_db = -30.0
            cfg.hotkeys.activate = "ctrl+shift+space"
            cfg.hotkeys.toggle_listen = "ctrl+shift+v"
            cfg.hotkeys.push_to_talk = "ctrl+shift+b"
            cfg.hotkeys.pin_screen = "ctrl+shift+s"
            mock_cfg.return_value = cfg

            import asyncio
            from src.routes.settings import get_settings
            result = asyncio.run(get_settings())
            # Must be basename only — no directory separators
            assert "/" not in result.model
            assert "\\" not in result.model
            assert result.model == "qwen-vl-7b-Q8_0.gguf"

    def test_models_returns_basename_only(self):
        """GET /api/models must not leak directory paths."""
        from src.routes.settings import list_models
        with patch("src.routes.settings.get_config") as mock_cfg, \
             patch("src.main.get_app_state") as mock_state:
            cfg = MagicMock()
            cfg.llm.model_path = "/home/user/models/test-model.gguf"
            cfg.llm.fallback_model_path = "D:\\backup\\fallback.gguf"
            mock_cfg.return_value = cfg
            mock_state.return_value = MagicMock()

            import asyncio
            result = asyncio.run(list_models())
            for model in result["models"]:
                assert "/" not in model["name"], f"Path leaked: {model['name']}"
                assert "\\" not in model["name"], f"Path leaked: {model['name']}"


class TestP1OriginBypass:
    """BUG-013/074: Empty string origin must be rejected."""

    def test_none_origin_allowed(self):
        from src.websocket_manager import check_origin
        assert check_origin(None, ["http://localhost:*"]) is True

    def test_empty_string_origin_rejected(self):
        from src.websocket_manager import check_origin
        assert check_origin("", ["http://localhost:*"]) is False

    def test_valid_origin_allowed(self):
        from src.websocket_manager import check_origin
        assert check_origin("http://localhost:8765", ["http://localhost:*"]) is True

    def test_evil_origin_rejected(self):
        from src.websocket_manager import check_origin
        assert check_origin("http://evil.com", ["http://localhost:*"]) is False


class TestP1IsolationPrivacy:
    """BUG-084: No outbound connections at startup."""

    def test_no_outbound_connection_test(self):
        """verify_isolation must NOT make TCP connections."""
        import src.isolation as iso
        # _test_outbound_connection should not exist anymore
        assert not hasattr(iso, "_test_outbound_connection"), \
            "Outbound connection test function still exists — privacy violation"

    def test_isolation_report_no_internet_blocked_key(self):
        """Report must not contain internet_blocked key."""
        from src.isolation import verify_isolation
        report = verify_isolation()
        assert "internet_blocked" not in report
        assert "env_guards_set" in report
        assert "status" in report


class TestP1Base64Decode:
    """BUG-032: Malformed base64 must not crash WS handler."""

    def test_chat_py_has_base64_try_except(self):
        """chat.py ws_voice handler must wrap b64decode in try/except."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        # Find the audio handling section
        assert "try:" in source
        assert "base64.b64decode" in source
        # Verify there's a try block around the decode
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "b64decode" in line and "audio" in source[max(0, source.find(line)-200):source.find(line)]:
                # Check that a try: exists within 5 lines before
                context = "\n".join(lines[max(0, i-5):i+1])
                assert "try:" in context, "b64decode not protected by try/except"
                break


class TestP1PcmDecode:
    """BUG-069: PCM decode must interpret as int16, not float32."""

    def test_int16_decode_and_normalize(self):
        from src.audio_utils import decode_audio_raw_pcm
        # Int16 max positive = 32767
        data = np.array([32767, -32768, 0], dtype=np.int16)
        result = decode_audio_raw_pcm(data.tobytes())
        assert result is not None
        assert result.dtype == np.float32
        # 32767/32768 ≈ 0.99997
        assert abs(result[0] - 32767/32768.0) < 1e-4
        # -32768/32768 = -1.0
        assert abs(result[1] - (-1.0)) < 1e-4
        # 0/32768 = 0.0
        assert result[2] == 0.0

    def test_empty_pcm_returns_empty_array(self):
        from src.audio_utils import decode_audio_raw_pcm
        result = decode_audio_raw_pcm(b"")
        assert result is not None
        assert len(result) == 0


class TestP1PyprojectGuard:
    """BUG-015/077: Missing pyproject.toml must not crash import."""

    def test_app_version_is_string(self):
        from src.main import APP_VERSION
        assert isinstance(APP_VERSION, str)
        assert len(APP_VERSION) > 0


# ══════════════════════════════════════════════════════════════
#  P2: Voice Pipeline Consistency
# ══════════════════════════════════════════════════════════════

class TestP2VoicePipeline:
    """BUG-001/002: Voice pipeline consistency fixes."""

    def test_legacy_handler_uses_voice_response_mode(self):
        """BUG-001: Legacy voice handler must use response_mode='voice'."""
        source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")
        # Find _handle_legacy_audio function
        legacy_start = source.find("async def _handle_legacy_audio")
        assert legacy_start > 0, "_handle_legacy_audio not found"
        legacy_code = source[legacy_start:]
        # Find the llm.chat call within legacy handler
        chat_call_pos = legacy_code.find("state.llm.chat(")
        assert chat_call_pos > 0
        chat_call_line = legacy_code[chat_call_pos:chat_call_pos+100]
        assert 'response_mode="voice"' in chat_call_line, \
            f"Legacy handler still using wrong response_mode: {chat_call_line}"

    def test_ws_voice_has_finally_block(self):
        """BUG-002: /ws/voice must have finally block for disconnect."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        # Find ws_voice function
        voice_start = source.find("async def ws_voice")
        assert voice_start > 0
        voice_code = source[voice_start:]
        # Must have finally: ... disconnect
        assert "finally:" in voice_code
        finally_pos = voice_code.find("finally:")
        after_finally = voice_code[finally_pos:finally_pos+200]
        assert "disconnect" in after_finally


class TestP2HistoryFixes:
    """BUG-094 + visual_memo: History API fixes."""

    def test_add_user_message_accepts_visual_memo(self):
        from src.llm.history import ConversationHistory
        h = ConversationHistory()
        msg = h.add_user_message("test", visual_memo="VS Code açık")
        assert msg.visual_memo == "VS Code açık"

    def test_export_includes_visual_memo_key(self):
        from src.llm.history import ConversationHistory
        h = ConversationHistory()
        h.add_user_message("test")
        exported = h.export()
        assert "visual_memo" in exported[0]

    def test_auto_trim_no_insert_zero(self):
        """BUG-094: _auto_trim must not use insert(0) — O(n²) fix."""
        source = Path("src/llm/history.py").read_text(encoding="utf-8")
        trim_start = source.find("def _auto_trim")
        trim_code = source[trim_start:source.find("\n    def ", trim_start+1)]
        assert "insert(0" not in trim_code, "O(n²) insert(0) still in _auto_trim"
        assert "kept.append(msg)" in trim_code
        assert "kept.reverse()" in trim_code


# ══════════════════════════════════════════════════════════════
#  P3: Frontend Reliability (Static Analysis)
# ══════════════════════════════════════════════════════════════

class TestP3FrontendFixes:
    """Frontend fixes verified via static source analysis."""

    def test_no_inline_onclick_in_chat_js(self):
        """BUG-018/066: No inline onclick for image lightbox."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "onclick=\"window.VoxChat" not in source, \
            "Inline onclick XSS vector still present"

    def test_lightbox_uses_data_attribute(self):
        """Images must use data-lightbox-index for safe click handling."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "data-lightbox-index" in source

    def test_send_button_disabled_during_streaming(self):
        """BUG-058/090: Send button must be disabled during streaming."""
        source = Path("frontend/js/chat.js").read_text(encoding="utf-8")
        assert "sendBtn.disabled = true" in source
        assert "sendBtn.disabled = false" in source

    def test_audio_play_has_catch(self):
        """BUG-076: audio.play() must have .catch() handler."""
        source = Path("frontend/js/app.js").read_text(encoding="utf-8")
        assert "audio.play().catch" in source

    def test_cached_features_null_guard(self):
        """BUG-019/055: _cachedFeatures null check before use."""
        source = Path("frontend/js/app.js").read_text(encoding="utf-8")
        assert "_cachedFeatures != null" in source or \
               "_cachedFeatures !== null" in source

    def test_btoa_uses_safe_encoder(self):
        """BUG-020/082: MediaRecorder must use arrayBufferToBase64."""
        source = Path("frontend/js/audio-capture.js").read_text(encoding="utf-8")
        assert "arrayBufferToBase64" in source

    def test_tts_toggle_has_change_handler(self):
        """BUG-067: ttsToggle must have change event listener."""
        source = Path("frontend/js/settings.js").read_text(encoding="utf-8")
        assert "ttsToggle" in source
        assert "toggleTts" in source

    def test_va_toggle_has_change_handler(self):
        """BUG-067: vaToggle must have change event listener."""
        source = Path("frontend/js/settings.js").read_text(encoding="utf-8")
        assert "vaToggle" in source
        assert "toggleVoiceActivation" in source


# ══════════════════════════════════════════════════════════════
#  P4: Infrastructure
# ══════════════════════════════════════════════════════════════

class TestP4Infrastructure:
    """WS connect return check, toggle endpoints."""

    def test_all_ws_handlers_check_connect_return(self):
        """BUG-009/010: All WS handlers must check connect() return."""
        chat_source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        voice_source = Path("src/routes/voice_v2.py").read_text(encoding="utf-8")

        # Every ws_manager.connect call must be assigned
        for name, source in [("chat.py", chat_source), ("voice_v2.py", voice_source)]:
            lines = source.split("\n")
            for i, line in enumerate(lines):
                stripped = line.strip()
                if "ws_manager.connect(" in stripped:
                    assert stripped.startswith("connected"), \
                        f"{name}:{i+1} — connect() return not captured: {stripped}"

    def test_tts_toggle_endpoint_exists(self):
        """BUG-067: PUT /tts/toggle endpoint must exist."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        assert "async def toggle_tts" in source
        assert '"/tts/toggle"' in source

    def test_va_toggle_endpoint_exists(self):
        """BUG-067: PUT /voice-activation/toggle endpoint must exist."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        assert "async def toggle_voice_activation" in source
        assert '"/voice-activation/toggle"' in source

    def test_put_model_documented_as_stub(self):
        """BUG-048: PUT /model must be documented as stub."""
        source = Path("src/routes/settings.py").read_text(encoding="utf-8")
        model_pos = source.find("async def update_model")
        assert model_pos > 0
        context = source[model_pos:model_pos+200]
        assert "stub" in context.lower() or "not yet implemented" in context.lower()


# ══════════════════════════════════════════════════════════════
#  Voice+Screen — Now FIXED (Sprint 5.3 P1)
# ══════════════════════════════════════════════════════════════

class TestVoiceScreenFixed:
    """Voice+Screen mode TTS exception handling — Sprint 5.3 P1."""

    def test_ws_voice_tts_exception_now_caught(self):
        """TTS exception must be caught with try/except and send TTS_FAILED."""
        source = Path("src/routes/chat.py").read_text(encoding="utf-8")
        voice_start = source.find("async def ws_voice")
        voice_code = source[voice_start:]
        tts_section_pos = voice_code.find("state.tts.enabled")
        assert tts_section_pos > 0
        tts_section = voice_code[tts_section_pos:tts_section_pos+2000]
        assert "try:" in tts_section, "TTS section must have try block"
        assert "tts_err" in tts_section, "TTS exception variable not found"
        assert "TTS_FAILED" in tts_section, "TTS_FAILED error code not sent"
        assert "record_error" in tts_section, "record_error not called on TTS failure"
        assert "recoverable" in tts_section, "recoverable flag missing"


# ══════════════════════════════════════════════════════════════
#  Sprint 5.3 Specific Fixes
# ══════════════════════════════════════════════════════════════

class TestSprint53ModelLoadRace:
    """P2: Model load race condition — Event-based wait."""

    def test_load_event_exists(self):
        from src.model_state import ManagedModel
        m = ManagedModel.__new__(ManagedModel)
        m.__init__(name="test")
        assert hasattr(m, "_load_event")
        assert m._load_event.is_set()

    def test_concurrent_load_no_deadlock(self):
        """Two threads calling load() must not deadlock."""
        import threading
        from src.model_state import ManagedModel, ModelState

        class SlowModel(ManagedModel):
            def _do_load(self):
                import time; time.sleep(0.1)
                return "model"
            def _do_unload(self): pass

        m = SlowModel(name="slow", min_loaded_seconds=0)
        results = []

        def loader():
            results.append(m.load())

        t1 = threading.Thread(target=loader)
        t2 = threading.Thread(target=loader)
        t1.start()
        import time; time.sleep(0.01)  # Ensure t1 enters LOADING first
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not t1.is_alive(), "Thread 1 deadlocked"
        assert not t2.is_alive(), "Thread 2 deadlocked"
        assert all(r is True for r in results), f"Load results: {results}"
        assert m.state == ModelState.LOADED


class TestSprint53SecurityConfig:
    """P3: SecurityConfig enforcement in audio_protocol."""

    def test_audio_protocol_uses_config_function(self):
        source = Path("src/audio_protocol.py").read_text(encoding="utf-8")
        assert "get_max_frame_bytes()" in source
        assert "def get_max_frame_bytes" in source

    def test_default_frame_limit_matches_config(self):
        from src.config import SecurityConfig
        from src.audio_protocol import get_max_frame_bytes
        default_sec = SecurityConfig()
        assert get_max_frame_bytes() == default_sec.max_ws_frame_bytes


class TestSprint53CaptureProtocol:
    """P4: ScreenCapture health() and close()."""

    def test_capture_has_health(self):
        from src.capture import ScreenCapture
        sc = ScreenCapture()
        h = sc.health()
        assert "running" in h
        assert "buffer_count" in h
        assert "has_camera" in h
        assert h["running"] is False

    def test_capture_has_close(self):
        from src.capture import ScreenCapture
        sc = ScreenCapture()
        sc.close()  # Must not raise
        assert sc.buffer_count == 0

    def test_capture_stop_uses_release(self):
        source = Path("src/capture.py").read_text(encoding="utf-8")
        assert "release()" in source, "camera.release() not called in stop()"


class TestSprint53PttModifier:
    """P6: PTT release modifier fix."""

    def test_ptt_registers_modifier_release_handlers(self):
        source = Path("src/hotkey.py").read_text(encoding="utf-8")
        assert "for mod in modifiers:" in source
        assert "on_release_key" in source


class TestSprint53TrayQuit:
    """P7: Tray quit wiring."""

    def test_tray_quit_callback_set(self):
        source = Path("src/main.py").read_text(encoding="utf-8")
        assert "on_quit=_tray_quit" in source
        assert "SIGINT" in source
