"""Model registry and inference settings.

Model choices and runtime flags come from the Milestone 1 evaluation
(docs/milestone-1-report.md): Qwen3.5-2B by default, Qwen3.5-0.8B for
memory-constrained PCs, Granite-4.2-3B for quality. Every setting can be
overridden with an ``EDULITE_*`` environment variable or a CLI flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_DIR / "models"
DATA_DIR = PROJECT_DIR / "data"
# llama.cpp CPU build b11780 (pinned in Milestone 1). Windows ships .exe; Linux has no extension.
DEFAULT_SERVER_BINARY = PROJECT_DIR / "runtime" / "llama-cpu" / (
    "llama-server.exe" if os.name == "nt" else "llama-server")

# Memory settings validated in Milestone 1: no in-RAM prompt cache and a single
# context checkpoint (both cut peak RAM substantially, no speed loss).
LEAN_MEMORY_FLAGS = ("--cache-ram", "0", "--ctx-checkpoints", "1")


@dataclass(frozen=True)
class ModelSpec:
    key: str
    name: str
    file: str
    quantization: str
    size_bytes: int            # exact size of the published file, used to detect partial downloads
    source_url: str
    license: str
    peak_ram_mb: int           # measured in Milestone 1 (lean settings, 4 threads, 4096 context)
    # Hybrid-reasoning models: hidden "thinking" is disabled so answers start quickly.
    disable_thinking: bool = True
    # Weight repacking gave no speedup for Q4_K_M but sped up prompt reading for Q4_0
    # (Milestone 1, section 5.3), so it's switched off only where it doesn't help.
    repack: bool = False

    def path(self, models_dir: Path = MODELS_DIR) -> Path:
        return models_dir / self.file


REGISTRY: dict[str, ModelSpec] = {
    "default": ModelSpec(
        key="default", name="Qwen3.5-2B", file="Qwen3.5-2B-Q4_K_M.gguf", quantization="Q4_K_M",
        size_bytes=1_280_835_840,
        source_url="https://huggingface.co/unsloth/Qwen3.5-2B-GGUF/resolve/main/Qwen3.5-2B-Q4_K_M.gguf",
        license="Apache-2.0", peak_ram_mb=1448),
    "lite": ModelSpec(
        key="lite", name="Qwen3.5-0.8B", file="Qwen3.5-0.8B-Q4_0.gguf", quantization="Q4_0",
        size_bytes=563_036_064,
        source_url="https://huggingface.co/ggml-org/Qwen3.5-0.8B-GGUF/resolve/main/Qwen3.5-0.8B-Q4_0.gguf",
        license="Apache-2.0", peak_ram_mb=1026, repack=True),
    "quality": ModelSpec(
        key="quality", name="Granite-4.2-3B", file="granite-4.2-3b-Q4_K_M.gguf", quantization="Q4_K_M",
        size_bytes=2_244_011_552,
        source_url="https://huggingface.co/ibm-granite/granite-4.2-3b-GGUF/resolve/main/granite-4.2-3b-Q4_K_M.gguf",
        license="Apache-2.0", peak_ram_mb=2406),
}


@dataclass(frozen=True)
class ModelStatus:
    spec: ModelSpec
    installed: bool
    problem: str | None = None


def model_status(spec: ModelSpec, models_dir: Path = MODELS_DIR) -> ModelStatus:
    path = spec.path(models_dir)
    if not path.is_file():
        return ModelStatus(spec, False, f"missing: {path}")
    size = path.stat().st_size
    if size != spec.size_bytes:
        return ModelStatus(spec, False, f"incomplete or different file: {size:,} bytes, expected {spec.size_bytes:,}")
    return ModelStatus(spec, True)


def installed_models(models_dir: Path = MODELS_DIR) -> list[ModelSpec]:
    return [spec for spec in REGISTRY.values() if model_status(spec, models_dir).installed]


def default_threads() -> int:
    """Physical cores (hyper-threads don't speed up inference), capped at 8, at least 1."""
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
    except ImportError:
        physical = None
    if not physical:
        physical = max(1, (os.cpu_count() or 2) // 2)
    return max(1, min(8, physical))


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value else default


@dataclass(frozen=True)
class InferenceConfig:
    model: ModelSpec = field(default_factory=lambda: REGISTRY["default"])
    models_dir: Path = MODELS_DIR
    server_command: tuple[str, ...] = (str(DEFAULT_SERVER_BINARY),)
    host: str = "127.0.0.1"
    port: int = 8765
    threads: int = field(default_factory=default_threads)
    context_tokens: int = 4096
    max_tokens: int = 1024
    temperature: float = 0.6
    top_p: float = 0.9
    startup_timeout_s: float = 120.0
    request_timeout_s: float = 300.0
    log_dir: Path = DATA_DIR / "logs"
    extra_args: tuple[str, ...] = ()

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def model_path(self) -> Path:
        return self.model.path(self.models_dir).resolve()

    def with_overrides(self, **changes) -> InferenceConfig:
        return replace(self, **{k: v for k, v in changes.items() if v is not None})


def config_from_env(model_key: str | None = None) -> InferenceConfig:
    key = model_key or os.getenv("EDULITE_MODEL", "default")
    if key not in REGISTRY:
        raise ValueError(f"Unknown model '{key}'. Choose one of: {', '.join(REGISTRY)}")
    base = InferenceConfig(model=REGISTRY[key])
    binary = os.getenv("EDULITE_SERVER_BINARY")
    return base.with_overrides(
        threads=_env_int("EDULITE_THREADS", base.threads),
        context_tokens=_env_int("EDULITE_CTX", base.context_tokens),
        max_tokens=_env_int("EDULITE_MAX_TOKENS", base.max_tokens),
        port=_env_int("EDULITE_PORT", base.port),
        server_command=(binary,) if binary else None,
    )
