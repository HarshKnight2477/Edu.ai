"""A stand-in for llama-server used by the tests: same CLI flags and HTTP API, no model.

Behaviour is controlled with environment variables (inherited from the test):
  FAKE_LOAD_SECONDS   time spent "loading" (health returns 503), default 0.3
  FAKE_EXIT_ON_START  exit with this code during startup, after logging an error
  FAKE_MODE           normal | malformed | error500 | slow | crash_on_chat
  FAKE_MAX_CHARS      reply 400 exceed_context_size_error when the prompt is longer
  FAKE_STREAM_WORDS   number of words in a streamed reply (default 5)
  FAKE_CHUNK_DELAY    seconds between streamed chunks (default 0.01)
  FAKE_UNSUPPORTED    comma-separated flags to leave out of --help
  FAKE_RECORD         file to append each request body to (one JSON per line)
"""

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FLAGS = ["--model", "--host", "--port", "--threads", "--threads-batch", "--ctx-size", "--parallel",
         "--cache-ram", "--ctx-checkpoints", "--no-webui", "--jinja", "--no-repack"]


def main():
    if "--help" in sys.argv:
        hidden = set(filter(None, os.getenv("FAKE_UNSUPPORTED", "").split(",")))
        print("usage: llama-server [options]\n" + "\n".join(f"{f}    fake option" for f in FLAGS if f not in hidden))
        return 0

    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9931)
    args, _ = parser.parse_known_args()

    print(f"fake llama-server: loading {args.model}", flush=True)
    if os.getenv("FAKE_EXIT_ON_START"):
        print("error: failed to load model (simulated)", flush=True)
        return int(os.environ["FAKE_EXIT_ON_START"])

    ready_at = time.time() + float(os.getenv("FAKE_LOAD_SECONDS", "0.3"))
    mode = os.getenv("FAKE_MODE", "normal")
    max_chars = int(os.getenv("FAKE_MAX_CHARS", "0"))
    words = int(os.getenv("FAKE_STREAM_WORDS", "5"))
    delay = float(os.getenv("FAKE_CHUNK_DELAY", "0.01"))
    record = os.getenv("FAKE_RECORD")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def _json(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                if time.time() < ready_at:
                    return self._json(503, {"error": {"message": "Loading model", "type": "unavailable_error", "code": 503}})
                return self._json(200, {"status": "ok"})
            if self.path == "/props":
                return self._json(200, {"model_path": os.path.abspath(args.model)})
            self._json(404, {"error": {"message": "not found"}})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if record:
                with open(record, "a", encoding="utf-8") as f:
                    f.write(json.dumps(body) + "\n")
            if mode == "crash_on_chat":
                os._exit(1)
            if mode == "error500":
                return self._json(500, {"error": {"message": "simulated failure", "type": "server_error"}})
            if mode == "slow":
                time.sleep(5)
            prompt_chars = sum(len(m["content"]) for m in body["messages"])
            if max_chars and prompt_chars > max_chars:
                return self._json(400, {"error": {"code": 400, "message": "request exceeds the available context size",
                                                  "type": "exceed_context_size_error",
                                                  "n_prompt_tokens": prompt_chars, "n_ctx": max_chars}})
            last = body["messages"][-1]["content"]
            if not body.get("stream"):
                if mode == "malformed":
                    data = b"this is not json"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    return self.wfile.write(data)
                return self._json(200, {"choices": [{"message": {"role": "assistant", "content": f"echo: {last}"},
                                                      "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": prompt_chars, "completion_tokens": 3},
                                        "timings": {"predicted_per_second": 42.0}})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                pieces = ["echo:"] + [f" w{i}" for i in range(words)]
                for piece in pieces:
                    event = {"choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(delay)
                end = {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                       "timings": {"predicted_per_second": 42.0}}
                self.wfile.write(f"data: {json.dumps(end)}\n\ndata: [DONE]\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # client cancelled
            self.close_connection = True

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
