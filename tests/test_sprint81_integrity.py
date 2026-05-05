"""
VoxDesk — Sprint 8.1 Integrity Tests
Tests for all audit-driven fixes: privacy, state truthfulness, dependencies, docs.
"""

import pytest
import time
import re
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch, PropertyMock
from dataclasses import fields as dataclass_fields

# ══════════════════════════════════════════════════════════════
#  Goal 2: AppState declared fields
# ══════════════════════════════════════════════════════════════

class TestAppStateDeclaredFields:
    """C-01 fix: screen_context_enabled and voice_activation_enabled are declared fields."""

    @pytest.mark.unit
    def test_screen_context_enabled_is_declared_field(self):
        from src.main import AppState
        field_names = [f.name for f in dataclass_fields(AppState)]
        assert "screen_context_enabled" in field_names

    @pytest.mark.unit
    def test_voice_activation_enabled_is_declared_field(self):
        from src.main import AppState
        field_names = [f.name for f in dataclass_fields(AppState)]
        assert "voice_activation_enabled" in field_names

    @pytest.mark.unit
    def test_screen_context_enabled_defaults_true(self):
        from src.main import AppState
        state = AppState()
        assert state.screen_context_enabled is True

    @pytest.mark.unit
    def test_voice_activation_enabled_defaults_true(self):
        from src.main import AppState
        state = AppState()
        assert state.voice_activation_enabled is True

    @pytest.mark.unit
    def test_screen_context_field_is_mutable(self):
        from src.main import AppState
        state = AppState()
        state.screen_context_enabled = False
        assert state.screen_context_enabled is False
        state.screen_context_enabled = True
        assert state.screen_context_enabled is True

    @pytest.mark.unit
    def test_no_adhoc_screen_context_attribute(self):
        """Verify no code uses the old _screen_context_enabled pattern."""
        src_dir = Path(__file__).parent.parent / "src"
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            assert "_screen_context_enabled" not in content, (
                f"Old ad-hoc _screen_context_enabled found in {py_file.name}"
            )

    @pytest.mark.unit
    def test_no_adhoc_voice_activation_attribute(self):
        """Verify no code uses the old _voice_activation_enabled pattern."""
        src_dir = Path(__file__).parent.parent / "src"
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            assert "_voice_activation_enabled" not in content, (
                f"Old ad-hoc _voice_activation_enabled found in {py_file.name}"
            )


# ══════════════════════════════════════════════════════════════
#  Goal 1+3: Screen context enforcement in ALL routes
# ══════════════════════════════════════════════════════════════

class TestScreenContextEnforcement:
    """C-02 fix: All voice/chat routes respect screen_context_enabled."""

    @pytest.mark.regression
    def test_ws_voice_legacy_checks_screen_context(self):
        """Legacy /ws/voice must check screen_context_enabled before creating artifact."""
        chat_py = Path(__file__).parent.parent / "src" / "routes" / "chat.py"
        content = chat_py.read_text(encoding="utf-8")
        # Find the ws_voice function and verify it checks screen_context_enabled
        voice_section = content[content.index("async def ws_voice("):]
        assert "screen_context_enabled" in voice_section, (
            "Legacy /ws/voice does NOT check screen_context_enabled — PRIVACY GAP"
        )

    @pytest.mark.regression
    def test_ws_chat_checks_screen_context(self):
        """WS chat must check screen_context_enabled."""
        chat_py = Path(__file__).parent.parent / "src" / "routes" / "chat.py"
        content = chat_py.read_text(encoding="utf-8")
        chat_section = content[content.index("async def ws_chat("):]
        chat_section = chat_section[:chat_section.index("async def ws_screen(")]
        assert "screen_context_enabled" in chat_section

    @pytest.mark.regression
    def test_voice_v2_process_checks_screen_context(self):
        """voice_v2 _process_audio_buffer must check screen_context_enabled."""
        v2_py = Path(__file__).parent.parent / "src" / "routes" / "voice_v2.py"
        content = v2_py.read_text(encoding="utf-8")
        proc_section = content[content.index("async def _process_audio_buffer("):]
        proc_section = proc_section[:proc_section.index("# ── Legacy")]
        assert "screen_context_enabled" in proc_section

    @pytest.mark.regression
    def test_voice_v2_legacy_checks_screen_context(self):
        """voice_v2 _handle_legacy_audio must check screen_context_enabled."""
        v2_py = Path(__file__).parent.parent / "src" / "routes" / "voice_v2.py"
        content = v2_py.read_text(encoding="utf-8")
        legacy_section = content[content.index("async def _handle_legacy_audio("):]
        assert "screen_context_enabled" in legacy_section

    @pytest.mark.regression
    def test_all_four_paths_use_declared_field(self):
        """All 4 voice/chat paths must use state.screen_context_enabled, not getattr."""
        src_dir = Path(__file__).parent.parent / "src" / "routes"
        for route_file in ["chat.py", "voice_v2.py"]:
            content = (src_dir / route_file).read_text(encoding="utf-8")
            # Must NOT contain old getattr pattern
            assert "getattr(state, '_screen_context_enabled'" not in content, (
                f"Old getattr pattern still in {route_file}"
            )


# ══════════════════════════════════════════════════════════════
#  Goal 2 continued: Settings toggle uses declared fields
# ══════════════════════════════════════════════════════════════

class TestSettingsToggleDeclaredFields:
    """Settings routes must mutate declared AppState fields."""

    @pytest.mark.regression
    def test_screen_toggle_uses_declared_field(self):
        settings_py = Path(__file__).parent.parent / "src" / "routes" / "settings.py"
        content = settings_py.read_text(encoding="utf-8")
        toggle_section = content[content.index("async def toggle_screen_context("):]
        toggle_section = toggle_section[:toggle_section.index("async def get_screen_status(")]
        assert "state.screen_context_enabled" in toggle_section
        assert "setattr" not in toggle_section
        assert "getattr" not in toggle_section

    @pytest.mark.regression
    def test_voice_activation_toggle_uses_declared_field(self):
        settings_py = Path(__file__).parent.parent / "src" / "routes" / "settings.py"
        content = settings_py.read_text(encoding="utf-8")
        toggle_section = content[content.index("async def toggle_voice_activation("):]
        toggle_section = toggle_section[:toggle_section.index("@router.put")]
        assert "state.voice_activation_enabled" in toggle_section
        assert "setattr" not in toggle_section
        assert "getattr" not in toggle_section

    @pytest.mark.regression
    def test_screen_status_uses_declared_field(self):
        settings_py = Path(__file__).parent.parent / "src" / "routes" / "settings.py"
        content = settings_py.read_text(encoding="utf-8")
        status_section = content[content.index("async def get_screen_status("):]
        assert "state.screen_context_enabled" in status_section
        assert "getattr" not in status_section


# ══════════════════════════════════════════════════════════════
#  Goal 2: /api/status reads declared field
# ══════════════════════════════════════════════════════════════

class TestStatusReportsDeclaredField:

    @pytest.mark.regression
    def test_runtime_status_uses_declared_field(self):
        main_py = Path(__file__).parent.parent / "src" / "main.py"
        content = main_py.read_text(encoding="utf-8")
        status_section = content[content.index("async def runtime_status("):]
        assert "state.screen_context_enabled" in status_section
        assert "getattr(state, '_screen_context_enabled'" not in status_section


# ══════════════════════════════════════════════════════════════
#  Goal 4: httpx dependency declared
# ══════════════════════════════════════════════════════════════

class TestHttpxDependency:

    @pytest.mark.regression
    def test_httpx_in_requirements_txt(self):
        req = Path(__file__).parent.parent / "requirements.txt"
        content = req.read_text(encoding="utf-8")
        assert "httpx" in content, "httpx not declared in requirements.txt"

    @pytest.mark.regression
    def test_httpx_in_pyproject_toml(self):
        pyproject = Path(__file__).parent.parent / "pyproject.toml"
        content = pyproject.read_text(encoding="utf-8")
        assert "httpx" in content, "httpx not declared in pyproject.toml"

    @pytest.mark.unit
    def test_httpx_importable(self):
        import httpx
        assert hasattr(httpx, "AsyncClient")


# ══════════════════════════════════════════════════════════════
#  Goal 5: Security docs correctness
# ══════════════════════════════════════════════════════════════

class TestSecurityDocsCorrectness:

    @pytest.mark.regression
    def test_security_doc_no_longer_claims_httpx_absent(self):
        doc = Path(__file__).parent.parent / "docs" / "security_privacy_policy.md"
        content = doc.read_text(encoding="utf-8")
        # The old text claimed httpx was "not present at runtime"
        assert "`httpx`" not in content.split("bulunmaz")[0] if "bulunmaz" in content else True

    @pytest.mark.regression
    def test_security_doc_mentions_localhost_only(self):
        doc = Path(__file__).parent.parent / "docs" / "security_privacy_policy.md"
        content = doc.read_text(encoding="utf-8")
        assert "127.0.0.1" in content
        assert "localhost" in content.lower()


# ══════════════════════════════════════════════════════════════
#  Goal 6: LocalLlamaServerProvider privacy
# ══════════════════════════════════════════════════════════════

class TestLocalServerProviderPrivacy:

    @pytest.mark.unit
    def test_remote_base_url_rejected(self, tmp_path):
        from src.llm.local_server_provider import LocalLlamaServerProvider
        from src.config import LocalLlamaServerConfig
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"FAKE_GGUF")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="https://api.openai.com",
            model_path=str(fake_model),
            mmproj_path="",
        )
        with pytest.raises(ValueError, match="SECURITY"):
            LocalLlamaServerProvider(cfg)

    @pytest.mark.unit
    def test_lan_ip_rejected(self, tmp_path):
        from src.llm.local_server_provider import LocalLlamaServerProvider
        from src.config import LocalLlamaServerConfig
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"FAKE_GGUF")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://192.168.1.100:8081",
            model_path=str(fake_model),
            mmproj_path="",
        )
        with pytest.raises(ValueError, match="SECURITY"):
            LocalLlamaServerProvider(cfg)

    @pytest.mark.unit
    def test_localhost_accepted(self, tmp_path):
        from src.llm.local_server_provider import LocalLlamaServerProvider
        from src.config import LocalLlamaServerConfig
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"FAKE_GGUF")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path=str(fake_model),
        )
        provider = LocalLlamaServerProvider(cfg)
        assert provider.model_name == "model.gguf"

    @pytest.mark.unit
    def test_text_only_payload_no_image_url(self, tmp_path):
        from src.llm.local_server_provider import LocalLlamaServerProvider
        from src.config import LocalLlamaServerConfig
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"FAKE_GGUF")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path=str(fake_model),
        )
        provider = LocalLlamaServerProvider(cfg)
        messages = provider._build_messages("hello", response_mode="text", image_artifact=None)
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    assert part.get("type") != "image_url", "Text-only must not have image_url"

    @pytest.mark.unit
    def test_multimodal_payload_has_image_url(self, tmp_path):
        from src.llm.local_server_provider import LocalLlamaServerProvider
        from src.config import LocalLlamaServerConfig
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"FAKE_GGUF")
        fake_mmproj = tmp_path / "mmproj.gguf"
        fake_mmproj.write_bytes(b"FAKE_MMPROJ")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path=str(fake_model),
            mmproj_path=str(fake_mmproj),
        )
        provider = LocalLlamaServerProvider(cfg)
        # Create a minimal artifact mock
        artifact = MagicMock()
        artifact.image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        artifact.source = "test"
        artifact.mime_type = "image/jpeg"
        messages = provider._build_messages("describe", image_artifact=artifact)
        has_image_url = False
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "image_url":
                        has_image_url = True
        assert has_image_url, "Multimodal payload must include image_url"


# ══════════════════════════════════════════════════════════════
#  Goal 7: Sidecar config safety
# ══════════════════════════════════════════════════════════════

class TestSidecarConfigSafety:

    @pytest.mark.unit
    def test_sidecar_host_forced_127(self):
        """SidecarManager._build_command must use --host 127.0.0.1."""
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="fake.exe",
            model_path="fake.gguf",
            port=9999,
        )
        mgr = SidecarManager(cfg)
        cmd = mgr._build_command()
        assert "--host" in cmd
        host_idx = cmd.index("--host")
        assert cmd[host_idx + 1] == "127.0.0.1"

    @pytest.mark.unit
    def test_sidecar_missing_exe_fails_loudly(self, tmp_path):
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path=str(tmp_path / "nonexistent.exe"),
            model_path=str(tmp_path / "nonexistent.gguf"),
        )
        mgr = SidecarManager(cfg)
        with pytest.raises(FileNotFoundError, match="executable not found"):
            mgr._validate_paths()

    @pytest.mark.unit
    def test_sidecar_missing_model_fails_loudly(self, tmp_path):
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig
        fake_exe = tmp_path / "llama-server.exe"
        fake_exe.write_bytes(b"EXE")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path=str(fake_exe),
            model_path=str(tmp_path / "nonexistent.gguf"),
        )
        mgr = SidecarManager(cfg)
        with pytest.raises(FileNotFoundError, match="Model GGUF not found"):
            mgr._validate_paths()

    @pytest.mark.unit
    def test_sidecar_missing_mmproj_fails_loudly(self, tmp_path):
        from src.llm.sidecar import SidecarManager
        from src.config import LocalLlamaServerConfig
        fake_exe = tmp_path / "llama-server.exe"
        fake_exe.write_bytes(b"EXE")
        fake_model = tmp_path / "model.gguf"
        fake_model.write_bytes(b"GGUF")
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path=str(fake_exe),
            model_path=str(fake_model),
            mmproj_path=str(tmp_path / "nonexistent-mmproj.gguf"),
        )
        mgr = SidecarManager(cfg)
        with pytest.raises(FileNotFoundError, match="mmproj GGUF not found"):
            mgr._validate_paths()

    @pytest.mark.unit
    def test_localhost_validation_rejects_0000(self):
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(base_url="http://0.0.0.0:8081")
        assert cfg.validate_localhost_only() is False

    @pytest.mark.unit
    def test_localhost_validation_accepts_127(self):
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(base_url="http://127.0.0.1:8081")
        assert cfg.validate_localhost_only() is True

    @pytest.mark.regression
    def test_dev_docker_path_documented(self):
        """Config should document Docker path as a comment example, not a live value."""
        yaml_path = Path(__file__).parent.parent / "config" / "default.yaml"
        content = yaml_path.read_text(encoding="utf-8")
        # Docker path must be a comment example, not the active executable_path value
        assert "Dev example" in content or "dev example" in content.lower()
        # Active executable_path should be empty (fail-loud on startup)
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        assert cfg["local_llama_server"]["executable_path"] == "", (
            "executable_path must be empty in committed config — no personal paths"
        )


# ══════════════════════════════════════════════════════════════
#  Goal 10: Metrics flags
# ══════════════════════════════════════════════════════════════

class TestMetricsFlags:

    @pytest.mark.unit
    def test_model_loaded_llm_flag_registered(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        assert "model_loaded_llm" in mc._flags

    @pytest.mark.unit
    def test_model_loaded_translator_flag_registered(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        assert "model_loaded_translator" in mc._flags

    @pytest.mark.unit
    def test_set_flag_llm_not_silently_dropped(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        mc.set_flag("model_loaded_llm", True)
        assert mc._flags["model_loaded_llm"] is True

    @pytest.mark.unit
    def test_set_flag_translator_not_silently_dropped(self):
        from src.metrics import MetricsCollector
        mc = MetricsCollector()
        mc.set_flag("model_loaded_translator", True)
        assert mc._flags["model_loaded_translator"] is True


# ══════════════════════════════════════════════════════════════
#  Goal 8: Architecture doc drift
# ══════════════════════════════════════════════════════════════

class TestArchitectureDocDrift:

    @pytest.mark.regression
    def test_voice_pipeline_no_translator_default(self):
        """architecture.md voice pipeline should NOT show translator as default path."""
        doc = Path(__file__).parent.parent / "docs" / "architecture.md"
        content = doc.read_text(encoding="utf-8")
        # Find the Voice Pipeline line in the header
        for line in content.split("\n")[:15]:
            if "Voice Pipeline" in line:
                assert "Translator" not in line or "disabled" in line.lower() or "available" in line.lower(), (
                    "Voice pipeline description still shows translator as default"
                )
                break

    @pytest.mark.regression
    def test_status_example_has_screen_context(self):
        doc = Path(__file__).parent.parent / "docs" / "architecture.md"
        content = doc.read_text(encoding="utf-8")
        assert "screen_context_enabled" in content

    @pytest.mark.regression
    def test_status_example_has_llm_provider(self):
        doc = Path(__file__).parent.parent / "docs" / "architecture.md"
        content = doc.read_text(encoding="utf-8")
        assert "llm_provider" in content

    @pytest.mark.regression
    def test_no_exact_stale_test_counts(self):
        """Test counts should be approximate, not exact outdated numbers."""
        doc = Path(__file__).parent.parent / "docs" / "architecture.md"
        content = doc.read_text(encoding="utf-8")
        # Should use approximate markers like ~ or approx
        assert "| 183 |" not in content, "Stale exact test count 183 still in architecture.md"
        assert "| 84 |" not in content, "Stale exact test count 84 still in architecture.md"
