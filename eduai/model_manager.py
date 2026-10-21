"""Keeps one model server running for the web app and applies settings changes."""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eduai.config import MODELS_DIR, REGISTRY, InferenceConfig, ModelSpec, model_status
from eduai.inference import InferenceError, LlamaServer
from eduai.tutor.prompts import LEVELS

logger = logging.getLogger("eduai.models")

CONTEXT_CHOICES = (2048, 4096, 8192)
# Changing these needs a server restart; max_tokens and temperature apply per request.
RESTART_KEYS = ("model", "context_tokens", "threads")


class ModelBusyError(RuntimeError):
    """A change was requested while an answer is being generated."""


@dataclass(frozen=True)
class Settings:
    model: str
    context_tokens: int
    max_tokens: int
    threads: int
    temperature: float
    level: str = "beginner"       # tutoring settings: apply to the next answer, no restart
    use_notes: bool = True

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class ModelManager:
    def __init__(self, config: InferenceConfig,
                 server_factory: Callable[[InferenceConfig], LlamaServer] = LlamaServer,
                 registry: dict[str, ModelSpec] | None = None, level: str = "beginner", use_notes: bool = True):
        self._config = config
        self.level = level
        self.use_notes = use_notes
        self.registry = registry or REGISTRY
        self._factory = server_factory
        self._server: LlamaServer | None = None
        self.state = "stopped"          # stopped | loading | ready | error
        self.error: str | None = None
        self.load_seconds: float | None = None
        self._state_lock = threading.Lock()
        # Held for the whole of a generation so the model can't be swapped mid-answer.
        self.generation_lock = threading.Lock()

    @property
    def config(self) -> InferenceConfig:
        return self._config

    @property
    def settings(self) -> Settings:
        c = self._config
        return Settings(c.model.key, c.context_tokens, c.max_tokens, c.threads, c.temperature,
                        self.level, self.use_notes)

    @property
    def server(self) -> LlamaServer:
        if self.state != "ready" or self._server is None:
            raise InferenceError(self.error or f"The model is {self.state}, not ready yet.")
        return self._server

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        with self._state_lock:
            self.state, self.error = "loading", None
            server = self._factory(self._config)
            self._server = server
        started = time.perf_counter()
        try:
            server.start()
        except Exception as error:  # report any startup failure in the UI
            logger.error("Model failed to start: %s", error)
            with self._state_lock:
                self.state, self.error = "error", str(error)
            server.close()
            return
        with self._state_lock:
            self.state, self.load_seconds = "ready", round(time.perf_counter() - started, 1)

    def start_in_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.start, name="model-loader", daemon=True)
        self.state = "loading"
        thread.start()
        return thread

    def shutdown(self) -> None:
        with self._state_lock:
            server, self._server = self._server, None
            self.state = "stopped"
        if server is not None:
            server.close()

    # ---- settings -----------------------------------------------------------
    def apply(self, changes: dict) -> bool:
        """Apply new settings. Returns True if the model server was restarted.

        Raises ValueError for invalid values and ModelBusyError while generating.
        """
        current = self.settings.to_dict()
        merged = {**current, **{k: v for k, v in changes.items() if v is not None}}
        validate_settings(merged, self.registry, self._config.models_dir)
        restart = any(merged[k] != current[k] for k in RESTART_KEYS)
        if not self.generation_lock.acquire(blocking=False):
            raise ModelBusyError("Edu.ai is still answering. Stop the answer before changing settings.")
        try:
            self._config = self._config.with_overrides(
                model=self.registry[merged["model"]], context_tokens=merged["context_tokens"],
                max_tokens=merged["max_tokens"], threads=merged["threads"], temperature=merged["temperature"])
            self.level, self.use_notes = merged["level"], merged["use_notes"]
            if restart:
                self.shutdown()
                self.start()
        finally:
            self.generation_lock.release()
        return restart

    def status(self) -> dict:
        ram_mb = None
        server = self._server
        if self.state == "ready" and server is not None and server.pid:
            try:
                import psutil
                ram_mb = round(psutil.Process(server.pid).memory_info().rss / 2**20)
            except Exception:
                ram_mb = None
        spec = self._config.model
        return {"state": self.state, "error": self.error, "load_seconds": self.load_seconds,
                "model": {"key": spec.key, "name": spec.name, "quantization": spec.quantization},
                "ram_mb": ram_mb, "settings": self.settings.to_dict()}


def validate_settings(values: dict, registry: dict[str, ModelSpec] = REGISTRY, models_dir: Path = MODELS_DIR) -> None:
    if values["model"] not in registry:
        raise ValueError(f"Unknown model '{values['model']}'")
    status = model_status(registry[values["model"]], models_dir)
    if not status.installed:
        raise ValueError(f"{registry[values['model']].name} is not installed ({status.problem})")
    if values["context_tokens"] not in CONTEXT_CHOICES:
        raise ValueError(f"Context length must be one of {CONTEXT_CHOICES}")
    if not 64 <= values["max_tokens"] <= 4096:
        raise ValueError("Maximum answer length must be between 64 and 4096 tokens")
    if values["max_tokens"] >= values["context_tokens"]:
        raise ValueError("Maximum answer length must be smaller than the context length")
    if not 1 <= values["threads"] <= (os.cpu_count() or 1):
        raise ValueError(f"Threads must be between 1 and {os.cpu_count()}")
    if not 0.0 <= values["temperature"] <= 1.5:
        raise ValueError("Temperature must be between 0 and 1.5")
    if values.get("level", "beginner") not in LEVELS:
        raise ValueError(f"Level must be one of: {', '.join(LEVELS)}")
    if not isinstance(values.get("use_notes", True), bool):
        raise ValueError("use_notes must be true or false")


def models_overview(registry: dict[str, ModelSpec] = REGISTRY, models_dir: Path = MODELS_DIR) -> list[dict]:
    rows = []
    for key, spec in registry.items():
        status = model_status(spec, models_dir)
        rows.append({"key": key, "name": spec.name, "quantization": spec.quantization,
                     "ram_gb": round(spec.peak_ram_mb / 1024, 1), "license": spec.license,
                     "installed": status.installed, "problem": status.problem})
    return rows
