"""
VoxDesk — Sprint 5.0 Audit Regression Tests
Audit bulgularının düzeltildiğini doğrulayan testler.
Her bulgu için en az bir test — regression guard.
"""

import inspect
import pytest
from unittest.mock import MagicMock, patch

from src.config import PersonalityConfig
from src.protocols import LLMProvider, TranslatorEngine


# ══════════════════════════════════════════════════════════════
#  Audit #1 — LLMProvider Protocol response_mode
# ══════════════════════════════════════════════════════════════

class TestAuditProtocolDrift:
    """LLMProvider protocol'ü response_mode içermeli."""

    @pytest.mark.regression
    def test_llm_protocol_chat_has_response_mode(self):
        """LLMProvider.chat() response_mode parametresi olmalı."""
        sig = inspect.signature(LLMProvider.chat)
        assert "response_mode" in sig.parameters
        # Default "text" olmalı
        default = sig.parameters["response_mode"].default
        assert default == "text"

    @pytest.mark.regression
    def test_llm_protocol_chat_stream_has_response_mode(self):
        """LLMProvider.chat_stream() response_mode parametresi olmalı."""
        sig = inspect.signature(LLMProvider.chat_stream)
        assert "response_mode" in sig.parameters
        default = sig.parameters["response_mode"].default
        assert default == "text"

    @pytest.mark.regression
    def test_protocol_matches_implementation(self):
        """Protocol ve implementation imzaları uyuşmalı."""
        from src.llm.provider import LlamaCppProvider
        proto_sig = inspect.signature(LLMProvider.chat)
        impl_sig = inspect.signature(LlamaCppProvider.chat)

        proto_params = set(proto_sig.parameters.keys()) - {"self"}
        impl_params = set(impl_sig.parameters.keys()) - {"self"}
        # Implementation protocol'ün üst kümesi olabilir ama temel params eşleşmeli
        assert proto_params.issubset(impl_params), (
            f"Protocol params {proto_params} implementation'da eksik: {proto_params - impl_params}"
        )


# ══════════════════════════════════════════════════════════════
#  Audit #2 — Debug Metrics Translator
# ══════════════════════════════════════════════════════════════

class TestAuditDebugMetrics:
    """Debug metrics translator bilgisi içermeli."""

    @pytest.mark.regression
    def test_debug_metrics_has_translator_key(self):
        """main.py debug_metrics engines dict'inde translator olmalı."""
        import ast
        from pathlib import Path

        main_path = Path("src/main.py")
        source = main_path.read_text(encoding="utf-8")
        # "translator" stringi engines dict'inde geçmeli
        assert '"translator"' in source or "'translator'" in source


# ══════════════════════════════════════════════════════════════
#  Audit #3 — pyproject.toml Translator Deps
# ══════════════════════════════════════════════════════════════

class TestAuditDependencies:
    """pyproject.toml translator bağımlılıkları tam olmalı."""

    @pytest.mark.regression
    def test_pyproject_has_transformers(self):
        """pyproject.toml dependencies'de transformers olmalı."""
        import tomllib
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        deps = [d.lower() for d in data["project"]["dependencies"]]
        dep_names = [d.split(">")[0].split("=")[0].split("<")[0].strip() for d in deps]
        assert "transformers" in dep_names
        assert "sentencepiece" in dep_names
        assert "sacremoses" in dep_names

    @pytest.mark.regression
    def test_pyproject_no_opencv(self):
        """pyproject.toml'da opencv olmamalı (kullanılmıyor)."""
        import tomllib
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        deps_lower = " ".join(data["project"]["dependencies"]).lower()
        assert "opencv" not in deps_lower

    @pytest.mark.regression
    def test_requirements_no_opencv(self):
        """requirements.txt'de opencv olmamalı."""
        with open("requirements.txt", "r") as f:
            content = f.read().lower()
        assert "opencv" not in content

    @pytest.mark.regression
    def test_no_cv2_imports_in_source(self):
        """Hiçbir kaynak dosyada cv2 import'u olmamalı."""
        from pathlib import Path
        for py_file in Path("src").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            assert "import cv2" not in content, f"cv2 import bulundu: {py_file}"


# ══════════════════════════════════════════════════════════════
#  Audit #4 — STT local_files_only
# ══════════════════════════════════════════════════════════════

class TestAuditSTTIsolation:
    """STT WhisperModel local_files_only=True olmalı."""

    @pytest.mark.regression
    def test_stt_do_load_has_local_files_only(self):
        """_STTLifecycle._do_load local_files_only=True kullanmalı."""
        from pathlib import Path
        stt_source = Path("src/stt.py").read_text(encoding="utf-8")
        assert "local_files_only=True" in stt_source, (
            "WhisperModel'de local_files_only=True eksik"
        )

    @pytest.mark.regression
    def test_translator_do_load_has_local_files_only(self):
        """Translator._do_load da local_files_only=True kullanmalı."""
        from pathlib import Path
        src = Path("src/translator.py").read_text(encoding="utf-8")
        assert "local_files_only=True" in src, (
            "MarianMT'de local_files_only=True eksik"
        )

    @pytest.mark.regression
    def test_all_model_loaders_use_local_files_only(self):
        """from_pretrained kullanan tüm dosyalarda local_files_only=True olmalı."""
        from pathlib import Path
        for py_file in Path("src").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Skip comments and docstrings
                if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                if "from_pretrained(" in stripped and "local_files_only" not in stripped:
                    # Check next few lines for local_files_only
                    block = "\n".join(lines[max(0,i):min(len(lines),i+5)])
                    assert "local_files_only=True" in block, (
                        f"{py_file}:{i+1}: from_pretrained var ama local_files_only=True yok"
                    )


# ══════════════════════════════════════════════════════════════
#  Audit #7 — VISUAL_MEMO_PROMPT English
# ══════════════════════════════════════════════════════════════

class TestAuditVisualMemo:
    """Visual memo prompt İngilizce olmalı."""

    @pytest.mark.regression
    def test_visual_memo_prompt_is_english(self):
        """VISUAL_MEMO_PROMPT İngilizce olmalı."""
        from src.llm.types import VISUAL_MEMO_PROMPT
        # Türkçe karakter olmamalı
        turkish_chars = set("çğıöşüÇĞİÖŞÜ")
        found_turkish = [c for c in VISUAL_MEMO_PROMPT if c in turkish_chars]
        assert len(found_turkish) == 0, f"Türkçe karakterler bulundu: {found_turkish}"
        # İngilizce anahtar kelimeler olmalı
        assert "screen" in VISUAL_MEMO_PROMPT.lower()
        assert "detail" in VISUAL_MEMO_PROMPT.lower()


# ══════════════════════════════════════════════════════════════
#  Audit #9 — Gereksiz Bağımlılık Temizliği
# ══════════════════════════════════════════════════════════════

class TestAuditUnusedDeps:
    """Kullanılmayan bağımlılıklar temizlenmiş olmalı."""

    @pytest.mark.regression
    def test_no_cv2_import_in_source(self):
        """Hiçbir kaynak dosyada cv2 import'u olmamalı."""
        from pathlib import Path
        for py_file in Path("src").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            assert "import cv2" not in content, f"cv2 import bulundu: {py_file}"


# ══════════════════════════════════════════════════════════════
#  Audit #10 — Version Check
# ══════════════════════════════════════════════════════════════

class TestAuditVersion:
    """Version Sprint 5.0'ı yansıtmalı."""

    @pytest.mark.regression
    def test_version_is_0_5_0(self):
        """pyproject.toml version >= 0.5.0 olmalı."""
        import tomllib
        with open("pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        version = data["project"]["version"]
        major, minor, patch = [int(x) for x in version.split(".")]
        assert (major, minor) >= (0, 5), f"Version çok eski: {version}"


# ══════════════════════════════════════════════════════════════
#  Audit #11 — Model Path Config Alignment
# ══════════════════════════════════════════════════════════════

class TestAuditModelPaths:
    """Config model yolları gerçek dosya yapısıyla eşleşmeli."""

    @pytest.mark.regression
    def test_llm_model_path_exists(self):
        """default.yaml LLM model_path var mı kontrol et."""
        from pathlib import Path
        import yaml
        config_path = Path("config/default.yaml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        model_path = cfg.get("llm", {}).get("model_path")
        if model_path:
            assert Path(model_path).exists(), f"LLM model dosyası yok: {model_path}"

    @pytest.mark.regression
    def test_translator_model_path_exists(self):
        """default.yaml translator model_path var mı kontrol et."""
        from pathlib import Path
        import yaml
        config_path = Path("config/default.yaml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        model_path = cfg.get("translator", {}).get("model_path")
        if model_path:
            assert Path(model_path).exists(), f"Translator model dosyası yok: {model_path}"

    @pytest.mark.regression
    def test_mmproj_path_exists(self):
        """default.yaml mmproj_path var mı kontrol et."""
        from pathlib import Path
        import yaml
        config_path = Path("config/default.yaml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        mmproj_path = cfg.get("llm", {}).get("mmproj_path")
        if mmproj_path:
            assert Path(mmproj_path).exists(), f"mmproj dosyası yok: {mmproj_path}"


# ══════════════════════════════════════════════════════════════
#  Cross-Cutting — Isolation Integrity
# ══════════════════════════════════════════════════════════════

class TestAuditIsolation:
    """Tüm model yükleyiciler offline isolation'a uymalı."""

    @pytest.mark.regression
    def test_isolation_env_guards(self):
        """verify_isolation HF_HUB_OFFLINE set etmeli."""
        from src.isolation import verify_isolation
        import os
        verify_isolation()
        assert os.environ.get("HF_HUB_OFFLINE") == "1"
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"

    @pytest.mark.regression
    def test_no_direct_hub_downloads_in_code(self):
        """Kaynak kodda doğrudan hub download fonksiyonu çağrılmamalı."""
        from pathlib import Path
        dangerous_patterns = [
            "hf_hub_download(",
            "snapshot_download(",
        ]
        for py_file in Path("src").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Skip comments and docstrings
                if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                    continue
                if stripped.startswith("- "):  # docstring bullet
                    continue
                for pattern in dangerous_patterns:
                    assert pattern not in stripped, (
                        f"{py_file}:{i+1}: Potansiyel hub download: {pattern}"
                    )
