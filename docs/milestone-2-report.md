# Edu.ai — Milestone 2 Report: Local Inference Engine

Date: 2026-10-21 · Status: **complete** · Builds on [milestone-1-report.md](milestone-1-report.md)

## Objective

Make the selected model run reliably on the CPU and answer messages locally. This milestone covers a managed `llama-server` process, a chat client with streaming, and a terminal chat. Frontend, tutoring prompts and retrieval are later milestones.

## What was built

| File | Purpose |
|---|---|
| `eduai/config.py` | Model registry (default / lite / quality), exact file sizes for download checks, `InferenceConfig`, `EDUAI_*` environment overrides, thread auto-detection |
| `eduai/inference.py` | `LlamaServer`: start / attach / health wait / stop, flag verification, `chat()`, `stream_chat()` with cancellation, typed errors |
| `eduai/conversation.py` | Conversation history with a short tutor system prompt and oldest-first trimming |
| `eduai/cli.py`, `eduai/__main__.py` | Terminal chat: `python -m eduai` |
| `tests/fake_llama_server.py` | Model-free stand-in for llama-server, able to simulate loading, crashes, timeouts, bad replies and a full context |
| `tests/test_inference.py`, `tests/test_cli.py` | 34 tests of lifecycle, chat, streaming and CLI behaviour |
| `tests/test_real_model.py` | 4 end-to-end tests with the real runtime and lite model (skipped if not installed) |
| `benchmarks/measure_inference.py` | End-to-end startup / RAM / latency measurement |
| `pyproject.toml`, `requirements*.txt` | Dependencies (`httpx`, `psutil`; `pytest` for development) |

Nothing new was downloaded. The milestone reuses the llama.cpp build b11780 in `runtime/llama-cpu/` and the models in `models/`, whose sizes are verified against the registry.

## How to run

```bash
.venv\Scripts\activate                 # Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m eduai                      # default model, Qwen3.5-2B
python -m eduai --model lite         # Qwen3.5-0.8B
python -m eduai --list-models
python -m eduai --stats --threads 4 --ctx 2048 --max-tokens 512
python -m pytest
```

In the chat: `/help`, `/reset`, `/info`, `/exit`. **Ctrl+C stops the current answer**; Ctrl+C at the prompt quits.

## Design decisions

- **Model server as a separate process** (`llama-server`), reached through its OpenAI-compatible API at `127.0.0.1` only. Requests never leave the machine; the HTTP client ignores proxy settings.
- **Lean memory flags** from Milestone 1: `--cache-ram 0 --ctx-checkpoints 1`, plus `--no-repack` for Q4_K_M models only (the Q4_0 lite model keeps repacking, which speeds up its prompt reading). Each optional flag is checked against `llama-server --help` and skipped with a warning if unsupported.
- **`--no-webui`**: the server's built-in web page is disabled, leaving the API only.
- **Thinking disabled** (`enable_thinking: false`) for the hybrid-reasoning models, so answers start immediately.
- **Single slot** (`--parallel 1`): one student, one conversation, minimum memory.
- **No duplicate servers.** If the port already serves the *same* model file (checked through `/props`), Edu.ai attaches to it. A different model or another program on the port is refused with a clear message.
- **The server can't be orphaned.** It runs in its own process group, so Ctrl+C reaches the chat, not the server. On Windows it's also placed in a Job object that kills it if Edu.ai dies; on Linux the parent-death signal does the same.
- **A full context is recovered automatically.** When llama-server reports `exceed_context_size_error`, the CLI drops the oldest exchange and retries, and tells the student it did so.

## Test results

```
38 passed in 37.6 s   (34 with the fake server, 4 with the real llama.cpp runtime + Qwen3.5-0.8B)
```

What the tests cover:
- **Configuration:** registry matches Milestone 1, partial-download detection, environment overrides.
- **Command line:** lean flags present, `--no-repack` only for Q4_K_M, binds 127.0.0.1, unsupported flags skipped.
- **Lifecycle:**
  - waits through the 503 "Loading model" phase;
  - no duplicate launch;
  - attaches to a matching server and refuses a mismatched one;
  - missing model file reported with its download URL;
  - startup crash reported with log lines;
  - startup timeout kills the process.
- **Chat:** history and settings sent exactly; malformed reply, HTTP 500, context overflow, request timeout and mid-chat crash all give typed errors.
- **Streaming:**
  - chunks arrive incrementally;
  - cancelling from another thread, through an event, or by breaking out of the loop all work;
  - the server stays healthy after cancellation;
  - overflow is reported while streaming.
- **CLI:**
  - multi-turn chat and all commands;
  - Ctrl+C stops an answer without ending the chat;
  - oldest messages trimmed when the context is full, and an over-long message rejected;
  - automatic restart after a server crash;
  - missing-model message.
- **Real model:**
  - correct arithmetic answer, and follow-up questions use the history;
  - after cancelling a stream, the next request runs promptly;
  - the server listens only on 127.0.0.1.

**Also verified by hand:**
- **Hard-kill check:** after hard-killing the Edu.ai Python process (so no cleanup code ran), the llama-server process was gone a second later. That confirms the Job object works.
- **A real CLI session with Qwen3.5-2B:** two turns, where the follow-up correctly built on the first answer, then `/info` (1,457 MB server RAM), `/reset` and `/exit`.

## Measurements

Intel i7-14650HX laptop, CPU only, lean settings, 3 tutoring questions per model, answers capped at 300 tokens (`benchmarks/results/inference_m2.json`):

| Model | Threads | Startup | RAM after load | Peak RAM | First text | Speed | Typical answer |
|---|---|---|---|---|---|---|---|
| **Qwen3.5-2B** (default) | 4 | 1.6 s | 1,393 MB | **1,433 MB** | 566 ms | 20.9 tok/s | 14.7 s |
| Qwen3.5-2B | 8 | 1.6 s | 1,394 MB | 1,436 MB | 375 ms | 20.2 tok/s | 15.1 s |
| Qwen3.5-0.8B (lite) | 4 | 1.8 s | 977 MB | 1,015 MB | 246 ms | 40.4 tok/s | 7.5 s |
| Qwen3.5-0.8B | 8 | 1.4 s | 977 MB | 1,015 MB | 187 ms | 38.2 tok/s | 7.8 s |
| Granite-4.2-3B (quality) | 4 | 2.1 s | 2,375 MB | 2,392 MB | 379 ms | 12.7 tok/s | 23.8 s |
| Granite-4.2-3B | 8 | 1.4 s | 2,375 MB | 2,393 MB | 246 ms | 14.9 tok/s | 20.3 s |

What this shows:
- **RAM matches Milestone 1** (Qwen3.5-2B: 1,433 MB vs 1,448 MB), so the lean settings are applied correctly.
- **Students see text within about half a second**; the full answer takes 7–24 s depending on the model.
- **More threads don't speed up generation.** Going from 4 to 8 left generation speed about the same, because on this CPU generation is limited by memory bandwidth. Extra threads only shorten the wait for the first text. The default (physical cores, capped at 8) is reasonable; low-end PCs with 2–4 cores will use all of them.

## Problems found and fixed during this milestone

| Problem | How it was found | Fix |
|---|---|---|
| **`start()` attached to whatever was on the port**, even a server running a different model or an unrelated program, because the "already running?" check came before the model check | Two failing tests (attach / port-in-use) | `is_running()` now only reports *this object's* server; foreign servers are checked by model path, and mismatches are refused |
| **Every startup silently waited ~4 s.** On Windows, connecting to a closed port takes ~2 s to fail, and startup made two such checks before launching | All fake-server tests took ~5 s; the suite took 131 s | A 0.2 s socket probe before any HTTP call. The suite dropped to 38 s, and real startups now measure 1.4–2.1 s in total |
| **Windows wouldn't launch the server from a relative path** (`FileNotFoundError`) | First probe of the real server | The binary path is always resolved to an absolute path |
| **Answers stopped at the token limit without saying so** | Real CLI session with a 250-token cap | The CLI now says the answer was cut off and that typing "continue" gets the rest |
| **Test mistake:** the CLI tests expected the fake server's streamed reply to repeat the question | 3 failing CLI tests | Corrected the expectations; the fake server's stream doesn't echo |

## Known limitations

- **Answer quality is not tuned yet.** One real answer from Qwen3.5-2B included odd advice ("Never modify a variable directly without checking if it's safe"). Tutoring prompts, level adaptation and the homework policy are Milestone 4; quality evaluation is Milestone 8.
- **Context trimming is reactive.** The CLI drops old messages only after the server rejects a too-long request. That costs one wasted request in that case, but needs no tokenizer in Python.
- **One conversation at a time** (`--parallel 1`) by design. The web UI in Milestone 3 will reuse the same server.
- **Speeds were measured on a fast CPU.** As in Milestone 1, real low-end PCs will be slower. Milestone 6 measures on real low-end hardware.
- **Linux paths are written but untested here.** The parent-death signal, process group and binary name are implemented, but this milestone only ran on Windows.
- **A cancelled answer is discarded**, and the question is removed from the history to keep the next turn clean. The student re-asks if needed.
- **The milestone prompt arrived truncated** (it ended mid-sentence in the CLI section). CLI features beyond that point were inferred: multi-turn chat, `/reset`, `/help`, `/info`, `/exit`, `--stats`, model and thread flags, and Ctrl+C to stop an answer.

## Definition of done

- [x] Starts the selected model with the existing CPU runtime; no duplicate downloads, no placeholders
- [x] Clean stop; no duplicate processes; startup failures and crashes detected; health wait with timeout
- [x] Server terminated on exit, including a hard crash (verified)
- [x] Registry for the default / lite / quality models, with sizes verified
- [x] Configurable threads, context (default 4096), max tokens, address/port, timeouts; lean memory flags verified against the binary
- [x] Binds to 127.0.0.1 only (verified by test)
- [x] Chat with system/user/assistant messages, caller-supplied history, max tokens, typed errors
- [x] SSE streaming with cancellation and clean handling of interrupted streams
- [x] Terminal chat with multi-turn conversation
- [x] Automated tests: 38 passing
