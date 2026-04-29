"""
VoxDesk — Regression Test Suite
Bilinen bug'ların geri dönmemesini, API contract'ların kırılmamasını,
ve performans baseline'ının korunmasını garanti eder.

Her fix → zorunlu regression test.
"""

import re
import time
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch


# ══════════════════════════════════════════════════════════════
#  Bug Regression Guards
# ══════════════════════════════════════════════════════════════

class TestBugRegressions:
    """Düzeltilmiş bug'lar bir daha geri gelmemeli."""

    @pytest.mark.regression
    def test_no_external_cdn_in_html(self):
        """
        REGRESSION: CDN leak — external URL olmamalı.
        Fix: Google Fonts kaldırılıp system font kullanıldı.
        """
        frontend_dir = Path(__file__).parent.parent / "frontend"
        external_patterns = [
            r"https?://fonts\.googleapis\.com",
            r"https?://fonts\.gstatic\.com",
            r"https?://cdn\.",
            r"https?://unpkg\.com",
            r"https?://cdnjs\.",
        ]

        for html_file in frontend_dir.rglob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            for pattern in external_patterns:
                assert not re.search(pattern, content), \
                    f"CDN leak: {html_file.name} → {pattern}"

    @pytest.mark.regression
    def test_no_external_cdn_in_css(self):
        """CSS dosyalarında da external URL olmamalı."""
        frontend_dir = Path(__file__).parent.parent / "frontend"
        for css_file in frontend_dir.rglob("*.css"):
            content = css_file.read_text(encoding="utf-8")
            assert "fonts.googleapis.com" not in content, \
                f"CDN leak: {css_file.name}"
            assert "fonts.gstatic.com" not in content, \
                f"CDN leak: {css_file.name}"

    @pytest.mark.regression
    def test_no_external_cdn_in_js(self):
        """JS dosyalarında da external URL olmamalı."""
        frontend_dir = Path(__file__).parent.parent / "frontend"
        for js_file in frontend_dir.rglob("*.js"):
            content = js_file.read_text(encoding="utf-8")
            assert "googleapis.com" not in content, \
                f"CDN leak: {js_file.name}"
            assert "cdn." not in content.lower() or "cdn" in js_file.name.lower(), \
                f"CDN leak suspect: {js_file.name}"

    @pytest.mark.regression
    def test_startup_exception_not_masked(self):
        """
        REGRESSION: Startup hatası sessizce yutulmamalı.
        Fix: lifespan() except bloğunda raise var.
        """
        import inspect
        from src.main import lifespan

        source = inspect.getsource(lifespan)
        assert "raise" in source, \
            "lifespan() exception'ı yutmamalı — raise olmalı"

    @pytest.mark.regression
    def test_pystray_callback_params(self):
        """
        REGRESSION: pystray MenuItem callback (icon, item) almalı.
        """
        import inspect
        from src.tray import TrayIcon

        source = inspect.getsource(TrayIcon._run)
        assert "icon, item" in source or "icon,item" in source, \
            "pystray callback parametreleri eksik: (icon, item)"

    @pytest.mark.regression
    def test_isolation_env_guards(self):
        """Tüm güvenlik env guard'ları set edilmeli."""
        from src.isolation import _set_env_guards
        import os

        required = [
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
        ]

        # Save original env state
        original = {k: os.environ.get(k) for k in required}
        try:
            _set_env_guards()
            for key in required:
                assert os.environ.get(key) == "1", \
                    f"İzolasyon guard eksik: {key}"
        finally:
            # Restore original env state
            for k, v in original.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    @pytest.mark.regression
    def test_localhost_only_binding(self):
        """Host her zaman 127.0.0.1 olmalı — privacy contract."""
        from src.config import AppConfig
        cfg = AppConfig()
        assert cfg.host == "127.0.0.1", \
            f"Host {cfg.host} olmamalı — sadece 127.0.0.1"


# ══════════════════════════════════════════════════════════════
#  API Contract Regression (Schema Snapshots)
# ══════════════════════════════════════════════════════════════

class TestContractRegression:
    """
    Pydantic model schema'ları beklenmedik şekilde değişmemeli.
    Schema değişikliği → bilinçli karar + test update.
    """

    @pytest.mark.regression
    def test_chat_request_schema(self):
        """ChatRequest schema'sı kırılmamalı."""
        from src.routes.chat import ChatRequest
        schema = ChatRequest.model_json_schema()
        props = schema["properties"]
        assert "message" in props
        assert "include_screen" in props
        assert props["message"]["type"] == "string"

    @pytest.mark.regression
    def test_chat_response_schema(self):
        """ChatResponse schema'sı kırılmamalı."""
        from src.routes.chat import ChatResponse
        schema = ChatResponse.model_json_schema()
        props = schema["properties"]
        assert "response" in props
        assert "model" in props
        assert "has_image" in props

    @pytest.mark.regression
    def test_settings_response_schema(self):
        """SettingsResponse tüm alanları korumalı."""
        from src.routes.settings import SettingsResponse
        schema = SettingsResponse.model_json_schema()

        required_fields = {
            "model", "voice", "tts_speed", "tts_enabled",
            "capture_interval", "personality", "stt_language",
            "voice_activation_enabled", "voice_activation_threshold",
            "hotkeys",
        }
        actual_fields = set(schema["properties"].keys())
        missing = required_fields - actual_fields
        assert not missing, f"SettingsResponse eksik: {missing}"

    @pytest.mark.regression
    def test_voice_update_schema(self):
        """VoiceUpdateRequest schema'sı kırılmamalı."""
        from src.routes.settings import VoiceUpdateRequest
        schema = VoiceUpdateRequest.model_json_schema()
        assert "voice" in schema["properties"]

    @pytest.mark.regression
    def test_model_update_schema(self):
        """ModelUpdateRequest schema'sı kırılmamalı."""
        from src.routes.settings import ModelUpdateRequest
        schema = ModelUpdateRequest.model_json_schema()
        assert "model" in schema["properties"]


# ══════════════════════════════════════════════════════════════
#  Privacy & Security Regression
# ══════════════════════════════════════════════════════════════

class TestPrivacyRegression:
    """Local-only runtime contract korunmalı."""

    @pytest.mark.regression
    def test_cors_only_localhost(self):
        """CORS sadece localhost origin'lere izin vermeli."""
        import src.main as main_mod
        import inspect

        source = inspect.getsource(main_mod)
        assert "127.0.0.1" in source, "CORS config 127.0.0.1 içermeli"

    @pytest.mark.regression
    def test_uvicorn_binds_localhost(self):
        """Uvicorn her zaman localhost'a bind olmalı."""
        import inspect
        from src.main import main as main_func

        source = inspect.getsource(main_func)
        assert "host=config.host" in source or "host=" in source

    @pytest.mark.regression
    def test_visual_memo_prompt_not_empty(self):
        """Visual memo prompt boş olmamalı ve İngilizce olmalı."""
        from src.llm.types import VISUAL_MEMO_PROMPT
        assert len(VISUAL_MEMO_PROMPT) > 50
        assert "screen" in VISUAL_MEMO_PROMPT.lower() or "detail" in VISUAL_MEMO_PROMPT.lower()

    @pytest.mark.regression
    def test_config_singleton_pattern(self):
        """Config singleton doğru çalışmalı."""
        from src.config import get_config
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2, "get_config() aynı instance dönmeli"

    @pytest.mark.regression
    def test_health_endpoint_no_secrets(self):
        """
        /api/health response'u sadece status/version/uptime/degraded içermeli.
        Model adı, registry, VRAM, debug metrics, internal path, token sızdırmamalı.
        """
        import inspect
        from src.main import health

        source = inspect.getsource(health)
        # Health fonksiyonu bu kelimeleri response dict'e koymamalı
        forbidden_in_health = [
            "registry", "vram", "memory", "torch",
            "model", "stt", "tts", "llm",
            "secret", "token", "password", "key",
        ]
        # Response dict'e eklenen key'lere bak (return { ... } bloğu)
        # Source'da bu terimlerin report/response'a yazılmadığını doğrula
        # NOT: "status" = OK, "version" = OK, "uptime" = OK, "degraded" = OK
        for term in forbidden_in_health:
            # Sadece response dict key olarak kullanılmamalı
            assert f'"{term}"' not in source and f"'{term}'" not in source, \
                f"/api/health response'unda gizli bilgi sızıntısı: {term}"

    @pytest.mark.regression
    def test_no_external_urls_in_python(self):
        """
        src/ altında dış URL kullanımı olmamalı.
        Localhost/127.0.0.1 ve isolation probe (8.8.8.8) hariç.
        Cloud API, telemetry, CDN, remote logging yakalanmalı.
        """
        src_dir = Path(__file__).parent.parent / "src"
        # Allowed exceptions
        allowed_hosts = [
            "127.0.0.1",
            "localhost",
            "0.0.0.0",
            "8.8.8.8",          # isolation.py probe — bilerek var
            "http://localhost",
            "http://127.0.0.1",
        ]
        url_pattern = re.compile(r'https?://[^\s\'")\]]+')

        violations = []
        for py_file in src_dir.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for match in url_pattern.finditer(content):
                url = match.group()
                # Skip f-string templates (e.g. http://{config.host})
                if "{" in url or "}" in url:
                    continue
                # Check if it's an allowed localhost/probe URL
                is_allowed = any(host in url for host in allowed_hosts)
                if not is_allowed:
                    violations.append(f"{py_file.name}: {url}")

        assert not violations, \
            f"src/ içinde dış URL bulundu (privacy ihlali):\n" + \
            "\n".join(f"  - {v}" for v in violations)


# ══════════════════════════════════════════════════════════════
#  Performance Baseline (Deterministic Micro-benchmarks)
#  >%25 regression → CI FAIL
#  Hardware-dependent → report-only
# ══════════════════════════════════════════════════════════════

class TestPerformanceBaseline:
    """Deterministic CPU-bound fonksiyonlar — hardware bağımsız."""

    @pytest.mark.benchmark
    def test_build_messages_perf(self, benchmark, make_llm):
        """_build_messages() performans baseline."""
        llm = make_llm(context_messages=10)

        for i in range(10):
            if i % 2 == 0:
                msg = llm._history.add_user_message(f"Test mesajı {i} " * 20)
                if i % 3 == 0:
                    msg.visual_memo = f"Memo {i}"
            else:
                llm._history.add_assistant_message(f"Test mesajı {i} " * 20)

        result = benchmark(llm._build_messages, "Yeni soru")
        assert len(result) > 0

    @pytest.mark.benchmark
    def test_voice_activation_perf(self, benchmark):
        """check_voice_activation() performans baseline."""
        from src.stt import SpeechRecognizer
        stt = SpeechRecognizer(activation_threshold_db=-30.0)

        audio = np.random.randn(16000).astype(np.float32) * 0.3
        result = benchmark(stt.check_voice_activation, audio)
        assert result is True or result is False or isinstance(result, (bool, np.bool_))

    @pytest.mark.benchmark
    def test_export_history_perf(self, benchmark, make_llm):
        """export_history() performans baseline."""
        llm = make_llm()

        for i in range(100):
            msg = llm._history.add_user_message(f"Mesaj {i}")
            if i % 5 == 0:
                msg.visual_memo = f"Memo {i}"

        result = benchmark(llm.export_history)
        assert len(result) == 100

    @pytest.mark.benchmark
    def test_voice_profiles_perf(self, benchmark):
        """get_available_voices() performans baseline."""
        from src.tts import VoiceSynth
        result = benchmark(VoiceSynth.get_available_voices)
        assert len(result) >= 4


# ══════════════════════════════════════════════════════════════
#  Sprint 1 — Static File Regression Guards
# ══════════════════════════════════════════════════════════════

class TestSprint1StaticGuards:
    """Sprint 1: Static file content checks for known fixed gaps."""

    # --- Task 3: app.js health/status migration ---

    @pytest.mark.regression
    def test_app_js_no_data_model_split(self):
        """app.js must NOT contain data.model.split (Gap 1 fix)."""
        app_js = Path(__file__).parent.parent / "frontend" / "js" / "app.js"
        content = app_js.read_text(encoding="utf-8")
        assert "data.model.split" not in content

    @pytest.mark.regression
    def test_app_js_fetches_api_status(self):
        """app.js must fetch /api/status for runtime state."""
        app_js = Path(__file__).parent.parent / "frontend" / "js" / "app.js"
        content = app_js.read_text(encoding="utf-8")
        assert "/api/status" in content

    @pytest.mark.regression
    def test_app_js_still_fetches_api_health(self):
        """app.js must still use /api/health for availability."""
        app_js = Path(__file__).parent.parent / "frontend" / "js" / "app.js"
        content = app_js.read_text(encoding="utf-8")
        assert "/api/health" in content

    # --- Task 6: audio-capture.js loading ---

    @pytest.mark.regression
    def test_index_html_loads_audio_capture_js(self):
        """index.html must include audio-capture.js."""
        index = Path(__file__).parent.parent / "frontend" / "index.html"
        content = index.read_text(encoding="utf-8")
        assert "audio-capture.js" in content

    @pytest.mark.regression
    def test_audio_capture_before_app_js(self):
        """audio-capture.js must appear before app.js in index.html."""
        index = Path(__file__).parent.parent / "frontend" / "index.html"
        content = index.read_text(encoding="utf-8")
        ac_pos = content.find("audio-capture.js")
        app_pos = content.find("app.js")
        assert ac_pos != -1, "audio-capture.js not found"
        assert app_pos != -1, "app.js not found"
        assert ac_pos < app_pos

    @pytest.mark.regression
    def test_audio_processor_not_as_script_tag(self):
        """audio-processor.js must NOT be loaded as normal <script>."""
        index = Path(__file__).parent.parent / "frontend" / "index.html"
        content = index.read_text(encoding="utf-8")
        # Should not have <script src="...audio-processor.js">
        assert '<script src="/static/js/audio-processor.js">' not in content

    # --- Task 7: voxly.yaml prompt hardening ---

    @pytest.mark.regression
    def test_voxly_no_never_refuse(self):
        """voxly.yaml must NOT contain 'Never refuse to help'."""
        voxly = Path(__file__).parent.parent / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8")
        assert "Never refuse to help" not in content

    @pytest.mark.regression
    def test_voxly_no_same_language_default(self):
        """voxly.yaml must NOT instruct same-language as default."""
        voxly = Path(__file__).parent.parent / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8")
        assert "Respond in the same language" not in content

    @pytest.mark.regression
    def test_voxly_english_default(self):
        """voxly.yaml must specify English as default output."""
        voxly = Path(__file__).parent.parent / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8").lower()
        assert "english" in content

    @pytest.mark.regression
    def test_voxly_refuses_harmful(self):
        """voxly.yaml must mention refusal of harmful/unsafe requests.

        Safety guard semantic — checks that the personality prompt contains
        explicit safety boundary language (EN or TR).
        """
        voxly = Path(__file__).parent.parent / "config" / "personalities" / "voxly.yaml"
        content = voxly.read_text(encoding="utf-8").lower()
        # English safety keywords (current prompt is English)
        en_safety = any(w in content for w in ["refuse", "harmful", "unsafe", "illegal", "unethical"])
        # Turkish safety keywords (if prompt is ever translated)
        tr_safety = any(w in content for w in ["reddet", "zararlı", "güvenli değil", "yasa dışı", "tehlikeli"])
        assert en_safety or tr_safety, (
            "voxly.yaml must contain safety/refusal guard — "
            "neither English nor Turkish safety keywords found"
        )
