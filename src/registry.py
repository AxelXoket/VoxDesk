"""
VoxDesk — Module Registry
Dependency-injection factory catalog for pluggable engine backends.
NOT a service locator — no global state, no runtime register/unregister.

Lifecycle rules:
  - register() at module import / app startup — builds the catalog
  - create() at lifespan startup — instantiates engines ONCE
  - Request path uses ready instances from app.state — NEVER calls create()
  - After startup, registry is effectively immutable — no lock needed

Kind namespaces: stt/faster-whisper, tts/kokoro, llm/llama-cpp, capture/dxcam
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("voxdesk.registry")


class ModuleRegistry:
    """
    Factory catalog for engine backends.

    Usage:
        registry = ModuleRegistry()
        registry.register("stt", "faster-whisper", create_stt, requires_gpu=True)
        registry.register("tts", "kokoro", create_tts, requires_gpu=True)

        stt = registry.create("stt", "faster-whisper", config.stt)
    """

    def __init__(self):
        # {kind: {name: {"factory": callable, "metadata": dict}}}
        self._catalog: dict[str, dict[str, dict[str, Any]]] = {}

    def register(
        self,
        kind: str,
        name: str,
        factory: Callable,
        **metadata,
    ) -> None:
        """
        Register a factory function for a given kind/name pair.

        Args:
            kind: Module kind ("stt", "tts", "llm", "capture")
            name: Implementation name ("faster-whisper", "kokoro", etc.)
            factory: Callable that takes config and returns engine instance
            **metadata: Optional metadata (requires_gpu, description, etc.)
        """
        if kind not in self._catalog:
            self._catalog[kind] = {}

        if name in self._catalog[kind]:
            logger.warning(f"Registry: {kind}/{name} zaten kayıtlı — override ediliyor")

        self._catalog[kind][name] = {
            "factory": factory,
            "metadata": metadata,
        }
        logger.debug(f"Registry: {kind}/{name} kaydedildi")

    def create(self, kind: str, name: str, config: Any = None) -> Any:
        """
        Create an engine instance using the registered factory.
        Should be called ONCE at startup, NOT on each request.

        Args:
            kind: Module kind
            name: Implementation name
            config: Configuration to pass to factory

        Returns:
            Engine instance

        Raises:
            KeyError: If kind/name not found
        """
        if kind not in self._catalog:
            raise KeyError(
                f"Registry: bilinmeyen kind '{kind}'. "
                f"Mevcut kind'lar: {list(self._catalog.keys())}"
            )

        if name not in self._catalog[kind]:
            raise KeyError(
                f"Registry: '{kind}/{name}' bulunamadı. "
                f"Mevcut {kind} modülleri: {list(self._catalog[kind].keys())}"
            )

        factory = self._catalog[kind][name]["factory"]
        logger.info(f"Registry: {kind}/{name} oluşturuluyor...")

        if config is not None:
            return factory(config)
        return factory()

    def exists(self, kind: str, name: str) -> bool:
        """Check if a kind/name pair is registered."""
        return kind in self._catalog and name in self._catalog[kind]

    def list_modules(self, kind: str | None = None) -> dict:
        """
        List registered modules.

        Args:
            kind: If specified, list only modules of this kind.
                  If None, list all modules.

        Returns:
            dict: {kind: {name: metadata, ...}, ...}
        """
        if kind is not None:
            if kind not in self._catalog:
                return {}
            return {
                name: entry["metadata"]
                for name, entry in self._catalog[kind].items()
            }

        return {
            k: {
                name: entry["metadata"]
                for name, entry in entries.items()
            }
            for k, entries in self._catalog.items()
        }

    def get_metadata(self, kind: str, name: str) -> dict:
        """Get metadata for a registered module."""
        if not self.exists(kind, name):
            raise KeyError(f"Registry: '{kind}/{name}' bulunamadı")
        return self._catalog[kind][name]["metadata"]
