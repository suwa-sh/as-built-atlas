"""jobs.lib.notify の単体テスト (pytest)。"""
from jobs.lib import notify


def test_post_without_webhook_does_nothing(monkeypatch):
    monkeypatch.delenv("KOTORI_CHAT_WEBHOOK", raising=False)
    calls = []
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: calls.append(a))
    notify.post("hello")
    assert calls == []  # URL が無ければ、何も送らない
