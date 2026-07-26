"""Sembrar vocabulario desde un mazo de Anki que ya estudias."""
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app import db, vocab


def _con(tmp_path):
    main.CON = db.connect(tmp_path / "t.db")
    return main.CON


def test_deck_words_cleans_html_and_drops_sentences():
    from app import anki
    notes = [
        {"fields": {"Front": {"value": "<b>gos</b>", "order": 0},
                    "Back": {"value": "perro", "order": 1}}},
        {"fields": {"Front": {"value": "casa [sound:c.mp3]", "order": 0}}},
        {"fields": {"Front": {"value": "una frase entera que no es vocabulario",
                              "order": 0}}},        # >3 palabras: se descarta
        {"fields": {}},                              # nota vacía: se ignora
    ]
    with patch.object(anki, "invoke", side_effect=lambda a, **k:
                      [1, 2, 3, 4] if a == "findNotes" else notes):
        assert anki.deck_words("Mazo") == ["gos", "casa"]


def test_seed_marks_known_without_touching_existing(tmp_path):
    con = _con(tmp_path)
    db.set_word_status(con, "gos", "learning", "ca")     # progreso previo
    from app import anki
    with patch.object(anki, "deck_words", return_value=["gos", "casa", "llibre"]), \
         patch.object(main.nlp, "analyze_selection", side_effect=lambda w, c="": (w, "NOUN")):
        r = vocab.seed_from_anki(con, "Mazo", "ca")
    st = db.word_statuses(con, "ca")
    assert st["gos"] == "learning"          # NO se pisa lo ya marcado
    assert st["casa"] == "known" and st["llibre"] == "known"
    assert r == {"marked": 2, "skipped": 1, "read": 3}


def test_seed_endpoint_rejects_unknown_deck(tmp_path):
    _con(tmp_path)
    c = TestClient(main.app)
    with patch.object(main.anki, "deck_names", return_value=["Mio"]):
        assert c.post("/api/words/seed-anki", json={"deck": "Otro"}).status_code == 400


def test_decks_endpoint_survives_anki_closed(tmp_path):
    _con(tmp_path)
    c = TestClient(main.app)
    with patch.object(main.anki, "deck_names", side_effect=Exception("down")):
        r = c.get("/api/anki/decks").json()
    assert r["decks"] == [] and "error" in r


def test_seed_job_reports_friendly_error_when_anki_drops(tmp_path):
    """Si Anki se cierra a mitad, el usuario ve un mensaje claro, no un stack."""
    import time
    _con(tmp_path)
    c = TestClient(main.app)
    with patch.object(main.anki, "deck_names", return_value=["Mio"]), \
         patch.object(main.vocab, "seed_from_anki",
                      side_effect=ConnectionError("HTTPConnectionPool(...)")):
        r = c.post("/api/words/seed-anki", json={"deck": "Mio"}).json()
        t0 = time.time()
        while time.time() - t0 < 10:
            j = main.jobs.get(r["job_id"])
            if j["status"] in ("done", "error"):
                break
            time.sleep(0.05)
    assert j["status"] == "error"
    assert "Anki dejó de responder" in j["message"]
    assert "HTTPConnectionPool" not in j["message"]
