import socket
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from edulite.config import REGISTRY, InferenceConfig
from edulite.inference import LlamaServer

FAKE_SERVER = Path(__file__).with_name("fake_llama_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def model_file(tmp_path) -> Path:
    path = tmp_path / "models" / REGISTRY["default"].file
    path.parent.mkdir()
    path.write_bytes(b"GGUF fake model")
    return path


@pytest.fixture
def make_config(tmp_path, model_file):
    def make(**overrides) -> InferenceConfig:
        base = InferenceConfig(
            model=replace(REGISTRY["default"], size_bytes=model_file.stat().st_size),
            models_dir=model_file.parent,
            server_command=(sys.executable, str(FAKE_SERVER)),
            port=free_port(), threads=2, startup_timeout_s=10, request_timeout_s=3,
            log_dir=tmp_path / "logs")
        return base.with_overrides(**overrides)
    return make


@pytest.fixture
def servers():
    """Track servers created in a test and always stop them."""
    created: list[LlamaServer] = []

    def make(config) -> LlamaServer:
        server = LlamaServer(config)
        created.append(server)
        return server

    yield make
    for server in created:
        server.close()
