import json
import threading
import time
from dataclasses import replace

import psutil
import pytest

from eduai.config import REGISTRY, config_from_env, model_status
from eduai.inference import (ContextOverflowError, InferenceError, InferenceTimeoutError, ModelNotFoundError,
                               PortInUseError, ServerNotRunningError, ServerStartError, validate_messages)

USER = [{"role": "user", "content": "hello"}]


def process_gone(pid: int) -> bool:
    return not psutil.pid_exists(pid) or psutil.Process(pid).status() == psutil.STATUS_ZOMBIE


# --------------------------------------------------------------------- configuration

def test_registry_matches_milestone_1_choices():
    assert REGISTRY["default"].file == "Qwen3.5-2B-Q4_K_M.gguf"
    assert REGISTRY["lite"].file == "Qwen3.5-0.8B-Q4_0.gguf"
    assert REGISTRY["quality"].file == "granite-4.2-3b-Q4_K_M.gguf"
    assert not REGISTRY["default"].repack and REGISTRY["lite"].repack  # --no-repack only for Q4_K_M


def test_model_status_detects_missing_and_partial_files(tmp_path):
    spec = replace(REGISTRY["default"], size_bytes=10)
    assert not model_status(spec, tmp_path).installed
    (tmp_path / spec.file).write_bytes(b"12345")
    status = model_status(spec, tmp_path)
    assert not status.installed and "incomplete" in status.problem
    (tmp_path / spec.file).write_bytes(b"0123456789")
    assert model_status(spec, tmp_path).installed


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("EDUAI_THREADS", "3")
    monkeypatch.setenv("EDUAI_CTX", "2048")
    config = config_from_env("lite")
    assert (config.model.key, config.threads, config.context_tokens) == ("lite", 3, 2048)
    assert config.host == "127.0.0.1"
    with pytest.raises(ValueError):
        config_from_env("huge")


def test_command_uses_lean_flags_and_binds_localhost(make_config, servers):
    command = servers(make_config()).build_command()
    joined = " ".join(command)
    assert "--host 127.0.0.1" in joined and "--ctx-size 4096" in joined
    for flag in ("--cache-ram 0", "--ctx-checkpoints 1", "--no-repack", "--no-webui"):
        assert flag in joined


def test_repack_kept_for_q4_0_models(make_config, servers):
    config = make_config()
    lite = replace(config.model, repack=True)
    assert "--no-repack" not in servers(config.with_overrides(model=lite)).build_command()


def test_unsupported_flags_are_skipped(make_config, servers, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_UNSUPPORTED", "--no-repack,--ctx-checkpoints")
    command = servers(make_config()).build_command()
    assert "--no-repack" not in command and "--ctx-checkpoints" not in command
    assert "--cache-ram" in command
    assert "does not support --no-repack" in caplog.text


def test_validate_messages():
    assert validate_messages([{"role": "system", "content": "s"}, {"role": "user", "content": "u"},
                              {"role": "assistant", "content": "a"}])[2]["role"] == "assistant"
    with pytest.raises(ValueError):
        validate_messages([{"role": "tool", "content": "x"}])
    with pytest.raises(ValueError):
        validate_messages([{"role": "user", "content": None}])
    with pytest.raises(ValueError):
        validate_messages([])


# ------------------------------------------------------------------------ lifecycle

def test_start_waits_for_loading_then_chats_and_stops(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_LOAD_SECONDS", "0.8")
    server = servers(make_config())
    assert not server.is_running()
    seconds = server.start()
    assert seconds >= 0.6  # waited through the 503 "Loading model" phase
    assert server.is_running()
    assert server.chat(USER).text == "echo: hello"
    pid = server.pid
    server.stop()
    time.sleep(0.3)
    assert process_gone(pid) and not server.is_running()


def test_start_twice_does_not_launch_a_duplicate(make_config, servers):
    server = servers(make_config())
    server.start()
    pid = server.pid
    assert server.start() == 0.0 and server.pid == pid


def test_second_client_attaches_to_matching_server(make_config, servers):
    config = make_config()
    owner = servers(config)
    owner.start()
    other = servers(config)
    other.start()
    assert other.pid is None  # attached, did not launch its own process
    assert other.chat(USER).text == "echo: hello"
    other.stop()
    assert owner.is_running()  # stopping a non-owner leaves the server alone


def test_port_used_by_other_model_is_refused(make_config, servers, tmp_path):
    config = make_config()
    servers(config).start()
    other_model = tmp_path / "models" / "other.gguf"
    other_model.write_bytes(b"x")
    other = replace(config.model, file="other.gguf")
    with pytest.raises(PortInUseError):
        servers(config.with_overrides(model=other)).start()


def test_missing_model_file(make_config, servers):
    config = make_config()
    missing = replace(config.model, file="nope.gguf")
    with pytest.raises(ModelNotFoundError, match="huggingface.co"):
        servers(config.with_overrides(model=missing)).start()


def test_crash_during_startup_reports_log(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT_ON_START", "3")
    with pytest.raises(ServerStartError, match="failed to load model"):
        servers(make_config()).start()


def test_startup_timeout_kills_process(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_LOAD_SECONDS", "60")
    server = servers(make_config(startup_timeout_s=1))
    with pytest.raises(ServerStartError, match="did not become ready"):
        server.start()
    assert server.pid is None


def test_chat_before_start_is_an_error(make_config, servers):
    with pytest.raises(ServerNotRunningError):
        servers(make_config()).chat(USER)


# ---------------------------------------------------------------------------- chat

def test_chat_sends_history_and_settings(make_config, servers, monkeypatch, tmp_path):
    record = tmp_path / "requests.jsonl"
    monkeypatch.setenv("FAKE_RECORD", str(record))
    server = servers(make_config())
    server.start()
    history = [{"role": "system", "content": "be kind"}, {"role": "user", "content": "q1"},
               {"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}]
    result = server.chat(history, max_tokens=77)
    assert result.text == "echo: q2" and result.finish_reason == "stop" and result.tokens_per_second == 42.0
    body = json.loads(record.read_text().splitlines()[-1])
    assert body["messages"] == history
    assert body["max_tokens"] == 77
    assert body["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("mode, error", [("malformed", InferenceError), ("error500", InferenceError)])
def test_bad_replies_raise_clear_errors(make_config, servers, monkeypatch, mode, error):
    monkeypatch.setenv("FAKE_MODE", mode)
    server = servers(make_config())
    server.start()
    with pytest.raises(error):
        server.chat(USER)


def test_context_overflow_is_reported_with_token_counts(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "10")
    server = servers(make_config())
    server.start()
    with pytest.raises(ContextOverflowError) as info:
        server.chat([{"role": "user", "content": "a very long message"}])
    assert info.value.context_tokens == 10


def test_request_timeout(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "slow")
    server = servers(make_config(request_timeout_s=1))
    server.start()
    with pytest.raises(InferenceTimeoutError):
        server.chat(USER)


def test_server_crash_during_chat_is_detected(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "crash_on_chat")
    server = servers(make_config())
    server.start()
    with pytest.raises((ServerNotRunningError, InferenceError)):
        server.chat(USER)
    time.sleep(0.3)
    with pytest.raises(ServerNotRunningError):
        server.chat(USER)


# ------------------------------------------------------------------------ streaming

def test_stream_delivers_chunks_incrementally(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM_WORDS", "5")
    monkeypatch.setenv("FAKE_CHUNK_DELAY", "0.1")
    server = servers(make_config())
    server.start()
    stream = server.stream_chat(USER)
    started, arrivals = time.perf_counter(), []
    for _ in stream:
        arrivals.append(time.perf_counter() - started)
    assert stream.text == "echo: w0 w1 w2 w3 w4"
    assert len(arrivals) == 6 and arrivals[0] < arrivals[-1] - 0.3  # first chunk came well before the last
    assert stream.finish_reason == "stop" and stream.tokens_per_second == 42.0 and not stream.cancelled


def test_stream_cancel_from_another_thread(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM_WORDS", "200")
    monkeypatch.setenv("FAKE_CHUNK_DELAY", "0.02")
    server = servers(make_config())
    server.start()
    stream = server.stream_chat(USER)
    threading.Timer(0.3, stream.cancel).start()
    chunks = list(stream)
    assert stream.cancelled and 0 < len(chunks) < 150
    assert server.chat(USER).text == "echo: hello"  # server still healthy afterwards


def test_stream_cancel_with_event_and_by_breaking(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM_WORDS", "200")
    server = servers(make_config())
    server.start()
    event = threading.Event()
    stream = server.stream_chat(USER, cancel_event=event)
    for i, _ in enumerate(stream):
        if i == 3:
            event.set()
    assert stream.cancelled
    stream2 = server.stream_chat(USER)
    for i, _ in enumerate(stream2):
        if i == 2:
            break
    stream2.close()
    assert server.chat(USER).text == "echo: hello"


def test_stream_context_overflow(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "3")
    server = servers(make_config())
    server.start()
    with pytest.raises(ContextOverflowError):
        list(server.stream_chat(USER))
