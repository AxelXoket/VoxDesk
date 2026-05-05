"""
Sprint 8: LocalLlamaServerProvider + Sidecar Tests
Privacy-first, localhost-only, no base64 logging.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
FRONTEND_JS = FRONTEND / "js"


# ═══════════════════════════════════════════════════════════
#  Provider: localhost enforcement
# ═══════════════════════════════════════════════════════════

class TestLocalhostEnforcement:
    """LocalLlamaServerProvider must reject non-localhost base_url."""

    @pytest.mark.regression
    def test_localhost_127_accepted(self):
        """127.0.0.1 base_url should be accepted."""
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
        )
        assert cfg.validate_localhost_only() is True

    @pytest.mark.regression
    def test_localhost_name_accepted(self):
        """'localhost' base_url should be accepted."""
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://localhost:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
        )
        assert cfg.validate_localhost_only() is True

    @pytest.mark.regression
    def test_remote_url_rejected(self):
        """Remote base_url should be rejected."""
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://api.openai.com/v1",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
        )
        assert cfg.validate_localhost_only() is False

    @pytest.mark.regression
    def test_remote_ip_rejected(self):
        """Non-loopback IP should be rejected."""
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://192.168.1.100:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
        )
        assert cfg.validate_localhost_only() is False

    @pytest.mark.regression
    def test_provider_rejects_remote_on_construction(self):
        """Provider __init__ must raise ValueError for non-localhost."""
        from src.config import LocalLlamaServerConfig
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://cloud-api.example.com:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
        )
        from src.llm.local_server_provider import LocalLlamaServerProvider
        with pytest.raises(ValueError, match="SECURITY"):
            LocalLlamaServerProvider(cfg)


# ═══════════════════════════════════════════════════════════
#  Provider: path validation
# ═══════════════════════════════════════════════════════════

class TestPathValidation:
    """Provider must fail loudly if model/mmproj files are missing."""

    @pytest.mark.regression
    def test_missing_model_raises(self):
        """Missing model_path should raise FileNotFoundError."""
        from src.config import LocalLlamaServerConfig
        from src.llm.local_server_provider import LocalLlamaServerProvider
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path="models/nonexistent/model.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
        )
        with pytest.raises(FileNotFoundError, match="model"):
            LocalLlamaServerProvider(cfg)

    @pytest.mark.regression
    def test_missing_mmproj_raises(self):
        """Missing mmproj_path should raise FileNotFoundError."""
        from src.config import LocalLlamaServerConfig
        from src.llm.local_server_provider import LocalLlamaServerProvider
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/nonexistent/mmproj.gguf",
        )
        with pytest.raises(FileNotFoundError, match="mmproj"):
            LocalLlamaServerProvider(cfg)

    @pytest.mark.regression
    def test_empty_model_path_raises(self):
        """Empty model_path should raise FileNotFoundError."""
        from src.config import LocalLlamaServerConfig
        from src.llm.local_server_provider import LocalLlamaServerProvider
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path="",
        )
        with pytest.raises(FileNotFoundError):
            LocalLlamaServerProvider(cfg)


# ═══════════════════════════════════════════════════════════
#  Provider: message building
# ═══════════════════════════════════════════════════════════

class TestMessageBuilding:
    """Provider must build correct OpenAI-compatible payloads."""

    def _make_provider(self):
        """Create provider with valid local paths."""
        from src.config import LocalLlamaServerConfig
        from src.llm.local_server_provider import LocalLlamaServerProvider
        cfg = LocalLlamaServerConfig(
            enabled=True,
            base_url="http://127.0.0.1:8081",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
        )
        return LocalLlamaServerProvider(cfg)

    @pytest.mark.regression
    def test_text_only_message(self):
        """Text-only request should have string content, not list."""
        provider = self._make_provider()
        messages = provider._build_messages("merhaba", response_mode="text")
        # Last message should be user text
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], str)
        assert user_msg["content"] == "merhaba"

    @pytest.mark.regression
    def test_multimodal_message_with_artifact(self):
        """Image artifact should produce image_url content list."""
        provider = self._make_provider()

        # Mock artifact
        artifact = MagicMock()
        artifact.image_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG
        artifact.mime_type = "image/jpeg"
        artifact.source = "test"

        messages = provider._build_messages(
            "ekranımda ne var?",
            response_mode="text",
            image_artifact=artifact,
        )
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        assert isinstance(user_msg["content"], list)
        assert len(user_msg["content"]) == 2
        assert user_msg["content"][0]["type"] == "text"
        assert user_msg["content"][1]["type"] == "image_url"
        assert "base64" in user_msg["content"][1]["image_url"]["url"]

    @pytest.mark.regression
    def test_system_prompt_present(self):
        """System prompt should be first message."""
        provider = self._make_provider()
        messages = provider._build_messages("test")
        assert messages[0]["role"] == "system"
        assert len(messages[0]["content"]) > 0


# ═══════════════════════════════════════════════════════════
#  Provider: no base64 logging
# ═══════════════════════════════════════════════════════════

class TestNoBase64Logging:
    """Provider must never log base64 image data."""

    @pytest.mark.regression
    def test_provider_source_has_no_base64_log(self):
        """local_server_provider.py must not have logger calls that contain b64/base64 data."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        # Check that base64 encoding is done but not logged
        assert "b64 =" in src or "base64.b64encode" in src, "Provider should handle base64"
        # Make sure no logger.info/debug/warning that includes b64 variable
        for line in src.split("\n"):
            if "logger." in line and "b64" in line and "NEVER" not in line:
                assert False, f"Potential base64 logging found: {line.strip()}"


# ═══════════════════════════════════════════════════════════
#  Sidecar: validation
# ═══════════════════════════════════════════════════════════

class TestSidecarValidation:
    """Sidecar must validate paths and reject missing files."""

    @pytest.mark.regression
    def test_missing_executable_raises(self):
        """Missing executable should raise FileNotFoundError."""
        from src.config import LocalLlamaServerConfig
        from src.llm.sidecar import SidecarManager
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="C:/nonexistent/llama-server.exe",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
        )
        sidecar = SidecarManager(cfg)
        with pytest.raises(FileNotFoundError, match="executable"):
            sidecar._validate_paths()

    @pytest.mark.regression
    def test_sidecar_command_has_localhost(self):
        """Sidecar command must include --host 127.0.0.1."""
        from src.config import LocalLlamaServerConfig
        from src.llm.sidecar import SidecarManager
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="C:/Users/USER/.docker/bin/inference/llama-server.exe",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            mmproj_path="models/gemma-4-E4B-uncensored/mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf",
            port=8081,
        )
        sidecar = SidecarManager(cfg)
        cmd = sidecar._build_command()
        assert "--host" in cmd
        host_idx = cmd.index("--host")
        assert cmd[host_idx + 1] == "127.0.0.1", "Sidecar must bind to 127.0.0.1 only"
        assert "--jinja" in cmd

    @pytest.mark.regression
    def test_sidecar_never_binds_0000(self):
        """Sidecar command must never include 0.0.0.0."""
        from src.config import LocalLlamaServerConfig
        from src.llm.sidecar import SidecarManager
        cfg = LocalLlamaServerConfig(
            enabled=True,
            executable_path="C:/Users/USER/.docker/bin/inference/llama-server.exe",
            model_path="models/gemma-4-E4B-uncensored/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf",
            port=8081,
        )
        sidecar = SidecarManager(cfg)
        cmd = sidecar._build_command()
        assert "0.0.0.0" not in cmd


# ═══════════════════════════════════════════════════════════
#  Config: local_llama_server section
# ═══════════════════════════════════════════════════════════

class TestConfigIntegration:
    """Config must correctly parse local_llama_server section."""

    @pytest.mark.regression
    def test_config_has_local_llama_server(self):
        """AppConfig must have local_llama_server field."""
        from src.config import AppConfig
        cfg = AppConfig()
        assert hasattr(cfg, 'local_llama_server')

    @pytest.mark.regression
    def test_default_yaml_has_section(self):
        """default.yaml must contain local_llama_server section."""
        yaml_file = ROOT / "config" / "default.yaml"
        content = yaml_file.read_text(encoding="utf-8")
        assert "local_llama_server:" in content

    @pytest.mark.regression
    def test_default_yaml_provider_is_local_server(self):
        """default.yaml must have provider: local-llama-server."""
        yaml_file = ROOT / "config" / "default.yaml"
        content = yaml_file.read_text(encoding="utf-8")
        assert 'provider: "local-llama-server"' in content

    @pytest.mark.regression
    def test_config_base_url_is_localhost(self):
        """Loaded config base_url must be localhost."""
        from src.config import get_config
        cfg = get_config()
        assert cfg.local_llama_server.validate_localhost_only()


# ═══════════════════════════════════════════════════════════
#  Code structure: provider + sidecar files exist
# ═══════════════════════════════════════════════════════════

class TestCodeStructure:
    """Verify new files exist and have required content."""

    @pytest.mark.regression
    def test_local_server_provider_exists(self):
        """local_server_provider.py must exist."""
        assert (ROOT / "src" / "llm" / "local_server_provider.py").exists()

    @pytest.mark.regression
    def test_sidecar_module_exists(self):
        """sidecar.py must exist."""
        assert (ROOT / "src" / "llm" / "sidecar.py").exists()

    @pytest.mark.regression
    def test_provider_has_health_check(self):
        """Provider must implement health_check method."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        assert "async def health_check" in src

    @pytest.mark.regression
    def test_provider_has_chat(self):
        """Provider must implement chat method."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        assert "async def chat(" in src

    @pytest.mark.regression
    def test_provider_has_chat_stream(self):
        """Provider must implement chat_stream method."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        assert "async def chat_stream(" in src

    @pytest.mark.regression
    def test_sidecar_has_start_stop(self):
        """Sidecar must implement start and stop."""
        src = (ROOT / "src" / "llm" / "sidecar.py").read_text(encoding="utf-8")
        assert "async def start(" in src
        assert "async def stop(" in src

    @pytest.mark.regression
    def test_main_registers_local_server(self):
        """main.py must handle local-llama-server provider."""
        src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        assert "local-llama-server" in src
        assert "SidecarManager" in src

    @pytest.mark.regression
    def test_provider_uses_httpx(self):
        """Provider must use httpx for HTTP requests."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        assert "import httpx" in src

    @pytest.mark.regression
    def test_provider_privacy_comment(self):
        """Provider must document privacy guarantee."""
        src = (ROOT / "src" / "llm" / "local_server_provider.py").read_text(encoding="utf-8")
        assert "Privacy" in src or "NEVER logged" in src or "localhost" in src


# ═══════════════════════════════════════════════════════════
#  Model files exist
# ═══════════════════════════════════════════════════════════

class TestModelFiles:
    """Verify model files referenced in config exist."""

    @pytest.mark.regression
    def test_gemma4_uncensored_model_exists(self):
        """Q8_K_P model file must exist."""
        path = ROOT / "models" / "gemma-4-E4B-uncensored" / "Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf"
        assert path.exists(), f"Model not found: {path}"

    @pytest.mark.regression
    def test_gemma4_uncensored_mmproj_exists(self):
        """F16 mmproj file must exist."""
        path = ROOT / "models" / "gemma-4-E4B-uncensored" / "mmproj-Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-f16.gguf"
        assert path.exists(), f"mmproj not found: {path}"
