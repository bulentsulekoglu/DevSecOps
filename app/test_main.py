from datetime import datetime

from fastapi.testclient import TestClient

import main


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows=None):
        self._rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        return FakeCursor(self._rows)


client = TestClient(main.app)


def test_health(monkeypatch):
    monkeypatch.setattr(main, "get_conn", lambda: FakeConn())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_add_note(monkeypatch):
    monkeypatch.setattr(main, "get_conn", lambda: FakeConn(rows=[(1,)]))
    r = client.post("/notes", params={"text": "merhaba"})
    assert r.status_code == 200
    assert r.json() == {"id": 1, "text": "merhaba"}


def test_list_notes(monkeypatch):
    rows = [(1, "merhaba", datetime(2026, 1, 1))]
    monkeypatch.setattr(main, "get_conn", lambda: FakeConn(rows=rows))
    r = client.get("/notes")
    assert r.status_code == 200
    assert r.json()[0]["text"] == "merhaba"


def test_add_note_requires_text():
    r = client.post("/notes")
    assert r.status_code == 422
