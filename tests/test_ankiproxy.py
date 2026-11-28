"""Puente con asbplayer: LinguaMiner hace de AnkiConnect.

Netflix no se puede descargar (DRM), pero asbplayer mina en la propia página:
lee los subtítulos y graba el audio y un clip de la frase. Apuntado a
/ankiconnect en vez de a Anki, las notas del tipo LinguaMiner llegan
completas (traducción, definición, ejemplos) y lo demás pasa tal cual.
"""
import json

from fastapi.testclient import TestClient

import app.main as main
from app import anki, ankiproxy, config

EXT = "chrome-extension://hkledmpjpaehamkiehglnbelcpdflcab"


def _client(tmp_path, monkeypatch, replies=None, up=True):
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    c.post("/api/settings", json={"language": "de"})
    sent = []

    def forward(payload, preferred=None):
        sent.append(json.loads(json.dumps(payload)))
        return (replies or {}).get(payload["action"], {"result": 1234, "error": None})
    monkeypatch.setattr(anki, "find_port", lambda p=None: ((8765 if up else None), {}))
    monkeypatch.setattr(anki, "forward", forward)
    monkeypatch.setattr(main.translate, "sentence", lambda t: "Eso es arte.")
    monkeypatch.setattr(main, "_word_info", lambda sel, frase: {
        "lemma": "kunst", "pos": "NOUN", "headword": "die Kunst",
        "gloss_key": "kunst", "word_es": "el arte"})
    monkeypatch.setattr(main, "_definition", lambda *a: "art<br>skill")
    monkeypatch.setattr(main.nlp, "zipf", lambda w: 4.2)
    return c, sent


def _post(c, body, origin=EXT):
    # asbplayer manda el JSON como text/plain (sin preflight de CORS)
    headers = {"Content-Type": "text/plain;charset=UTF-8"}
    if origin is not None:
        headers["Origin"] = origin
    return c.post("/ankiconnect", content=json.dumps(body), headers=headers)


def _note(fields, model=config.NOTE_TYPE):
    """Como la exporta asbplayer: el audio y el clip van aparte, en base64."""
    return {"action": "addNote", "version": 6, "key": "secreto",
            "params": {"note": {
                "deckName": "Netflix", "modelName": model, "tags": ["asbplayer"],
                "fields": fields, "options": {"allowDuplicate": True},
                "audio": {"filename": "asbp_a.mp3", "data": "QUJD", "fields": ["Audio"]},
                "picture": {"filename": "asbp_c.webp", "data": "UklG", "fields": ["Imatge"]}}}}


def _sent_note(sent):
    return sent[-1]["params"]["note"]


# ---------- pasa tal cual ----------

def test_other_actions_go_through_untouched(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch,
                      replies={"deckNames": {"result": ["Netflix"], "error": None}})
    body = {"action": "deckNames", "version": 6, "key": "secreto"}
    r = _post(c, body)
    assert r.json() == {"result": ["Netflix"], "error": None}
    assert sent == [body], "con su versión y su key"
    assert r.headers["access-control-allow-origin"] == EXT


def test_a_note_of_another_type_is_not_touched(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    body = _note({"Front": "Kunst", "Back": "Das ist Kunst."}, model="Basic")
    _post(c, body)
    assert sent == [body]
    assert main.db.cards_for_export(main.CON, only_pending=False) == []


def test_model_list_brings_the_linguaminer_note_type(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(anki, "ensure_note_type", lambda layout="reading": calls.append(layout))
    _post(c, {"action": "modelNames", "version": 6})
    assert calls == ["reading"]


# ---------- la nota LinguaMiner llega completa ----------

def test_linguaminer_note_is_filled_in(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    r = _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst.",
                        "Font": "Dark S01E01 (12:34)"}))
    assert r.json() == {"result": 1234, "error": None}
    note = _sent_note(sent)
    f = note["fields"]
    assert f["Paraula"] == "Kunst"
    assert f["ParaulaES"] == "die Kunst — el arte"
    assert f["FraseES"] == "Eso es arte."
    assert f["Definicio"] == "art<br>skill"
    assert f["Freq"]
    assert f["Font"] == "Dark S01E01 (12:34)"
    # lo de asbplayer sigue ahí
    assert note["audio"]["data"] == "QUJD" and note["picture"]["filename"] == "asbp_c.webp"
    assert note["options"] == {"allowDuplicate": True}
    assert note["tags"] == ["asbplayer", "lingua-miner"]
    assert sent[-1]["key"] == "secreto"


def test_what_you_wrote_in_asbplayer_wins(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst.",
                    "ParaulaES": "arte (el mío)", "Definicio": "mi definición"}))
    f = _sent_note(sent)["fields"]
    assert f["ParaulaES"] == "arte (el mío)" and f["Definicio"] == "mi definición"


def test_the_card_counts_in_linguaminer(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst."}))
    (card,) = main.db.cards_for_export(main.CON, only_pending=False)
    assert card["status"] == "sent" and card["anki_note_id"] == 1234
    assert card["lema"] == "kunst" and card["frase"] == "Das ist Kunst."
    assert main.db.pending_cards(main.CON) == [], "la cola no la vuelve a mandar"
    assert main.db.word_statuses(main.CON, "de")["kunst"] == "learning"


def test_a_note_anki_rejects_is_not_recorded(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch, replies={
        "addNote": {"result": None, "error": "cannot create note because it is a duplicate"}})
    r = _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst."}))
    assert "duplicate" in r.json()["error"]
    assert main.db.cards_for_export(main.CON, only_pending=False) == []


def test_a_failing_lookup_does_not_lose_the_card(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)

    def boom(*a):
        raise RuntimeError("diccionario roto")
    monkeypatch.setattr(main, "_word_info", boom)
    monkeypatch.setattr(main, "_definition", boom)
    r = _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst."}))
    assert r.json()["result"] == 1234
    f = _sent_note(sent)["fields"]
    assert f["Paraula"] == "Kunst" and f["FraseES"] == "Eso es arte."


# ---------- sin palabra elegida ----------

def test_the_highlighted_word_is_the_word(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    _post(c, _note({"Frase": "Das ist <b>Kunst</b>."}))
    f = _sent_note(sent)["fields"]
    assert f["Paraula"] == "Kunst" and f["ParaulaES"] == "die Kunst — el arte"


def _tokens(*words):
    return [{"t": w, "lemma": lemma, "pos": pos, "is_word": True, "zipf": 4.0, "ws": " "}
            for w, lemma, pos in words]


def test_the_only_new_word_is_picked(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main.nlp, "tokenize", lambda t: _tokens(
        ("Das", "das", "PRON"), ("ist", "sein", "AUX"), ("Kunst", "kunst", "NOUN")))
    for lemma in ("das", "sein"):
        main.db.set_word_status(main.CON, lemma, "known", "de")
    _post(c, _note({"Frase": "Das ist Kunst."}))
    assert _sent_note(sent)["fields"]["Paraula"] == "Kunst"


def test_with_several_new_words_it_is_a_sentence_card(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main.nlp, "tokenize", lambda t: _tokens(
        ("Moderne", "modern", "ADJ"), ("Kunst", "kunst", "NOUN")))
    _post(c, _note({"Frase": "Moderne Kunst."}))
    f = _sent_note(sent)["fields"]
    assert f["Paraula"] == "Moderne Kunst." and f["Frase"] == ""
    assert f["FraseES"] == "Eso es arte."


def test_a_new_name_is_not_the_word(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main.nlp, "tokenize", lambda t: _tokens(
        ("Jonas", "jonas", "PROPN"), ("kommt", "kommen", "VERB")))
    main.db.set_word_status(main.CON, "kommen", "known", "de")
    _post(c, _note({"Frase": "Jonas kommt."}))
    assert _sent_note(sent)["fields"]["Paraula"] == "Jonas kommt."


# ---------- quién puede usar el puente ----------

def test_web_pages_cannot_reach_your_anki(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    for origin in ("https://evil.example", "null", "http://localhost.evil.example"):
        assert _post(c, {"action": "deleteDecks", "version": 6}, origin=origin).status_code == 403
    assert sent == []


def test_extensions_localhost_and_desktop_apps_can(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    for origin in (EXT, "moz-extension://abc", "https://app.asbplayer.dev",
                   "http://localhost:3000", "http://127.0.0.1:8977", None):
        assert _post(c, {"action": "version", "version": 6}, origin=origin).status_code == 200
    assert len(sent) == 6


def test_preflight(tmp_path, monkeypatch):
    c, _ = _client(tmp_path, monkeypatch)
    ok = c.options("/ankiconnect", headers={"Origin": EXT})
    assert ok.status_code == 204 and ok.headers["access-control-allow-origin"] == EXT
    assert c.options("/ankiconnect", headers={"Origin": "https://evil.example"}).status_code == 403


def test_guests_on_the_network_cannot_use_it():
    assert "/ankiconnect" in main._ADMIN_POSTS


def test_anki_closed_is_a_clear_error(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch, up=False)
    r = _post(c, _note({"Paraula": "Kunst", "Frase": "Das ist Kunst."}))
    assert r.json()["result"] is None and "Anki" in r.json()["error"]
    assert sent == []


def test_bad_json_is_an_ankiconnect_error(tmp_path, monkeypatch):
    c, sent = _client(tmp_path, monkeypatch)
    r = c.post("/ankiconnect", content=b"{no", headers={"Origin": EXT})
    assert r.json()["result"] is None and r.json()["error"]
    assert sent == []


# ---------- piezas ----------

def test_plain_and_highlighted():
    assert ankiproxy.plain("Das ist <b>Kunst</b>.<br>Zweite") == "Das ist Kunst. Zweite"
    assert ankiproxy.plain("[sound:asbp_a.mp3]") == ""
    assert ankiproxy.plain("a &amp; b") == "a & b"
    assert ankiproxy.plain(None) == ""
    assert ankiproxy.highlighted("Das ist <b>Kunst</b>.") == "Kunst"
    assert ankiproxy.highlighted("Das ist Kunst.") == ""
    assert ankiproxy.esc("<ojo>") == "&lt;ojo&gt;"


def test_settings_show_the_note_type_to_pick(tmp_path, monkeypatch):
    """Quien instaló antes del cambio de nombre tiene «CatalaMiner» en Anki y
    buscaba «LinguaMiner» en la lista de asbplayer."""
    c, _ = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(anki, "invoke", lambda action, **kw: {
        "deckNames": ["Netflix"], "modelNames": ["CatalaMiner", "Basic"]}.get(action))
    assert c.get("/api/anki/status").json()["model"] == "CatalaMiner"
    monkeypatch.setattr(anki, "find_port", lambda p=None: (None, {}))
    assert c.get("/api/anki/status").json()["model"] == config.NOTE_TYPE
