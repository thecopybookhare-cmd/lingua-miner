"""Exportar tarjetas a .apkg: lo que Anki importa sin AnkiConnect."""
import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import config, desktop


@pytest.fixture
def c(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    monkeypatch.setattr(config, "MEDIA_DIR", media)
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def _card(paraula, frase, audio=None, image=None):
    sid = main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x.mp4",
        srt_source="none", model_size="-", duration_secs=1, transcript_json="[]")
    return main.db.create_card(
        main.CON, session_id=sid, segment_index=0, paraula=paraula, lema=paraula,
        pos="NOUN", paraula_es="perro", frase=frase, frase_es="El perro ladra",
        freq_rank="common", audio_file=audio, image_file=image, font="V @ 0:01")


def _open(raw: bytes, tmp_path):
    """Lo que vería Anki al importar: la colección, sus notas y los medios."""
    z = zipfile.ZipFile(io.BytesIO(raw))
    media = json.loads(z.read("media"))                  # {"0": "a.mp3", ...}
    files = {name: z.read(idx) for idx, name in media.items()}
    col = tmp_path / "col.anki2"
    col.write_bytes(z.read("collection.anki2"))
    con = sqlite3.connect(col)
    notes = con.execute("SELECT guid, flds, tags FROM notes").fetchall()
    models, decks = con.execute("SELECT models, decks FROM col").fetchone()
    con.close()
    return notes, files, json.loads(models), json.loads(decks)


def test_apkg_has_the_cards_their_media_and_note_type(c, tmp_path):
    (config.MEDIA_DIR / "a1.mp3").write_bytes(b"audio")
    (config.MEDIA_DIR / "i1.gif").write_bytes(b"clip")
    _card("gos", "El gos borda", audio="a1.mp3", image="i1.gif")
    r = c.get("/api/cards/export.apkg")
    assert r.status_code == 200
    assert ".apkg" in r.headers["content-disposition"]
    notes, files, models, decks = _open(r.content, tmp_path)
    assert len(notes) == 1
    flds = notes[0][1].split("\x1f")
    assert flds[0] == "gos" and flds[2] == "El gos borda"
    assert "[sound:a1.mp3]" in flds and '<img src="i1.gif">' in flds
    assert files == {"a1.mp3": b"audio", "i1.gif": b"clip"}
    # el mismo tipo de nota que crea AnkiConnect, en el mazo configurado
    model = next(iter(models.values()))
    assert model["name"] == config.NOTE_TYPE
    assert [f["name"] for f in model["flds"]] == config.NOTE_FIELDS
    assert any(d["name"] == "LinguaMiner::Mining" for d in decks.values())
    assert "lingua-miner" in notes[0][2]


def test_only_cards_not_yet_in_anki_by_default(c, tmp_path):
    _card("gos", "El gos borda")
    sent = _card("gat", "El gat dorm")
    dup = _card("casa", "La casa és gran")
    main.db.mark_card_sent(main.CON, sent, 123)
    main.db.mark_card_duplicate(main.CON, dup)
    assert c.get("/api/cards/counts").json() == {"pending": 1, "all": 2}
    pending, *_ = _open(c.get("/api/cards/export.apkg").content, tmp_path)
    assert [n[1].split("\x1f")[0] for n in pending] == ["gos"]
    everything, *_ = _open(c.get("/api/cards/export.apkg?all=1").content, tmp_path)
    assert sorted(n[1].split("\x1f")[0] for n in everything) == ["gat", "gos"]   # sin la duplicada


def test_importing_twice_updates_instead_of_duplicating(c, tmp_path):
    _card("gos", "El gos borda")
    first, *_ = _open(c.get("/api/cards/export.apkg").content, tmp_path)
    again, *_ = _open(c.get("/api/cards/export.apkg").content, tmp_path)
    assert [n[0] for n in first] == [n[0] for n in again]          # mismo guid


def test_missing_media_does_not_break_the_export(c, tmp_path):
    _card("gos", "El gos borda", audio="ya-no-esta.mp3")
    notes, files, *_ = _open(c.get("/api/cards/export.apkg").content, tmp_path)
    assert len(notes) == 1 and files == {}


def test_nothing_to_export(c):
    assert c.get("/api/cards/counts").json() == {"pending": 0, "all": 0}
    assert c.get("/api/cards/export.apkg").status_code == 404


def test_desktop_window_allows_downloads():
    # sin esto el audio condensado (y el .apkg) no se descargaban en el Mac
    class FakeWebview:
        settings = {"ALLOW_DOWNLOADS": False}
    desktop._configure_webview(FakeWebview)
    assert FakeWebview.settings["ALLOW_DOWNLOADS"] is True
