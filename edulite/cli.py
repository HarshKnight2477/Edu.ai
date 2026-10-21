"""Terminal chat with the local model.

    python -m edulite                    # default model (Qwen3.5-2B)
    python -m edulite --model lite       # Qwen3.5-0.8B for low-memory PCs
    python -m edulite --list-models
    python -m edulite --web              # browser interface at http://127.0.0.1:8770
    python -m edulite --level intermediate

Commands during a chat: /help, /reset, /info, /level, /mode, /notes, /exit.
Ctrl+C stops the current answer; Ctrl+C at the prompt (or /exit) quits.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from edulite import __version__
from edulite.config import REGISTRY, config_from_env, model_status
from edulite.conversation import Conversation
from edulite.inference import (ContextOverflowError, InferenceError, LlamaServer, ModelNotFoundError,
                               ServerNotRunningError, ServerStartError)
from edulite.tutor.engine import AUTO, Tutor
from edulite.tutor.guard import select_guard
from edulite.tutor.prompts import LEVELS, MODE_LABELS

HELP = """Commands:
  /help    show this help
  /reset   start a new conversation (forget earlier messages)
  /info    model, settings and memory use
  /level   beginner | intermediate | advanced   (how detailed answers are)
  /mode    auto | explain | hint | debug | code | quiz | project
  /notes   on | off   (use EduLite's course notes to ground answers)
  /exit    quit (also /quit, or Ctrl+C at the prompt)
Ctrl+C while EduLite is answering stops that answer."""


def list_models(out: TextIO) -> None:
    out.write("Models:\n")
    for key, spec in REGISTRY.items():
        status = model_status(spec)
        state = "installed" if status.installed else f"NOT INSTALLED ({status.problem})"
        out.write(f"  {key:8s} {spec.name:15s} {spec.quantization:7s} ~{spec.peak_ram_mb / 1024:.1f} GB RAM  {state}\n")


@dataclass
class TutorOptions:
    level: str = "beginner"
    mode: str = AUTO
    use_notes: bool = True


def info_text(server: LlamaServer, conversation: Conversation, options: TutorOptions | None = None) -> str:
    cfg = server.config
    lines = [f"Model:    {cfg.model.name} ({cfg.model.quantization}, {cfg.model.license})",
             f"File:     {cfg.model_path}",
             f"Threads:  {cfg.threads}   Context: {cfg.context_tokens} tokens   Max answer: {cfg.max_tokens} tokens",
             f"Server:   {cfg.base_url} (local only), pid {server.pid or 'external'}",
             f"History:  {conversation.exchanges} exchange(s)"]
    if options:
        lines.append(f"Tutor:    level {options.level}, mode {options.mode}, "
                     f"course notes {'on' if options.use_notes else 'off'}")
    if server.pid:
        try:
            import psutil
            rss = psutil.Process(server.pid).memory_info().rss / 2**20
            lines.append(f"RAM:      {rss:,.0f} MB used by the model server")
        except Exception:  # psutil missing or process gone
            pass
    return "\n".join(lines)


def answer(server: LlamaServer, conversation: Conversation, out: TextIO, show_stats: bool,
           tutor: Tutor | None = None, options: TutorOptions | None = None) -> None:
    """Stream one reply to the latest user message, recovering from a full context window."""
    tutor = tutor or Tutor()
    options = options or TutorOptions()
    dropped = 0
    while True:
        prepared = tutor.prepare(conversation.turns, options.level, options.mode, options.use_notes)
        stream = server.stream_chat(prepared.messages)
        started = time.perf_counter()
        try:
            if dropped == 0:
                label = MODE_LABELS[prepared.mode] + (" (auto)" if prepared.detected else "")
                notes = f" · notes: {'; '.join(prepared.sources)}" if prepared.sources else ""
                out.write(f"[{label}{notes}]\n")
            out.write("EduLite: ")
            out.flush()
            # Output checks: hint mode withholds complete solutions; an explicit
            # "one sentence" request is trimmed to that format.
            guard = select_guard(prepared.mode, conversation.turns[-1]["content"])
            shown = []
            for chunk in stream:
                safe = guard.feed(chunk) if guard else chunk
                shown.append(safe)
                out.write(safe)
                out.flush()
            if guard:
                tail = guard.finish()
                shown.append(tail)
                out.write(tail)
        except KeyboardInterrupt:
            stream.cancel()
            out.write("\n[answer stopped]\n\n")
            conversation.undo_last_user()  # a half answer would confuse the next turn
            return
        except ContextOverflowError:
            out.write("\r")
            if conversation.drop_oldest_exchange():
                dropped += 1
                continue
            conversation.undo_last_user()
            out.write("That message is too long for the model's memory. Try a shorter question.\n\n")
            return
        if dropped:
            out.write(f"\n(Older messages were forgotten to make room: {dropped} removed.)")
        conversation.add_assistant("".join(shown))  # what the student saw
        out.write("\n")
        if stream.finish_reason == "length":
            out.write(f"  (Answer cut off at the {server.config.max_tokens}-token limit. "
                      "Type 'continue' to get the rest.)\n")
        if show_stats:
            elapsed = time.perf_counter() - started
            speed = f", {stream.tokens_per_second:.1f} tok/s" if stream.tokens_per_second else ""
            out.write(f"  [{elapsed:.1f} s{speed}]\n")
        out.write("\n")
        return


def handle_tutor_command(command: str, options: TutorOptions, out: TextIO) -> bool:
    """/level, /mode and /notes. Returns True if the command was one of them."""
    name, _, value = command.partition(" ")
    value = value.strip().lower()
    if name == "/level":
        if value in LEVELS:
            options.level = value
            out.write(f"Level set to {value}.\n\n")
        else:
            out.write(f"Level is {options.level}. Choose: {', '.join(LEVELS)}\n\n")
        return True
    if name == "/mode":
        if value == AUTO or value in MODE_LABELS:
            options.mode = value
            out.write(f"Mode set to {value}.\n\n")
        else:
            out.write(f"Mode is {options.mode}. Choose: auto, {', '.join(MODE_LABELS)}\n\n")
        return True
    if name == "/notes":
        if value in ("on", "off"):
            options.use_notes = value == "on"
            out.write(f"Course notes {value}.\n\n")
        else:
            out.write(f"Course notes are {'on' if options.use_notes else 'off'}. Use /notes on or /notes off.\n\n")
        return True
    return False


def chat_loop(server: LlamaServer, conversation: Conversation, read_input: Callable[[str], str],
              out: TextIO, show_stats: bool = False, options: TutorOptions | None = None,
              tutor: Tutor | None = None) -> None:
    options = options or TutorOptions()
    tutor = tutor or Tutor()
    while True:
        try:
            message = read_input("Student: ").strip()
        except (EOFError, KeyboardInterrupt):
            out.write("\nGoodbye!\n")
            return
        if not message:
            continue
        command = message.lower()
        if command in ("/exit", "/quit", "/bye"):
            out.write("Goodbye!\n")
            return
        if command == "/help":
            out.write(HELP + "\n\n")
            continue
        if command == "/reset":
            conversation.reset()
            out.write("Started a new conversation.\n\n")
            continue
        if command == "/info":
            out.write(info_text(server, conversation, options) + "\n\n")
            continue
        if handle_tutor_command(command, options, out):
            continue
        if command.startswith("/"):
            out.write(f"Unknown command {message.split()[0]}. Type /help.\n\n")
            continue

        conversation.add_user(message)
        try:
            answer(server, conversation, out, show_stats, tutor, options)
        except ServerNotRunningError:
            out.write("\nThe model server stopped unexpectedly. Restarting it...\n")
            conversation.undo_last_user()
            try:
                server.start()
                out.write("Restarted. Please ask again.\n\n")
            except InferenceError as error:
                out.write(f"Could not restart: {error}\n")
                return
        except InferenceError as error:
            conversation.undo_last_user()
            out.write(f"\nSorry, something went wrong: {error}\n\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edulite", description="EduLite: offline AI tutor (terminal chat)")
    parser.add_argument("--model", choices=list(REGISTRY), help="model to use (default: default)")
    parser.add_argument("--threads", type=int, help="CPU threads (default: physical cores, max 8)")
    parser.add_argument("--ctx", type=int, help="context length in tokens (default: 4096)")
    parser.add_argument("--max-tokens", type=int, help="maximum answer length in tokens (default: 1024)")
    parser.add_argument("--port", type=int, help="local port for the model server (default: 8765)")
    parser.add_argument("--stats", action="store_true", help="show time and speed after each answer")
    parser.add_argument("--level", choices=list(LEVELS), default="beginner", help="student level (default: beginner)")
    parser.add_argument("--no-notes", action="store_true", help="don't use the course notes")
    parser.add_argument("--web", action="store_true", help="open the web interface instead of the terminal chat")
    parser.add_argument("--web-port", type=int, default=8770, help="port for the web interface (default: 8770)")
    parser.add_argument("--no-browser", action="store_true", help="with --web: don't open a browser window")
    parser.add_argument("--list-models", action="store_true", help="show available models and exit")
    parser.add_argument("--verbose", action="store_true", help="log server commands and events")
    parser.add_argument("--version", action="version", version=f"EduLite {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model output may contain any Unicode
    out = sys.stdout
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(message)s")

    if args.list_models:
        list_models(out)
        return 0

    try:
        config = config_from_env(args.model).with_overrides(
            threads=args.threads, context_tokens=args.ctx, max_tokens=args.max_tokens, port=args.port)
    except ValueError as error:
        out.write(f"{error}\n")
        return 2

    if args.web:
        from edulite.web.server import run
        run(config, port=args.web_port, open_browser=not args.no_browser, explicit_model=args.model is not None)
        return 0

    out.write(f"EduLite {__version__}: offline AI tutor\n")
    out.write(f"Loading {config.model.name} ({config.threads} threads, context {config.context_tokens})... ")
    out.flush()
    server = LlamaServer(config)
    try:
        seconds = server.start()
    except ModelNotFoundError as error:
        out.write(f"\n{error}\n\n")
        list_models(out)
        return 1
    except ServerStartError as error:
        out.write(f"\nCould not start the model server:\n{error}\n")
        return 1
    out.write(f"ready in {seconds:.1f} s.\n")
    out.write("Ask a question about programming or AI. Type /help for commands.\n\n")
    try:
        chat_loop(server, Conversation(), input, out, show_stats=args.stats,
                  options=TutorOptions(level=args.level, use_notes=not args.no_notes))
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
