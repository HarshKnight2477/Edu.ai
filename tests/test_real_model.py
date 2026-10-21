"""End-to-end checks against the real llama.cpp runtime and a real model.

Uses the lite model (fastest to load). Skipped automatically when the runtime
or model file isn't installed, so the rest of the suite runs anywhere.
"""

import time

import psutil
import pytest

from edulite.config import DEFAULT_SERVER_BINARY, REGISTRY, config_from_env, model_status
from edulite.inference import LlamaServer

from conftest import free_port

pytestmark = pytest.mark.skipif(
    not DEFAULT_SERVER_BINARY.exists() or not model_status(REGISTRY["lite"]).installed,
    reason="llama.cpp runtime or lite model not installed")


@pytest.fixture(scope="module")
def real_server():
    server = LlamaServer(config_from_env("lite").with_overrides(port=free_port(), threads=4, max_tokens=64))
    server.start()
    yield server
    server.close()


def test_real_chat_answers(real_server):
    result = real_server.chat([{"role": "user", "content": "What is 12 + 30? Reply with just the number."}],
                              max_tokens=16, temperature=0)
    assert "42" in result.text


def test_real_history_is_used(real_server):
    messages = [{"role": "user", "content": "My favourite number is 7. Just say OK."},
                {"role": "assistant", "content": "OK."},
                {"role": "user", "content": "What is my favourite number? Reply with just the number."}]
    assert "7" in real_server.chat(messages, max_tokens=16, temperature=0).text


def test_real_stream_and_cancel(real_server):
    stream = real_server.stream_chat([{"role": "user", "content": "Count from 1 to 100, one per line."}],
                                     max_tokens=400)
    for i, _ in enumerate(stream):
        if i == 5:
            stream.cancel()
    assert stream.cancelled
    started = time.perf_counter()
    real_server.chat([{"role": "user", "content": "Say OK."}], max_tokens=4)
    assert time.perf_counter() - started < 5  # generation really stopped; the server was free


def test_real_server_binds_localhost_only(real_server):
    listening = [c.laddr for c in psutil.Process(real_server.pid).net_connections(kind="tcp")
                 if c.status == psutil.CONN_LISTEN]
    assert listening and all(addr.ip == "127.0.0.1" for addr in listening)
