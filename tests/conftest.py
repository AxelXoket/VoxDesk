"""
VoxDesk — Test Configuration & Shared Fixtures
Tüm test dosyalarında kullanılan ortak fixture'lar ve autouse cleanup.
"""

import pytest
import time
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch


# ══════════════════════════════════════════════════════════════
#  Global State Cleanup — Autouse (function scope)
# ══════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _reset_global_state():
    """
    Her test sonrası tüm global state'leri sıfırla.
    Test izolasyonu için kritik — testler birbirini etkilemez.
    """
    yield

    # Config singleton reset
    import src.config as cfg_mod
    cfg_mod._config = None

    # AppState singleton reset — metrics önce temizle
    import src.main as main_mod
    if main_mod._state is not None and hasattr(main_mod._state, 'metrics'):
        try:
            main_mod._state.metrics.reset_for_tests()
        except Exception:
            pass  # Defensive — cleanup asla fail etmemeli
    main_mod._state = None


# ══════════════════════════════════════════════════════════════
#  LLM Mock Factory
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def make_llm():
    """
    Mock config ile VisionLLM factory.
    Her çağrıda yeni izole instance oluşturur.

    Usage:
        def test_something(make_llm):
            llm = make_llm(model="test", context_messages=5)
    """
    def _factory(**overrides):
        from src.llm_client import VisionLLM

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

    return _factory


# ══════════════════════════════════════════════════════════════
#  Fake Data Factories
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def make_fake_frame():
    """
    Fake CapturedFrame factory.

    Usage:
        frame = make_fake_frame(width=1920, height=1080)
    """
    def _factory(
        image_bytes: bytes = b"\xff\xd8\xff\xe0" * 100,
        timestamp: float = None,
        width: int = 1920,
        height: int = 1080,
    ):
        from src.capture import CapturedFrame
        return CapturedFrame(
            image_bytes=image_bytes,
            timestamp=timestamp or time.time(),
            width=width,
            height=height,
        )

    return _factory


@pytest.fixture
def make_fake_audio():
    """
    Fake audio numpy array factory.

    Usage:
        loud = make_fake_audio(amplitude=0.5, duration_ms=500)
        silent = make_fake_audio(amplitude=0.001)
    """
    def _factory(
        amplitude: float = 0.5,
        duration_ms: int = 500,
        sample_rate: int = 16000,
    ) -> np.ndarray:
        num_samples = int(sample_rate * duration_ms / 1000)
        return np.ones(num_samples, dtype=np.float32) * amplitude

    return _factory


# ══════════════════════════════════════════════════════════════
#  WebSocket Mock
# ══════════════════════════════════════════════════════════════

@pytest.fixture
def mock_websocket():
    """Fully mocked WebSocket — all send/receive methods."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.send_bytes = AsyncMock()
    ws.receive_json = AsyncMock(return_value={})
    ws.receive_text = AsyncMock(return_value="")
    ws.receive_bytes = AsyncMock(return_value=b"")
    return ws
