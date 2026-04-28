"""
VoxDesk — Translator Module
MarianMT (Helsinki-NLP/opus-mt-tr-en) ile Türkçe → İngilizce çeviri.
PyTorch float16 GPU inference — ~146 MB VRAM, <50ms latency.
ManagedModel lifecycle entegrasyonu ile güvenli VRAM yönetimi.
"""

from __future__ import annotations

import logging

from src.model_state import ManagedModel

logger = logging.getLogger("voxdesk.translator")


class Translator:
    """
    MarianMT ile Türkçe → İngilizce çeviri.
    STT detected language "tr" ise çevir, "en" ise bypass.
    ManagedModel lifecycle ile VRAM-safe.
    """

    def __init__(
        self,
        model_path: str = "models/opus-mt-tr-en",
        device: str = "cuda",
        enabled: bool = True,
        min_loaded_seconds: float = 30.0,
        unload_cooldown_seconds: float = 10.0,
        keep_warm: bool = False,
    ):
        self.model_path = model_path
        self.device = device
        self.enabled = enabled

        self._model = None
        self._tokenizer = None

        # Lifecycle — ManagedModel composition
        self._lifecycle = _TranslatorLifecycle(
            owner=self,
            name="translator",
            min_loaded_seconds=min_loaded_seconds,
            unload_cooldown_seconds=unload_cooldown_seconds,
            keep_warm=keep_warm,
        )

    def translate(self, text: str, source_lang: str) -> str:
        """
        Metin çevir.

        Args:
            text: Çevrilecek metin
            source_lang: Kaynak dil kodu (STT'den gelir)

        Returns:
            İngilizce metin. source_lang "en" ise bypass (identity return).
        """
        if not self.enabled or not text.strip():
            return text

        # İngilizce ise bypass — çeviriye gerek yok
        if source_lang == "en":
            return text

        # Ref count guard
        if not self._lifecycle.acquire():
            logger.error("Translator model hazır değil — bypass")
            return text

        try:
            import torch

            inputs = self._tokenizer(
                [text], return_tensors="pt", padding=True, truncation=True
            )
            if self.device == "cuda" and torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}

            with torch.no_grad():
                translated = self._model.generate(**inputs)

            result = self._tokenizer.decode(
                translated[0], skip_special_tokens=True
            )

            logger.info(f"🔄 TR→EN: {text[:60]}... → {result[:60]}...")
            return result

        except Exception as e:
            logger.error(f"Çeviri hatası: {e}")
            return text  # Hata durumunda orijinal metni döndür
        finally:
            self._lifecycle.release()

    # ── Lifecycle Methods (ManagedModel proxy) ───────────────

    def safe_unload(self) -> bool:
        """Model VRAM'den güvenli şekilde kaldır."""
        return self._lifecycle.safe_unload()

    def close(self) -> None:
        """Shutdown cleanup — model + tokenizer."""
        self._lifecycle.close()

    def health(self) -> dict:
        """Engine durum raporu."""
        h = self._lifecycle.health()
        h["enabled"] = self.enabled
        h["model_path"] = self.model_path
        return h

    def acquire(self) -> bool:
        """Ref count artır — aktif kullanım başlıyor."""
        return self._lifecycle.acquire()

    def release(self) -> None:
        """Ref count azalt — aktif kullanım bitti."""
        self._lifecycle.release()


# ── Internal ManagedModel subclass ───────────────────────────

class _TranslatorLifecycle(ManagedModel):
    """Translator'ın model lifecycle yöneticisi."""

    def __init__(self, owner: Translator, **kwargs):
        super().__init__(**kwargs)
        self._owner = owner

    def _do_load(self):
        """MarianMT modelini yükle (lokal dosyadan)."""
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        tokenizer = MarianTokenizer.from_pretrained(
            self._owner.model_path, local_files_only=True
        )
        model = MarianMTModel.from_pretrained(
            self._owner.model_path, local_files_only=True
        )

        if self._owner.device == "cuda" and torch.cuda.is_available():
            model = model.half().cuda()
            vram_mb = torch.cuda.memory_allocated() / (1024 ** 2)
            logger.info(f"✅ MarianMT yüklendi (CUDA float16) — {vram_mb:.0f} MB VRAM")
        else:
            logger.info("✅ MarianMT yüklendi (CPU)")

        self._owner._model = model
        self._owner._tokenizer = tokenizer
        return model

    def _do_unload(self):
        """MarianMT modelini ve VRAM'i serbest bırak."""
        self._owner._model = None
        self._owner._tokenizer = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("🗑️ MarianMT translator unload edildi")
