import io
from dataclasses import replace

import pytest

from edulite import cli
from edulite.config import REGISTRY
from edulite.conversation import Conversation


def run_session(server, inputs, conversation=None, out=None):
    feed = iter(inputs)

    def read_input(prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError

    out = out or io.StringIO()
    conversation = conversation or Conversation()
    cli.chat_loop(server, conversation, read_input, out, show_stats=True)
    return out.getvalue(), conversation


# ---------------------------------------------------------------- conversation

def test_conversation_history_and_trimming():
    c = Conversation(system_prompt="sys")
    c.add_user("q1"); c.add_assistant("a1"); c.add_user("q2")
    assert [m["role"] for m in c.messages()] == ["system", "user", "assistant", "user"]
    assert c.drop_oldest_exchange() and [t["content"] for t in c.turns] == ["q2"]
    assert not c.drop_oldest_exchange()  # the latest question is never dropped
    c.undo_last_user()
    assert c.turns == []


# ------------------------------------------------------------------ chat loop

def test_multi_turn_chat_and_commands(make_config, servers):
    server = servers(make_config())
    server.start()
    output, conversation = run_session(server, ["", "What is a variable?", "/info", "And a loop?",
                                                "/help", "/oops", "/reset", "/exit"])
    assert output.count("EduLite: echo: w0 w1 w2 w3 w4") == 2  # two streamed answers
    assert "History:  1 exchange(s)" in output  # /info after the first question
    assert "Commands:" in output and "Unknown command /oops" in output
    assert "Started a new conversation." in output and output.rstrip().endswith("Goodbye!")
    assert conversation.turns == []  # reset cleared the two exchanges


def test_end_of_input_exits_cleanly(make_config, servers):
    server = servers(make_config())
    server.start()
    output, _ = run_session(server, ["hi"])
    assert "Goodbye!" in output


def test_ctrl_c_stops_the_answer_but_not_the_chat(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_STREAM_WORDS", "100")
    server = servers(make_config())
    server.start()

    class InterruptingOutput(io.StringIO):
        """Simulates Ctrl+C arriving while the third chunk is printed."""
        chunks = 0

        def write(self, s):
            if s.startswith(" w"):
                self.chunks += 1
                if self.chunks == 3:
                    raise KeyboardInterrupt
            return super().write(s)

    output, conversation = run_session(server, ["long question", "/exit"], out=InterruptingOutput())
    assert "[answer stopped]" in output
    assert conversation.turns == []  # the cancelled question is not kept
    assert server.chat([{"role": "user", "content": "still there?"}]).text == "echo: still there?"


def test_full_context_drops_oldest_messages(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "1200")
    server = servers(make_config())
    server.start()
    conversation = Conversation(system_prompt="")
    for i in range(3):
        conversation.add_user("x" * 300); conversation.add_assistant("y" * 300)
    output, conversation = run_session(server, ["new question", "/exit"], conversation)
    assert "EduLite: echo: w0" in output
    assert "Older messages were forgotten" in output
    assert conversation.turns[-2]["content"] == "new question"


def test_message_too_long_for_context(make_config, servers, monkeypatch):
    monkeypatch.setenv("FAKE_MAX_CHARS", "50")
    server = servers(make_config())
    server.start()
    output, conversation = run_session(server, ["z" * 500, "/exit"], Conversation(system_prompt=""))
    assert "too long" in output and conversation.turns == []


def test_server_crash_is_recovered_by_restart(make_config, servers, monkeypatch):
    server = servers(make_config())
    server.start()
    server._process.kill()  # simulate an unexpected crash
    server._process.wait()
    output, _ = run_session(server, ["hello", "hello again", "/exit"])
    assert "stopped unexpectedly. Restarting" in output and "Restarted" in output
    assert output.count("EduLite: echo: w0") == 1  # the retry after the restart was answered


def test_main_reports_missing_model(monkeypatch, capsys, tmp_path):
    missing = replace(REGISTRY["default"], file="not-downloaded.gguf")
    monkeypatch.setitem(cli.REGISTRY, "default", missing)
    monkeypatch.setattr("edulite.config.REGISTRY", cli.REGISTRY)
    assert cli.main([]) == 1
    output = capsys.readouterr().out
    assert "Model file not found" in output and "Models:" in output


def test_list_models(capsys):
    assert cli.main(["--list-models"]) == 0
    assert "Qwen3.5-2B" in capsys.readouterr().out
