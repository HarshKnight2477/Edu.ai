# EduLite — Milestone 3 Report: Chat Interface

Date: 2026-10-21 · Status: **complete** · Builds on [milestone-2-report.md](milestone-2-report.md)

## Objective

From the Milestone 1 plan: *a FastAPI backend, a static web UI, chat history in SQLite, and settings (model, context, max tokens). Done when EduLite is usable in a browser on localhost and history persists.*

## How to run

```bash
pip install -r requirements-dev.txt
python -m edulite --web                 # opens http://127.0.0.1:8770
python -m edulite --web --no-browser --web-port 9000
python -m edulite                       # the terminal chat from Milestone 2 still works
```

## What was built

| File | Purpose |
|---|---|
| `edulite/storage.py` | SQLite store (`data/edulite.db`): conversations, messages (with model, stats and a "stopped" flag), saved settings |
| `edulite/model_manager.py` | Owns the single model server: loading / ready / error state, settings validation, restart on model, context or thread changes, refuses changes mid-answer |
| `edulite/web/app.py` | FastAPI app: status, settings, conversation CRUD, streamed answers (SSE), stop, localhost-only protection |
| `edulite/web/server.py` | Launcher: restores saved settings, falls back to an installed model, binds 127.0.0.1, opens the browser |
| `edulite/web/static/` | The UI: `index.html`, `app.css`, `app.js`, `markdown.js`, plus vendored highlight.js 11.12.0 (BSD-3) — **166 KB in total, no build step, no CDN** |
| `tests/test_storage.py`, `tests/test_web.py`, `tests/js/markdown.test.js` | 20 new tests (58 in the whole suite) |

## Features

- **Chat:** answers stream word by word, rendered as Markdown with syntax-highlighted code blocks and Copy buttons. Enter sends; Shift+Enter adds a new line.
- **Stop:** halts generation immediately. The partial answer is kept, marked *stopped*, and left out of the model's context for the next turn.
- **History:** a sidebar lists chats, most recently active first. Each chat is named after its first question and can be renamed or deleted. Everything survives restarts.
- **Settings:** model (installed ones only, with RAM estimates and a one-line note), context length (2K / 4K / 8K), maximum answer length, CPU threads, and creativity (temperature).
  - Changing the model, context or threads restarts the model server; answer length and temperature apply instantly.
  - Settings are remembered for the next launch.
- **Status:** the current model and its live RAM use, a "Loading…" state while it starts, and a clear error state with the reason if it fails.
- **Honest notices:** answers that hit the length limit show *"cut off: ask it to continue"*; when old messages had to be left out to fit, the answer says how many. A permanent hint reminds students that EduLite can make mistakes.
- **Works offline, in light and dark mode, and at phone width.**

## Privacy and security

- **Both servers listen on 127.0.0.1 only.** Verified: ports 8770 (web) and 8765 (model).
- **Host-header check:** requests addressed to any name other than `localhost` / `127.0.0.1` / `::1` are rejected (400). This blocks DNS-rebinding attacks, where a malicious website points its own domain at 127.0.0.1.
- **Cross-site requests blocked:** any change request carrying another website's `Origin` gets 403. Verified live: a cross-site attempt to change the model was refused.
- **Content-Security-Policy** `default-src 'self'`: the page can't load or send anything to other sites.
- **XSS-safe rendering:** model output is placed into the page with `textContent` only. The one exception is highlight.js's output, which escapes its input itself. Tests confirm that HTML written by the model stays plain text.
- **Chats stay in `data/edulite.db` on the student's computer** (git-ignored). Nothing is sent anywhere.

## Testing

```
58 passed   (Milestone 2's 38 + 20 new)
```

- **Storage:** CRUD, cascade delete, persistence across reopen, automatic titles, settings, ordering.
- **Web API** (with the fake model server):
  - streaming events and saved messages, with history sent to the model;
  - Stop saves the partial answer and leaves it out of the next context;
  - busy refusal (409), context trimming that keeps the saved history intact, over-long message rejected and removed;
  - model-not-ready (503) and startup-error reporting;
  - settings validation, per-request settings applied without a restart, restarts on model/context change, settings refused mid-answer;
  - host and origin protection, CSP header.
- **Markdown (Node):** code fences, including unfinished ones while streaming; headings, lists, tables, quotes and inline styles; `snake_case` and `2 * 3 * 4` aren't mistaken for italics; HTML stays text.

**Real-model check in a browser** (Qwen3.5-2B; the built-in browser pane in phone-width layout):

| Check | Result |
|---|---|
| Startup | Model ready in 1.6 s; status shows *Qwen3.5-2B · 1.4 GB RAM* |
| Palindrome question | Answer streamed at 21.7 tok/s (16.5 s); headings, 2 Python code blocks (12 highlighted tokens), Copy buttons, bullet list; chat named automatically; no console errors |
| Stop | Long answer stopped at 92 words, *stopped* badge shown, Send button back |
| Restart persistence | Web server killed and restarted, page reloaded: both exchanges and the *stopped* badge restored; no orphaned model server |
| Settings | Switched to Qwen3.5-0.8B from the dialog: restarted, status updated to 1.0 GB, setting saved; switched back. Only one model server ever running |
| Security from outside | Cross-site settings change → 403; both ports bound to 127.0.0.1 |

## Resource use

| Component | Memory |
|---|---|
| Model server (Qwen3.5-2B) | 1,393 MB |
| Web app (Python + FastAPI + uvicorn) | 58 MB (+4 MB launcher stub) |
| UI files | 166 KB on disk |

The interface adds about **4%** to EduLite's memory use. A browser tab adds its own few hundred MB, which matters on 4 GB PCs. That's why the terminal chat remains available and a lighter desktop window is an option for later.

## Problems found and fixed

| Problem | How found | Fix |
|---|---|---|
| **The "busy" lock could leak.** It was taken before streaming began, so a browser disconnecting at the wrong moment would have left EduLite "busy" forever | Code review while writing the endpoint | The lock and the saving of the user's message moved inside the stream, where `finally` always releases the lock |
| **Chat order could be wrong.** Windows clock timestamps can be identical for events milliseconds apart, so a just-used chat could sort below a newer empty one | Storage test failed even after switching to microsecond timestamps | Ordering by an always-increasing activity counter; timestamps kept for display |
| **The JavaScript tests silently didn't run.** Node 24 treated the `tests/js` folder argument as a file | The wrapper test failed with "test failed" and 0 tests run | The test files are now passed explicitly; all 7 run |
| **Tests couldn't use a fake model.** The manager always looked models up in the real registry and folder | While writing the API tests | The registry and models folder are now injectable |
| **A CLI edit silently didn't apply** (an escaping mismatch in an automated replace) | Verification grep after the edit | Applied by hand and re-verified |

## Known limitations

- **Answer quality isn't tuned yet.** For example, the palindrome function's docstring claims it handles spaces, but `.strip()` only removes them from the ends. Tutoring prompts (Milestone 4) and evaluation (Milestone 8) address this, and the sandboxed verifier (Milestone 7) will catch code claims like this one.
- **One answer at a time** across all tabs (`--parallel 1`, by design for memory). A second request gets a clear "already answering" message.
- **No regenerate or edit-message buttons yet.** They're natural additions once tutoring modes exist.
- **Rename and delete use the browser's built-in prompt/confirm dialogs.** They work, but they're plain.
- **No automated end-to-end browser test.** The UI was checked manually in a browser, and the logic is covered by API and renderer tests. The browser pane couldn't take screenshots while the app window was hidden, so the checks used the page's text and DOM.
- **Linux untested** for the web app as well. The code is portable; testing it is part of Milestone 9.

## Definition of done

- [x] FastAPI backend, local only, with streamed answers
- [x] Static web UI: chat, history sidebar, settings, Markdown + code highlighting, works offline
- [x] Chat history in SQLite, persists across restarts (verified)
- [x] Settings for model, context and max tokens (plus threads and temperature), validated, remembered, restart only when needed
- [x] Usable in a browser on localhost with the real model (verified)
- [x] Tests: 58 passing
