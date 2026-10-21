"""Local inference: a managed llama.cpp ``llama-server`` process and a chat client for it.

Everything stays on this machine: the server binds to 127.0.0.1 and requests
only ever go to that local address.

    from eduai.config import config_from_env
    from eduai.inference import LlamaServer

    with LlamaServer(config_from_env()) as server:
        print(server.chat([{"role": "user", "content": "What is a variable?"}]).text)
        for chunk in server.stream_chat([{"role": "user", "content": "Explain loops"}]):
            print(chunk, end="", flush=True)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from eduai.config import LEAN_MEMORY_FLAGS, InferenceConfig

logger = logging.getLogger("eduai.inference")

VALID_ROLES = frozenset({"system", "user", "assistant"})
LOG_TAIL_LINES = 25


# ------------------------------------------------------------------------- errors

class InferenceError(RuntimeError):
    """Base class for all inference failures."""


class ModelNotFoundError(InferenceError):
    pass


class ServerStartError(InferenceError):
    pass


class PortInUseError(ServerStartError):
    pass


class ServerNotRunningError(InferenceError):
    pass


class InferenceTimeoutError(InferenceError):
    pass


class ContextOverflowError(InferenceError):
    """The conversation no longer fits in the model's context window."""

    def __init__(self, message: str, prompt_tokens: int | None = None, context_tokens: int | None = None):
        super().__init__(message)
        self.prompt_tokens = prompt_tokens
        self.context_tokens = context_tokens


# ------------------------------------------------------------------------ results

@dataclass
class ChatResult:
    text: str
    finish_reason: str | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tokens_per_second: float | None = None


@dataclass
class ChatStream:
    """Iterate to receive text chunks as the model writes them.

    Stops early when ``cancel()`` is called (from any thread), when the caller
    breaks out of the loop, or when ``cancel_event`` is set. Afterwards,
    ``text`` holds everything received and ``cancelled`` tells whether it
    stopped early.
    """

    _chunks: Iterator[str]
    _response: httpx.Response | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    text: str = ""
    finish_reason: str | None = None
    tokens_per_second: float | None = None
    cancelled: bool = False

    def __iter__(self) -> Iterator[str]:
        return self._chunks

    def cancel(self) -> None:
        self.cancel_event.set()
        self.close()

    def close(self) -> None:
        # Closing the HTTP response makes llama-server stop generating for this request.
        if self._response is not None:
            self._response.close()


# ----------------------------------------------------------------- helpers

def validate_messages(messages: Iterable[dict]) -> list[dict]:
    clean = []
    for i, message in enumerate(messages):
        role, content = message.get("role"), message.get("content")
        if role not in VALID_ROLES:
            raise ValueError(f"message {i}: role must be one of {sorted(VALID_ROLES)}, got {role!r}")
        if not isinstance(content, str):
            raise ValueError(f"message {i}: content must be a string")
        clean.append({"role": role, "content": content})
    if not clean:
        raise ValueError("at least one message is required")
    return clean


def _error_from_response(response: httpx.Response) -> InferenceError:
    try:
        error = response.json().get("error", {})
    except (json.JSONDecodeError, AttributeError):
        error = {}
    message = error.get("message") or response.text[:300] or f"HTTP {response.status_code}"
    if error.get("type") == "exceed_context_size_error":
        return ContextOverflowError(message, error.get("n_prompt_tokens"), error.get("n_ctx"))
    return InferenceError(f"llama-server returned HTTP {response.status_code}: {message}")


def _kill_with_parent(pid: int):
    """Make the OS kill the server if this Python process dies, even if it crashes.

    Windows: put it in a Job object that kills its members when the last handle
    (ours) closes. Returns the job handle, which must be kept alive.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
    PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not job or not kernel32.SetInformationJobObject(
            job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ctypes.byref(info), ctypes.sizeof(info)):
        logger.warning("Could not create a job object; server may outlive a crash")
        return None
    process = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    ok = process and kernel32.AssignProcessToJobObject(job, process)
    if process:
        kernel32.CloseHandle(process)
    if not ok:
        logger.warning("Could not assign llama-server to a job object")
        kernel32.CloseHandle(job)
        return None
    return job


def _linux_parent_death_signal():  # pragma: no cover - Linux only
    """preexec_fn: deliver SIGTERM to the server if its parent dies."""
    import ctypes
    import signal
    PR_SET_PDEATHSIG = 1
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(PR_SET_PDEATHSIG, signal.SIGTERM)


# ------------------------------------------------------------------- server

class LlamaServer:
    """Owns one llama-server process (or attaches to a matching one already running)."""

    def __init__(self, config: InferenceConfig):
        self.config = config
        self._process: subprocess.Popen | None = None
        self._job = None
        self._log_file = None
        self._owned = False
        self._attached = False
        self._lock = threading.Lock()
        self._supported_flags: str | None = None
        self._atexit_registered = False
        self._log_path: Path | None = None
        self._client = httpx.Client(base_url=config.base_url, timeout=httpx.Timeout(
            config.request_timeout_s, connect=5.0), trust_env=False)  # never route via a proxy

    # ---- context manager ------------------------------------------------
    def __enter__(self) -> LlamaServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # ---- command line ---------------------------------------------------
    def _help_text(self) -> str:
        if self._supported_flags is None:
            try:
                result = subprocess.run([*self._command_prefix(), "--help"], capture_output=True,
                                        text=True, timeout=30, errors="replace")
                self._supported_flags = result.stdout + result.stderr
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ServerStartError(f"Cannot run llama-server: {error}") from error
        return self._supported_flags

    def supports(self, flag: str) -> bool:
        help_text = self._help_text()
        return any(token.strip(",") == flag for token in help_text.split())

    def _command_prefix(self) -> list[str]:
        command = list(self.config.server_command)
        # Windows won't start a program from a relative path, so resolve it.
        if command and not os.path.isabs(command[0]) and Path(command[0]).exists():
            command[0] = str(Path(command[0]).resolve())
        return command

    def build_command(self) -> list[str]:
        cfg = self.config
        command = [*self._command_prefix(),
                   "--model", str(cfg.model_path),
                   "--host", cfg.host, "--port", str(cfg.port),
                   "--threads", str(cfg.threads), "--threads-batch", str(cfg.threads),
                   "--ctx-size", str(cfg.context_tokens),
                   "--parallel", "1"]
        optional = [(LEAN_MEMORY_FLAGS[0], LEAN_MEMORY_FLAGS[1]), (LEAN_MEMORY_FLAGS[2], LEAN_MEMORY_FLAGS[3]),
                    ("--no-webui", None), ("--jinja", None)]
        if not cfg.model.repack:
            optional.append(("--no-repack", None))
        for flag, value in optional:
            if self.supports(flag):
                command += [flag] if value is None else [flag, value]
            else:
                logger.warning("llama-server does not support %s; continuing without it", flag)
        return command + list(cfg.extra_args)

    # ---- lifecycle -------------------------------------------------------
    def _port_open(self) -> bool:
        # On Windows a connection to a closed port takes ~2 s to be refused, so probe
        # with a short timeout before doing any HTTP request. A local listener accepts instantly.
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=0.2):
                return True
        except OSError:
            return False

    def _health(self) -> int | None:
        if not self._port_open():
            return None
        try:
            return self._client.get("/health", timeout=2.0).status_code
        except httpx.HTTPError:
            return None

    def _running_model_path(self) -> str | None:
        try:
            return self._client.get("/props", timeout=2.0).json().get("model_path")
        except (httpx.HTTPError, json.JSONDecodeError, AttributeError):
            return None

    def is_running(self) -> bool:
        """True when *this* object's server (owned or attached) is up and healthy."""
        if not (self._owned or self._attached):
            return False
        if self._owned and (self._process is None or self._process.poll() is not None):
            return False
        return self._health() == 200

    def start(self) -> float:
        """Start (or attach to) the server and wait until the model is loaded. Returns seconds taken."""
        with self._lock:
            if self.is_running():
                return 0.0
            if self._owned:  # our process died: clean up before starting a new one
                self._owned = False
                self._process = None
                self._close_log()
            if not self.config.model_path.is_file():
                raise ModelNotFoundError(
                    f"Model file not found: {self.config.model_path}\n"
                    f"Download {self.config.model.name} from {self.config.model.source_url}")

            status = self._health()
            if status is not None:
                running = self._running_model_path()
                if running and Path(running).resolve() == self.config.model_path:
                    logger.info("Reusing llama-server already running on port %s", self.config.port)
                    self._attached = True
                    return self.wait_until_ready()
                raise PortInUseError(
                    f"Port {self.config.port} is already used by another program "
                    f"{'(a llama-server with a different model)' if running else ''}. "
                    "Choose another port with --port or EDUAI_PORT.")

            self.config.log_dir.mkdir(parents=True, exist_ok=True)
            self._log_path = self.config.log_dir / "llama-server.log"
            self._log_file = open(self._log_path, "w", encoding="utf-8", errors="replace")
            command = self.build_command()
            logger.info("Starting llama-server: %s", " ".join(command))
            kwargs = {}
            if os.name == "nt":
                # Own process group: a Ctrl+C in the console stops an answer, not the server.
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:  # pragma: no cover - Linux only
                kwargs["start_new_session"] = True
                kwargs["preexec_fn"] = _linux_parent_death_signal
            try:
                self._process = subprocess.Popen(command, stdout=self._log_file, stderr=subprocess.STDOUT,
                                                 stdin=subprocess.DEVNULL, **kwargs)
            except OSError as error:
                self._close_log()
                raise ServerStartError(f"Could not launch llama-server: {error}") from error
            self._owned = True
            self._job = _kill_with_parent(self._process.pid)
            if not self._atexit_registered:
                atexit.register(self.stop)  # normal interpreter exit; the job object covers crashes
                self._atexit_registered = True
        try:
            return self.wait_until_ready()
        except Exception:
            self.stop()
            raise

    def wait_until_ready(self, timeout: float | None = None) -> float:
        timeout = self.config.startup_timeout_s if timeout is None else timeout
        started = time.perf_counter()
        while time.perf_counter() - started < timeout:
            if self._owned and self._process.poll() is not None:
                raise ServerStartError(
                    f"llama-server exited during startup (code {self._process.returncode}).\n"
                    f"Last log lines:\n{self.log_tail()}")
            if self._health() == 200:
                return time.perf_counter() - started
            time.sleep(0.2)
        raise ServerStartError(f"llama-server did not become ready within {timeout:.0f} s.\n{self.log_tail()}")

    def stop(self) -> None:
        with self._lock:
            process, self._process = self._process, None
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if self._job is not None:
                import ctypes
                ctypes.WinDLL("kernel32").CloseHandle(self._job)
                self._job = None
            self._owned = False
            self._attached = False
            self._close_log()

    def close(self) -> None:
        self.stop()
        self._client.close()

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def log_tail(self, lines: int = LOG_TAIL_LINES) -> str:
        path = self._log_path
        if not path or not path.exists():
            return "(no log)"
        if self._log_file is not None:
            self._log_file.flush()
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    # ---- chat -------------------------------------------------------------
    def _payload(self, messages, max_tokens, temperature, stream) -> dict:
        cfg = self.config
        payload = {
            "messages": validate_messages(messages),
            "max_tokens": max_tokens or cfg.max_tokens,
            "temperature": cfg.temperature if temperature is None else temperature,
            "top_p": cfg.top_p,
            "stream": stream,
        }
        if cfg.model.disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        return payload

    def _ensure_running(self) -> None:
        if self._owned and (self._process is None or self._process.poll() is not None):
            code = self._process.returncode if self._process else None
            raise ServerNotRunningError(
                f"llama-server is not running (exit code {code}). Last log lines:\n{self.log_tail()}")
        if not self._owned and not self._attached:
            raise ServerNotRunningError("llama-server has not been started; call start() first")

    def chat(self, messages: Iterable[dict], max_tokens: int | None = None,
             temperature: float | None = None) -> ChatResult:
        """Send a conversation and wait for the complete reply."""
        self._ensure_running()
        payload = self._payload(messages, max_tokens, temperature, stream=False)
        try:
            response = self._client.post("/v1/chat/completions", json=payload)
        except httpx.TimeoutException as error:
            raise InferenceTimeoutError(f"No reply within {self.config.request_timeout_s:.0f} s") from error
        except httpx.HTTPError as error:
            self._ensure_running()  # turns a crashed server into a clear error
            raise InferenceError(f"Could not reach llama-server: {error}") from error
        if response.status_code != 200:
            raise _error_from_response(response)
        try:
            data = response.json()
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, AttributeError) as error:
            raise InferenceError(f"Malformed reply from llama-server: {response.text[:300]}") from error
        usage, timings = data.get("usage") or {}, data.get("timings") or {}
        return ChatResult(text=text, finish_reason=choice.get("finish_reason"),
                          prompt_tokens=usage.get("prompt_tokens"),
                          completion_tokens=usage.get("completion_tokens"),
                          tokens_per_second=timings.get("predicted_per_second"))

    def stream_chat(self, messages: Iterable[dict], max_tokens: int | None = None,
                    temperature: float | None = None, cancel_event: threading.Event | None = None) -> ChatStream:
        """Send a conversation and receive the reply in chunks as it is generated (SSE)."""
        self._ensure_running()
        payload = self._payload(messages, max_tokens, temperature, stream=True)
        stream = ChatStream(_chunks=iter(()), cancel_event=cancel_event or threading.Event())
        stream._chunks = self._iter_stream(payload, stream)
        return stream

    def _iter_stream(self, payload: dict, stream: ChatStream) -> Iterator[str]:
        try:
            with self._client.stream("POST", "/v1/chat/completions", json=payload) as response:
                stream._response = response
                if response.status_code != 200:
                    response.read()
                    raise _error_from_response(response)
                for line in response.iter_lines():
                    if stream.cancel_event.is_set():
                        stream.cancelled = True
                        return
                    if not line.startswith("data:"):
                        continue  # SSE comments / keep-alives
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError as error:
                        raise InferenceError(f"Malformed stream event: {data[:200]}") from error
                    if "error" in event:
                        raise InferenceError(f"llama-server error: {event['error']}")
                    choices = event.get("choices") or []
                    if choices:
                        piece = (choices[0].get("delta") or {}).get("content")
                        stream.finish_reason = choices[0].get("finish_reason") or stream.finish_reason
                        if piece:
                            stream.text += piece
                            yield piece
                    timings = event.get("timings")
                    if timings:
                        stream.tokens_per_second = timings.get("predicted_per_second")
        except httpx.TimeoutException as error:
            raise InferenceTimeoutError(f"Stream stalled for {self.config.request_timeout_s:.0f} s") from error
        except (httpx.StreamClosed, httpx.ReadError, httpx.RemoteProtocolError) as error:
            if stream.cancel_event.is_set():
                stream.cancelled = True  # we closed it on purpose
                return
            self._ensure_running()
            raise InferenceError(f"Stream interrupted: {error}") from error
        except GeneratorExit:
            stream.cancelled = True  # caller stopped iterating early
            raise
        finally:
            stream._response = None


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    from eduai.config import config_from_env
    logging.basicConfig(level=logging.INFO)
    with LlamaServer(config_from_env(sys.argv[1] if len(sys.argv) > 1 else None)) as srv:
        print(srv.chat([{"role": "user", "content": "In one sentence, what is a variable?"}]).text)
