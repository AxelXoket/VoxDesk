"""
VoxDesk — Local llama-server Sidecar Manager
Manages the lifecycle of a local llama-server process.

Architecture:
  VoxDesk app startup
    → SidecarManager.start()
    → subprocess: llama-server.exe -m model --mmproj mmproj --host 127.0.0.1 --port 8081
    → health check poll until ready
    → provider begins sending requests

  VoxDesk app shutdown
    → SidecarManager.stop()
    → SIGTERM / process.terminate()
    → cleanup

Privacy:
  - Always binds to 127.0.0.1 — never 0.0.0.0
  - No external network access
  - Model files remain local

Future EXE packaging:
  - Replace executable_path with bundled llama-server.exe
  - Config stays the same
  - No code changes needed
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import httpx

from src.config import LocalLlamaServerConfig

logger = logging.getLogger("voxdesk.sidecar")


class SidecarManager:
    """
    Manages a local llama-server process as an app sidecar.

    Lifecycle:
      1. start() → spawn process, wait for health
      2. is_healthy() → check /health endpoint
      3. stop() → terminate process cleanly
    """

    def __init__(self, config: LocalLlamaServerConfig) -> None:
        self._config = config
        self._process: subprocess.Popen | None = None
        self._healthy = False

        # Validate paths
        self._exe_path = Path(config.executable_path)
        self._model_path = Path(config.model_path)
        self._mmproj_path = Path(config.mmproj_path) if config.mmproj_path else None

    def _validate_paths(self) -> None:
        """Fail loudly if required files are missing."""
        if not self._exe_path.exists():
            raise FileNotFoundError(
                f"llama-server executable not found: {self._exe_path}\n"
                f"Dev: Install llama.cpp and set local_llama_server.executable_path in config.\n"
                f"Prod: Bundled llama-server.exe should be next to VoxDesk.exe."
            )

        if not self._model_path.exists():
            raise FileNotFoundError(
                f"Model GGUF not found: {self._model_path}\n"
                f"Place the model file under models/ directory."
            )

        if self._mmproj_path and not self._mmproj_path.exists():
            raise FileNotFoundError(
                f"mmproj GGUF not found: {self._mmproj_path}\n"
                f"Vision requires an mmproj file alongside the model GGUF."
            )

    def _build_command(self) -> list[str]:
        """Build llama-server command line arguments."""
        cmd = [
            str(self._exe_path),
            "-m", str(self._model_path),
            "--host", "127.0.0.1",    # NEVER bind to 0.0.0.0
            "--port", str(self._config.port),
            "-c", str(self._config.n_ctx),
            "-ngl", str(self._config.n_gpu_layers),
        ]

        if self._mmproj_path:
            cmd.extend(["--mmproj", str(self._mmproj_path)])

        if self._config.jinja:
            cmd.append("--jinja")

        return cmd

    async def start(self) -> bool:
        """
        Start the llama-server sidecar process.
        Returns True if server becomes healthy within timeout.
        """
        # Check if something is already running on the target port
        if await self._check_port_health():
            logger.info(
                f"Server already running on port {self._config.port} — reusing"
            )
            self._healthy = True
            return True

        self._validate_paths()

        cmd = self._build_command()
        logger.info(f"Starting llama-server sidecar:\n  {' '.join(cmd)}")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to start llama-server: {e}\n"
                f"Command: {' '.join(cmd)}"
            ) from e

        # Wait for health check
        logger.info(
            f"Waiting for llama-server health (timeout: {self._config.startup_timeout_seconds}s)..."
        )

        start_time = time.monotonic()
        while (time.monotonic() - start_time) < self._config.startup_timeout_seconds:
            # Check if process died
            if self._process.poll() is not None:
                stderr = self._process.stderr.read().decode("utf-8", errors="replace")[-500:]
                raise RuntimeError(
                    f"llama-server exited prematurely (code {self._process.returncode}).\n"
                    f"stderr: {stderr}"
                )

            if await self._check_port_health():
                elapsed = time.monotonic() - start_time
                logger.info(f"✅ llama-server healthy in {elapsed:.1f}s")
                self._healthy = True
                return True

            await asyncio.sleep(2.0)

        # Timeout — kill and fail
        self.stop_sync()
        raise RuntimeError(
            f"llama-server failed to become healthy within "
            f"{self._config.startup_timeout_seconds}s"
        )

    async def _check_port_health(self) -> bool:
        """Check if the health endpoint responds."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                url = f"http://127.0.0.1:{self._config.port}/health"
                resp = await client.get(url)
                return resp.status_code == 200
        except Exception:
            return False

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def stop_sync(self) -> None:
        """Synchronous stop — for use in atexit / signal handlers."""
        if self._process is None:
            return

        pid = self._process.pid
        logger.info(f"Stopping llama-server sidecar (PID {pid})...")

        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=self._config.shutdown_timeout_seconds)
                logger.info(f"llama-server (PID {pid}) terminated cleanly")
            except subprocess.TimeoutExpired:
                logger.warning(f"llama-server (PID {pid}) did not stop — killing")
                self._process.kill()
                self._process.wait(timeout=5)
        except Exception as e:
            logger.error(f"Error stopping llama-server: {e}")
        finally:
            self._process = None
            self._healthy = False

    async def stop(self) -> None:
        """Async stop wrapper."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.stop_sync)
