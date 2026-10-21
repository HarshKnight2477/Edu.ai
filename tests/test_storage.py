from eduai.storage import Store, make_title


def test_conversation_lifecycle(tmp_path):
    store = Store(tmp_path / "chats.db")
    first = store.create_conversation()
    second = store.create_conversation()
    assert first.title == "New chat"
    store.add_message(first.id, "user", "How do   loops work in Python?")
    assert store.get_conversation(first.id).title == "How do loops work in Python?"
    assert [c.id for c in store.list_conversations()][0] == first.id  # most recently active first
    assert store.rename_conversation(second.id, "  Sorting  ")
    assert store.get_conversation(second.id).title == "Sorting"
    assert store.delete_conversation(first.id) and not store.delete_conversation(first.id)
    assert store.messages(first.id) == []  # messages deleted with their conversation
    store.close()


def test_messages_round_trip_and_persist(tmp_path):
    path = tmp_path / "chats.db"
    store = Store(path)
    c = store.create_conversation()
    store.add_message(c.id, "user", "hi")
    store.add_message(c.id, "assistant", "hello", model="default", stopped=True,
                      stats={"seconds": 1.5, "finish_reason": None})
    store.close()

    reopened = Store(path)  # history survives a restart
    messages = reopened.messages(c.id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].stopped and messages[1].stats["seconds"] == 1.5 and messages[1].model == "default"
    assert reopened.get_conversation(c.id).title == "hi"
    reopened.close()


def test_title_only_set_from_first_question(tmp_path):
    store = Store(tmp_path / "chats.db")
    c = store.create_conversation()
    store.add_message(c.id, "user", "first question")
    store.add_message(c.id, "user", "second question")
    assert store.get_conversation(c.id).title == "first question"
    store.close()


def test_settings(tmp_path):
    store = Store(tmp_path / "chats.db")
    assert store.get_settings() == {}
    store.save_settings({"model": "lite", "max_tokens": 512})
    store.save_settings({"max_tokens": 256})
    assert store.get_settings() == {"model": "lite", "max_tokens": 256}
    store.close()


def test_make_title_shortens():
    assert make_title("short") == "short"
    long = make_title("word " * 40)
    assert len(long) <= 60 and long.endswith("…")


def test_legacy_database_is_migrated(tmp_path, monkeypatch):
    import eduai.storage as storage
    new, old = tmp_path / "eduai.db", tmp_path / "edulite.db"
    monkeypatch.setattr(storage, "DEFAULT_DB_PATH", new)
    monkeypatch.setattr(storage, "LEGACY_DB_PATH", old)
    legacy = Store(old)
    c = legacy.create_conversation()
    legacy.add_message(c.id, "user", "kept from before the rename")
    legacy.close()
    migrated = Store(new)
    assert migrated.messages(c.id)[0].content == "kept from before the rename" and not old.exists()
    migrated.close()


def test_old_environment_variables_still_work(monkeypatch):
    from eduai.config import config_from_env
    monkeypatch.delenv("EDUAI_THREADS", raising=False)
    monkeypatch.setenv("EDULITE_THREADS", "3")
    assert config_from_env().threads == 3
