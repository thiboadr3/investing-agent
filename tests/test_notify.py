from agent.db import DB
from agent.notify import Notifier


class FakeResp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_notifier_discovers_chat_and_dedupes(tmp_path, monkeypatch):
    sent = []

    def fake_post(url, json=None, timeout=None):
        if url.endswith("getUpdates"):
            return FakeResp({"result": [{"message": {"chat": {"id": 42, "type": "private"}}}]})
        sent.append(json)
        return FakeResp({"ok": True})

    monkeypatch.setattr("agent.notify.requests.post", fake_post)
    db = DB(tmp_path / "t.db")
    n = Notifier(db, token="x:y", chat_id="")
    assert n.send("hallo", key="k1") and not n.send("hallo", key="k1")
    assert sent[0]["chat_id"] == "42" and db.get("telegram_chat_id") == "42"


def test_notifier_silent_without_token(tmp_path):
    assert Notifier(DB(tmp_path / "t.db"), token="", chat_id="").send("x") is False


def test_split_long_message():
    from agent.notify import split
    text = "\n".join(f"<b>regel {i}</b> " + "x" * 200 for i in range(60))
    parts = split(text)
    assert len(parts) > 1 and all(len(p) <= 3900 for p in parts)
    assert "\n".join(parts) == text
