"""
VoxDesk — Sprint 7 Voice UX Tests
Full Voice Mode, read-aloud endpoint, AudioWorklet RMS, silence detection.
Baseline : 623 passed, 3 xfailed → yeni testler eklenir, mevcut kırılmaz.
"""

import re
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Paths ─────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
FRONTEND = ROOT / "frontend"
FRONTEND_JS = FRONTEND / "js"
FRONTEND_CSS = FRONTEND / "css"


# ═══════════════════════════════════════════════════════════════
#  FAZ 1 — Backend : /api/tts/read endpoint + feature flag
# ═══════════════════════════════════════════════════════════════

class TestTTSReadEndpoint:
    """POST /api/tts/read route and validation tests."""

    @pytest.mark.unit
    def test_tts_read_endpoint_exists(self):
        """Route /api/tts/read should be registered in chat.py."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert '"/tts/read"' in content or "'/tts/read'" in content

    @pytest.mark.unit
    def test_tts_read_model_class_exists(self):
        """TTSReadRequest model should be defined."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "TTSReadRequest" in content

    @pytest.mark.unit
    def test_tts_read_validates_empty_text(self):
        """Endpoint should check for empty text → 400."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "empty_text" in content

    @pytest.mark.unit
    def test_tts_read_validates_oversized_text(self):
        """Endpoint should check for oversized text → 400."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "text_too_long" in content

    @pytest.mark.unit
    def test_tts_read_returns_503_when_unavailable(self):
        """Endpoint should return 503 when TTS is disabled/None."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "tts_unavailable" in content

    @pytest.mark.unit
    def test_tts_read_no_global_mutation(self):
        """Endpoint should not mutate global TTS state (no set_voice, no config write)."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        # Find the tts_read function body
        start = content.find("async def tts_read")
        assert start > 0, "tts_read function not found"
        # Get the function body (up to next def or end)
        body_end = content.find("\ndef ", start + 10)
        if body_end == -1:
            body_end = content.find("\n@router", start + 10)
        if body_end == -1:
            body_end = len(content)
        body = content[start:body_end]
        assert "set_voice" not in body, "tts_read should not call set_voice"
        assert "config.tts" not in body, "tts_read should not access config.tts"

    @pytest.mark.unit
    def test_tts_read_returns_wav_content_type(self):
        """Endpoint should return audio/wav content type."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "audio/wav" in content


class TestFeatureFlag:
    """enable_full_voice_mode feature flag tests."""

    @pytest.mark.unit
    def test_enable_full_voice_mode_in_features_config(self):
        """FeaturesConfig should have enable_full_voice_mode field."""
        from src.config import FeaturesConfig
        config = FeaturesConfig()
        assert hasattr(config, "enable_full_voice_mode")
        assert config.enable_full_voice_mode is True

    @pytest.mark.unit
    def test_enable_full_voice_mode_in_default_yaml(self):
        """default.yaml should have enable_full_voice_mode: true."""
        yaml_file = ROOT / "config" / "default.yaml"
        content = yaml_file.read_text(encoding="utf-8")
        assert "enable_full_voice_mode" in content


# ═══════════════════════════════════════════════════════════════
#  FAZ 2 — AudioWorklet RMS
# ═══════════════════════════════════════════════════════════════

class TestAudioWorkletRMS:
    """AudioWorklet RMS level feature tests."""

    @pytest.mark.unit
    def test_audio_processor_sends_rms_level(self):
        """audio-processor.js should send rms_level messages."""
        processor_file = FRONTEND_JS / "audio-processor.js"
        content = processor_file.read_text(encoding="utf-8")
        assert "rms_level" in content
        assert "sumSquares" in content or "rmsAccum" in content

    @pytest.mark.unit
    def test_audio_processor_rms_report_interval(self):
        """audio-processor.js should report every N frames (not every frame)."""
        processor_file = FRONTEND_JS / "audio-processor.js"
        content = processor_file.read_text(encoding="utf-8")
        assert "RMS_REPORT_INTERVAL" in content

    @pytest.mark.unit
    def test_audio_capture_has_on_level_update(self):
        """audio-capture.js should have onLevelUpdate callback."""
        capture_file = FRONTEND_JS / "audio-capture.js"
        content = capture_file.read_text(encoding="utf-8")
        assert "onLevelUpdate" in content


# ═══════════════════════════════════════════════════════════════
#  FAZ 3 — Full Voice Mode JS
# ═══════════════════════════════════════════════════════════════

class TestFullVoiceModeJS:
    """full-voice-mode.js state machine and features."""

    @pytest.mark.unit
    def test_full_voice_mode_js_exists(self):
        """full-voice-mode.js file should exist."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        assert fvm_file.exists(), f"Missing: {fvm_file}"

    @pytest.mark.unit
    def test_fvm_has_all_7_states(self):
        """FVM should define all 7 state constants."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        expected_states = [
            "idle", "listening", "user_speaking",
            "silence_countdown", "processing",
            "ai_speaking", "error",
        ]
        for state in expected_states:
            assert state in content, f"Missing state: {state}"

    @pytest.mark.unit
    def test_silence_rms_constant_defined(self):
        """SILENCE_RMS_THRESHOLD should be defined in FVM."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "SILENCE_RMS_THRESHOLD" in content or "FVM_SILENCE_RMS_THRESHOLD" in content

    @pytest.mark.unit
    def test_silence_duration_constant_defined(self):
        """SILENCE_DURATION_MS should be 3000ms."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "3000" in content
        assert "SILENCE_DURATION_MS" in content or "FVM_SILENCE_DURATION_MS" in content

    @pytest.mark.unit
    def test_fvm_has_spoke_yet_guard(self):
        """FVM should have hasSpokeYet guard to prevent false turn closes."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "hasSpokeYet" in content or "_hasSpokeYet" in content

    @pytest.mark.unit
    def test_fvm_beep_function(self):
        """FVM should have a beep function for turn-end signal."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "playBeep" in content or "_playBeep" in content

    @pytest.mark.unit
    def test_fvm_no_external_urls(self):
        """FVM JS should not contain external URLs."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        url_pattern = re.compile(
            r'(?:https?://|wss?://)'
            r'(?!(?:localhost|127\.0\.0\.1|0\.0\.0\.0))'
            r'[a-zA-Z0-9]'
        )
        violations = []
        for i, line in enumerate(content.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            if url_pattern.search(line):
                violations.append(f"full-voice-mode.js:{i}: {line.strip()[:80]}")
        assert not violations, \
            "FVM contains external URLs:\n" + \
            "\n".join(f"  - {v}" for v in violations)


# ═══════════════════════════════════════════════════════════════
#  FAZ 4 — HTML + CSS
# ═══════════════════════════════════════════════════════════════

class TestHTMLStructure:
    """HTML structure for FVM overlay and toggles."""

    @pytest.mark.unit
    def test_fvm_overlay_in_html(self):
        """FVM overlay div should exist in index.html."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="fvmOverlay"' in content

    @pytest.mark.unit
    def test_fvm_overlay_in_html(self):
        """FVM overlay should exist in index.html (sidebar toggle removed in 7.2b)."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="fvmOverlay"' in content

    @pytest.mark.unit
    def test_fvm_script_tag_in_html(self):
        """full-voice-mode.js script tag should be in index.html."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert "full-voice-mode.js" in content


class TestPreservedElements:
    """Sprint 6.1 elements must still be present."""

    @pytest.mark.regression
    def test_dictation_mic_btn_preserved(self):
        """Normal dictation mic button should still exist."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="btnMic"' in content

    @pytest.mark.regression
    def test_normal_chat_input_preserved(self):
        """Chat text input should still exist."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="chatInput"' in content

    @pytest.mark.regression
    def test_screen_context_toggle_preserved(self):
        """Screen context toggle should still exist."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="alwaysOnToggle"' in content

    @pytest.mark.regression
    def test_voice_indicator_preserved(self):
        """Legacy voice indicator should still exist."""
        html_file = FRONTEND / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="voiceIndicator"' in content


# ═══════════════════════════════════════════════════════════════
#  FAZ 5 — Chat Read-Aloud + App.js Integration
# ═══════════════════════════════════════════════════════════════

class TestReadAloudButton:
    """Read-aloud button in chat messages."""

    @pytest.mark.unit
    def test_read_aloud_btn_in_chat_js(self):
        """chat.js should create read-aloud-btn for assistant messages."""
        chat_file = FRONTEND_JS / "chat.js"
        content = chat_file.read_text(encoding="utf-8")
        assert "read-aloud-btn" in content

    @pytest.mark.unit
    def test_read_aloud_dispatches_event(self):
        """chat.js should dispatch 'readAloud' custom event."""
        chat_file = FRONTEND_JS / "chat.js"
        content = chat_file.read_text(encoding="utf-8")
        assert "readAloud" in content
        assert "CustomEvent" in content


class TestAppJSIntegration:
    """app.js FVM integration tests."""

    @pytest.mark.unit
    def test_active_audio_ref_in_app_js(self):
        """app.js should have activeAudio global reference."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "activeAudio" in content

    @pytest.mark.unit
    def test_fvm_voice_message_guard(self):
        """app.js should guard voice:message handler when FVM is active."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        # Should check if FVM is active and return early
        assert "voxFullVoice" in content or "VoxFullVoice" in content
        assert "isActive" in content

    @pytest.mark.unit
    def test_play_audio_from_base64_exposed(self):
        """app.js should expose playAudioFromBase64 globally for FVM."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "playAudioFromBase64" in content

    @pytest.mark.unit
    def test_read_aloud_fetch_handler(self):
        """app.js should have readAloud event listener that fetches /api/tts/read."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "readAloud" in content
        assert "/api/tts/read" in content


# ═══════════════════════════════════════════════════════════════
#  Screen Context Policy Guard (Sprint 6.1 Regression)
# ═══════════════════════════════════════════════════════════════

class TestScreenContextPolicy:
    """Screen context should NOT be affected by Sprint 7 changes."""

    @pytest.mark.regression
    def test_voice_v2_uses_get_best_frame(self):
        """voice_v2.py should still use get_best_frame() for screen context."""
        voice_file = SRC / "routes" / "voice_v2.py"
        content = voice_file.read_text(encoding="utf-8")
        assert "get_best_frame" in content

    @pytest.mark.regression
    def test_chat_uses_get_best_frame(self):
        """chat.py should still use get_best_frame() for screen context."""
        chat_file = SRC / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        assert "get_best_frame" in content

    @pytest.mark.regression
    def test_no_manual_screenshot_flow_in_chat_js(self):
        """chat.js should not have manual file upload/attachment mechanisms."""
        chat_file = FRONTEND_JS / "chat.js"
        content = chat_file.read_text(encoding="utf-8")
        # No drag-drop or file input (Sprint 6.1 removal)
        assert "dragover" not in content
        assert 'type="file"' not in content


# ═══════════════════════════════════════════════════════════════
#  Sprint 7.1 — Stabilization Tests
# ═══════════════════════════════════════════════════════════════

class TestSprint71Stabilization:
    """Sprint 7.1 regression guards for the four confirmed fixes."""

    # ── Fix 1 : micBtn FVM guard ─────────────────────────────

    @pytest.mark.regression
    def test_mic_btn_guard_when_fvm_active(self):
        """app.js micBtn handler must check FVM isActive and return early."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        # Guard must appear inside or before the micBtn click handler
        mic_handler_start = content.find("micBtn.addEventListener")
        assert mic_handler_start > 0, "micBtn listener not found"
        # Check FVM guard is present in handler body
        handler_block = content[mic_handler_start : mic_handler_start + 400]
        assert "voxFullVoice" in handler_block or "VoxFullVoice" in handler_block, \
            "FVM guard missing from micBtn click handler"
        assert "isActive" in handler_block, \
            "isActive check missing from micBtn click handler"

    @pytest.mark.regression
    def test_mic_btn_guard_returns_early(self):
        """app.js micBtn guard must explicitly return when FVM is active."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        mic_handler_start = content.find("micBtn.addEventListener")
        handler_block = content[mic_handler_start : mic_handler_start + 400]
        # 'return;' must appear inside the FVM guard block
        assert "return;" in handler_block or "return\n" in handler_block, \
            "micBtn FVM guard does not return early"

    # ── Fix 2 : FVM deactivate flushes queues ────────────────

    @pytest.mark.regression
    def test_fvm_deactivate_clears_fvm_tts_queue(self):
        """full-voice-mode.js deactivate() should clear window._fvmTtsQueue."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        # Search for the method definition ('deactivate() {'), not call sites
        deactivate_start = content.find("deactivate() {")
        assert deactivate_start > 0, "deactivate() method not found"
        deactivate_body = content[deactivate_start : deactivate_start + 1000]
        assert "_fvmTtsQueue" in deactivate_body, \
            "deactivate() does not clear _fvmTtsQueue"
        assert "_fvmTtsPlaying" in deactivate_body, \
            "deactivate() does not reset _fvmTtsPlaying"

    @pytest.mark.regression
    def test_fvm_deactivate_calls_vox_stop_audio(self):
        """full-voice-mode.js deactivate() should call window.voxStopAudio."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        deactivate_start = content.find("deactivate() {")
        deactivate_body = content[deactivate_start : deactivate_start + 1000]
        assert "voxStopAudio" in deactivate_body, \
            "deactivate() does not call voxStopAudio"

    # ── Fix 3 : voxStopAudio stale-callback prevention ───────

    @pytest.mark.regression
    def test_vox_stop_audio_helper_exists(self):
        """app.js should define voxStopAudio helper function."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "function voxStopAudio" in content, \
            "voxStopAudio helper not defined"

    @pytest.mark.regression
    def test_vox_stop_audio_nullifies_onended(self):
        """voxStopAudio must set audio.onended = null before pausing."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        stop_start = content.find("function voxStopAudio")
        assert stop_start > 0
        stop_body = content[stop_start : stop_start + 300]
        assert "onended = null" in stop_body, \
            "voxStopAudio does not nullify onended before pause"
        assert ".pause()" in stop_body, \
            "voxStopAudio does not call .pause()"

    @pytest.mark.regression
    def test_vox_stop_audio_exposed_globally(self):
        """window.voxStopAudio must be exposed so FVM can call it."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "window.voxStopAudio" in content, \
            "voxStopAudio not exposed on window"

    @pytest.mark.regression
    def test_reset_tts_playback_helper_exists(self):
        """app.js should define resetTtsPlayback helper function."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        assert "function resetTtsPlayback" in content, \
            "resetTtsPlayback helper not defined"

    @pytest.mark.regression
    def test_play_audio_uses_vox_stop_audio(self):
        """playAudio() should call voxStopAudio() instead of inline pause."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        play_start = content.find("function playAudio(")
        assert play_start > 0
        play_body = content[play_start : play_start + 500]
        assert "voxStopAudio()" in play_body, \
            "playAudio() does not call voxStopAudio()"

    @pytest.mark.regression
    def test_read_aloud_uses_vox_stop_audio(self):
        """readAloud handler should call voxStopAudio() before starting new audio."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        # Search the entire file — voxStopAudio() is called inside the handler
        assert "voxStopAudio()" in content, \
            "app.js does not contain any voxStopAudio() call"
        # Confirm it appears after the readAloud event registration
        read_aloud_pos = content.find("'readAloud'")
        if read_aloud_pos == -1:
            read_aloud_pos = content.find('"readAloud"')
        assert read_aloud_pos > 0, "readAloud listener not found"
        stop_pos = content.find("voxStopAudio()", read_aloud_pos)
        assert stop_pos > 0, \
            "voxStopAudio() not called after readAloud event registration"

    # ── Fix 4 : pyproject.toml version alignment ─────────────

    @pytest.mark.regression
    def test_pyproject_version_is_0_7_2(self):
        """pyproject.toml must declare version 0.7.2 to match docs/architecture.md."""
        pyproject = ROOT / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert 'version = "0.7.2"' in content, \
            f"pyproject.toml version mismatch: expected '0.7.2'"

    @pytest.mark.regression
    def test_architecture_docs_version_matches_pyproject(self):
        """architecture.md version header should match pyproject.toml version."""
        pyproject = ROOT / "pyproject.toml"
        arch_file = ROOT / "docs" / "architecture.md"
        # Extract version from pyproject
        pyversion = None
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("version ="):
                pyversion = line.split('"')[1]
                break
        assert pyversion is not None, "Could not parse version from pyproject.toml"
        arch_content = arch_file.read_text(encoding="utf-8")
        assert f"v{pyversion}" in arch_content, \
            f"architecture.md does not reference v{pyversion}"


# ═══════════════════════════════════════════════════════════
#  Sprint 7.2: Stabilization Regression Tests
# ═══════════════════════════════════════════════════════════

class TestSprint72Stabilization:
    """Sprint 7.2 regression tests: FVM stuck state, prompt policy, Gemma4 default."""

    # ── A: FVM processing timeout ────────────────────────────

    @pytest.mark.regression
    def test_fvm_processing_timeout_constant_exists(self):
        """full-voice-mode.js must define FVM_PROCESSING_TIMEOUT_MS."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "FVM_PROCESSING_TIMEOUT_MS" in content

    @pytest.mark.regression
    def test_fvm_llm_tts_grace_constant_exists(self):
        """full-voice-mode.js must define FVM_LLM_TTS_GRACE_MS."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        assert "FVM_LLM_TTS_GRACE_MS" in content

    @pytest.mark.regression
    def test_fvm_close_turn_starts_processing_timer(self):
        """_closeTurn must start a processing timeout."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        close_turn_start = content.find("_closeTurn() {")
        assert close_turn_start > 0, "_closeTurn() method not found"
        close_turn_body = content[close_turn_start:close_turn_start + 800]
        assert "FVM_PROCESSING_TIMEOUT_MS" in close_turn_body, \
            "_closeTurn() does not start processing timeout"

    @pytest.mark.regression
    def test_fvm_llm_response_starts_grace_timer(self):
        """handleVoiceMessage should start grace timer on llm_response."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        llm_pos = content.find("'llm_response'")
        assert llm_pos > 0
        handler_body = content[llm_pos:llm_pos + 600]
        assert "FVM_LLM_TTS_GRACE_MS" in handler_body, \
            "handleVoiceMessage does not set grace timer after llm_response"

    @pytest.mark.regression
    def test_fvm_tts_audio_clears_timers(self):
        """handleVoiceMessage should clear processing+grace timers on tts_audio."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        tts_pos = content.find("'tts_audio'")
        assert tts_pos > 0
        tts_body = content[tts_pos:tts_pos + 300]
        assert "_clearProcessingTimer" in tts_body
        assert "_clearLlmTtsGraceTimer" in tts_body

    @pytest.mark.regression
    def test_fvm_deactivate_clears_processing_timer(self):
        """deactivate() should clear processing + grace timers via _clearTimers."""
        fvm_file = FRONTEND_JS / "full-voice-mode.js"
        content = fvm_file.read_text(encoding="utf-8")
        # _clearTimers calls _clearProcessingTimer and _clearLlmTtsGraceTimer
        clear_timers_start = content.find("_clearTimers() {")
        assert clear_timers_start > 0
        clear_timers_body = content[clear_timers_start:clear_timers_start + 300]
        assert "_clearProcessingTimer" in clear_timers_body
        assert "_clearLlmTtsGraceTimer" in clear_timers_body

    # ── B: Read-aloud user feedback ──────────────────────────

    @pytest.mark.regression
    def test_read_aloud_shows_tts_unavailable_message(self):
        """readAloud handler should show user message on 503."""
        app_file = FRONTEND_JS / "app.js"
        content = app_file.read_text(encoding="utf-8")
        read_aloud_pos = content.find("'readAloud'")
        if read_aloud_pos == -1:
            read_aloud_pos = content.find('"readAloud"')
        assert read_aloud_pos > 0
        handler = content[read_aloud_pos:read_aloud_pos + 1200]
        assert "503" in handler, "readAloud handler does not check for 503 status"

    # ── D: Prompt policy ─────────────────────────────────────

    @pytest.mark.regression
    def test_prompt_policy_screen_use_caveat(self):
        """voxly.yaml system_prompt must instruct model not to describe screen unprompted."""
        voxly = ROOT / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8")
        assert "Do NOT describe or reference the screen unless" in content, \
            "voxly.yaml missing screen-use policy caveat"

    @pytest.mark.regression
    def test_prompt_policy_screen_accuracy_rule(self):
        """voxly.yaml must keep screen accuracy rule."""
        voxly = ROOT / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8")
        assert "SCREEN ACCURACY" in content

    # ── E: Gemma4 default config ─────────────────────────────

    @pytest.mark.regression
    def test_default_config_uses_gemma4(self):
        """config/default.yaml primary model_path must point to gemma-4."""
        config_file = ROOT / "config" / "default.yaml"
        content = config_file.read_text(encoding="utf-8")
        # Find first model_path line
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("model_path:") and "fallback" not in line:
                assert "gemma" in stripped.lower(), \
                    f"Default model is not Gemma4: {stripped}"
                break
        else:
            pytest.fail("No model_path found in default.yaml")

    @pytest.mark.regression
    def test_default_config_gemma4_file_exists(self):
        """Gemma4 GGUF file referenced in default.yaml must exist."""
        import yaml
        config_file = ROOT / "config" / "default.yaml"
        cfg = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        model_path = ROOT / cfg["llm"]["model_path"]
        assert model_path.exists(), f"Gemma4 GGUF missing: {model_path}"

    # ── F: Version alignment ─────────────────────────────────

    @pytest.mark.regression
    def test_pyproject_version_is_0_7_2_sprint72(self):
        """pyproject.toml must be 0.7.2."""
        pyproject = ROOT / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert 'version = "0.7.2"' in content


# ═══════════════════════════════════════════════════════════
#  Sprint 7.2b: State Truthfulness Regression Tests
# ═══════════════════════════════════════════════════════════

class TestSprint72bStateTruthfulness:
    """Screen toggle, voice toggle cleanup, label fixes, Gemma4 limitation."""

    # ── Screen capture toggle — backend ────────────────────

    @pytest.mark.regression
    def test_screen_toggle_endpoint_exists(self):
        """settings.py must define PUT /api/screen/toggle."""
        settings_file = ROOT / "src" / "routes" / "settings.py"
        content = settings_file.read_text(encoding="utf-8")
        assert "/screen/toggle" in content

    @pytest.mark.regression
    def test_chat_ws_honors_screen_flag(self):
        """ws_chat must check screen_context_enabled before including screen."""
        chat_file = ROOT / "src" / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        # Sprint 8.1: migrated from ad-hoc _screen_context_enabled to declared field
        assert "screen_context_enabled" in content

    @pytest.mark.regression
    def test_voice_v2_honors_screen_flag(self):
        """voice_v2.py must check screen_context_enabled before including screen."""
        voice_file = ROOT / "src" / "routes" / "voice_v2.py"
        content = voice_file.read_text(encoding="utf-8")
        # Sprint 8.1: migrated from ad-hoc _screen_context_enabled to declared field
        assert "screen_context_enabled" in content

    @pytest.mark.regression
    def test_screen_ws_honors_flag(self):
        """ws_screen must check screen_context_enabled before sending frames."""
        chat_file = ROOT / "src" / "routes" / "chat.py"
        content = chat_file.read_text(encoding="utf-8")
        ws_screen_pos = content.find("ws_screen")
        assert ws_screen_pos > 0
        ws_screen_body = content[ws_screen_pos:ws_screen_pos + 800]
        # Sprint 8.1: migrated from ad-hoc _screen_context_enabled to declared field
        assert "screen_context_enabled" in ws_screen_body

    @pytest.mark.regression
    def test_screen_preview_honors_flag(self):
        """screen-preview.js must check voxScreenEnabled."""
        preview_file = FRONTEND_JS / "screen-preview.js"
        content = preview_file.read_text(encoding="utf-8")
        assert "voxScreenEnabled" in content

    @pytest.mark.regression
    def test_chat_js_calls_screen_toggle_api(self):
        """chat.js must call /api/screen/toggle on toggle change."""
        chat_file = FRONTEND_JS / "chat.js"
        content = chat_file.read_text(encoding="utf-8")
        assert "/api/screen/toggle" in content

    # ── HTML label and toggle cleanup ──────────────────────

    @pytest.mark.regression
    def test_html_label_is_ekran_yakalama(self):
        """index.html must use 'Ekran Yakalama', not 'Ekran Capture'."""
        html_file = ROOT / "frontend" / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert "Ekran Yakalama" in content
        assert "Ekran Capture" not in content

    @pytest.mark.regression
    def test_voice_activation_toggle_removed(self):
        """index.html must NOT contain vaToggle."""
        html_file = ROOT / "frontend" / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="vaToggle"' not in content

    @pytest.mark.regression
    def test_voice_activation_label_removed(self):
        """index.html must NOT contain 'Voice Activation' label."""
        html_file = ROOT / "frontend" / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert "Voice Activation" not in content

    @pytest.mark.regression
    def test_sidebar_fvm_toggle_removed(self):
        """index.html must NOT contain fullVoiceToggle in settings panel."""
        html_file = ROOT / "frontend" / "index.html"
        content = html_file.read_text(encoding="utf-8")
        assert 'id="fullVoiceToggle"' not in content

    @pytest.mark.regression
    def test_settings_js_no_va_toggle_ref(self):
        """settings.js must not reference vaToggle element."""
        settings_file = FRONTEND_JS / "settings.js"
        content = settings_file.read_text(encoding="utf-8")
        assert "vaToggle" not in content

    # ── Gemma4 vision limitation documented ────────────────

    @pytest.mark.regression
    def test_gemma4_vision_limitation_documented(self):
        """dependency_matrix.md must document Gemma4 vision limitation."""
        dep_file = ROOT / "docs" / "dependency_matrix.md"
        content = dep_file.read_text(encoding="utf-8")
        assert "Gemma4 Vision Limitation" in content

    # ── Prompt policy still intact ─────────────────────────

    @pytest.mark.regression
    def test_prompt_policy_screen_use_caveat_72b(self):
        """voxly.yaml must still have screen-use policy."""
        voxly = ROOT / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8")
        assert "Do NOT describe or reference the screen unless" in content
