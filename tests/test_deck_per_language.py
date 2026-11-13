"""Un mazo por idioma de estudio.

«deck» era un solo ajuste para todo: quien estudiaba catalán y pasaba al
alemán metía las tarjetas alemanas en su mazo de catalán, y las pendientes
del catalán (con Anki cerrado) acababan en el del alemán al vaciarse la cola.
"""
from fastapi.testclient import TestClient

import app.main as main


def _client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def test_switching_language_keeps_each_deck(tmp_path):
    c = _client(tmp_path)
    c.post("/api/settings", json={"language": "ca", "deck": "Català::Mining"})
    r = c.post("/api/settings", json={"language": "de"}).json()
    assert r["deck"] == "LinguaMiner::Deutsch", "idioma nuevo, mazo nuevo"
    assert r["deck_by_lang"]["ca"] == "Català::Mining"
    c.post("/api/anki/deck", json={"deck": "Alemán::Mining"})
    r = c.post("/api/settings", json={"language": "ca"}).json()
    assert r["deck"] == "Català::Mining", "al volver, el suyo"
    r = c.post("/api/settings", json={"language": "de"}).json()
    assert r["deck"] == "Alemán::Mining"


def test_deck_and_language_in_the_same_request(tmp_path):
    c = _client(tmp_path)
    c.post("/api/settings", json={"language": "ca", "deck": "Català::Mining"})
    r = c.post("/api/settings", json={"language": "de", "deck": "Deutsch"}).json()
    assert r["deck"] == "Deutsch"
    assert r["deck_by_lang"] == {"ca": "Català::Mining", "de": "Deutsch"}


def test_other_settings_do_not_touch_the_deck(tmp_path):
    c = _client(tmp_path)
    c.post("/api/settings", json={"language": "ca", "deck": "Català::Mining"})
    r = c.post("/api/settings", json={"sub_scale": 1.2}).json()
    assert r["deck"] == "Català::Mining"


def test_bad_deck_map_is_rejected(tmp_path):
    c = _client(tmp_path)
    r = c.post("/api/settings", json={"deck_by_lang": {"de": 3}})
    assert r.status_code == 400


def test_pending_cards_go_to_their_own_language_deck(tmp_path, monkeypatch):
    c = _client(tmp_path)
    c.post("/api/settings", json={"language": "ca", "deck": "Català::Mining"})
    sid = main.db.create_session(main.CON, language="ca", title="t", source_type="file",
                                 media_path="x", srt_source="none", model_size="-",
                                 duration_secs=1, transcript_json="[]")
    for lang in ("ca", "de"):
        main.db.create_card(main.CON, session_id=sid, segment_index=0, paraula="w",
                            lema="w", pos="", paraula_es="", frase=f"frase {lang}",
                            frase_es="", freq_rank="", audio_file="", image_file="",
                            font="", language=lang)
    c.post("/api/settings", json={"language": "de"})
    sent = []
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: True)
    monkeypatch.setattr(main.anki, "send_card", lambda card, deck, *_: sent.append((card["frase"], deck)) or 1)
    main._flush()
    assert sorted(sent) == [("frase ca", "Català::Mining"), ("frase de", "LinguaMiner::Deutsch")]


def test_apkg_splits_cards_by_language_deck(tmp_path, monkeypatch):
    import genanki

    from app import apkg
    seen = {}

    class FakePackage:
        def __init__(self, decks):
            seen["decks"] = sorted(d.name for d in (decks if isinstance(decks, list) else [decks]))
            self.media_files = []

        def write_to_file(self, path):
            pass
    monkeypatch.setattr(genanki, "Package", FakePackage)
    cards = [{"id": "1", "language": "ca", "paraula": "gos", "paraula_es": "", "frase": "a",
              "frase_es": "", "audio_file": "", "image_file": ""},
             {"id": "2", "language": "de", "paraula": "Hund", "paraula_es": "", "frase": "b",
              "frase_es": "", "audio_file": "", "image_file": ""}]
    decks = {"ca": "Català::Mining", "de": "LinguaMiner::Deutsch"}
    apkg.build(cards, "Català::Mining", tmp_path / "x.apkg", deck_for=lambda c: decks[c["language"]])
    assert seen["decks"] == ["Català::Mining", "LinguaMiner::Deutsch"]
