"""Una tarjeta que Anki rechaza por duplicada no está «en cola».

En la base de un usuario había 57 tarjetas así (9 % de las de catalán): Anki
ya tenía la palabra, la app descartaba la tarjeta y aun así avisaba «en cola»,
como si fuera a llegar al abrir Anki.
"""
from fastapi.testclient import TestClient

import app.main as main


def _setup(tmp_path, monkeypatch, send):
    main.CON = main.db.connect(tmp_path / "t.db")
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: True)
    monkeypatch.setattr(main.anki, "send_card", send)
    sid = main.db.create_session(main.CON, language="ca", title="t", source_type="text",
                                 media_path="x", srt_source="-", model_size="-",
                                 duration_secs=0, transcript_json="[]")
    return TestClient(main.app), sid


def _post(c, sid):
    return c.post("/api/cards", json={"session_id": sid, "segment_index": 0,
                                      "paraula": "allò", "lema": "allò",
                                      "frase": "Pensava en allò.", "definicio": ""}).json()


def test_duplicate_is_reported_as_such(tmp_path, monkeypatch):
    def dup(*a):
        raise main.anki.AnkiError("cannot create note because it is a duplicate")
    c, sid = _setup(tmp_path, monkeypatch, dup)
    r = _post(c, sid)
    assert r["duplicate"] is True and r["sent_now"] is False
    assert main.db.pending_cards(main.CON) == [], "no se reintenta"


def test_sent_card(tmp_path, monkeypatch):
    c, sid = _setup(tmp_path, monkeypatch, lambda *a: 42)
    r = _post(c, sid)
    assert r["sent_now"] is True and r["duplicate"] is False


def test_queued_when_anki_is_closed(tmp_path, monkeypatch):
    c, sid = _setup(tmp_path, monkeypatch, lambda *a: 42)
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: False)
    r = _post(c, sid)
    assert r["sent_now"] is False and r["duplicate"] is False
    assert len(main.db.pending_cards(main.CON)) == 1
