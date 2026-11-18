"""Más contexto en la tarjeta: definición editable, ejemplos y notas.

Lo pidieron en Reddit: que la tarjeta tenga sitio para el contexto de la
palabra y para ejemplos. La definición ya llegaba a Anki pero no se veía ni
se podía tocar en el editor; los ejemplos de tus otros vídeos solo salían
en el popup; y no había dónde apuntar nada propio.
"""
import json

from fastapi.testclient import TestClient

import app.main as main
from app import anki, config


def _tok(word, lemma):
    return {"text": word, "is_word": True, "lemma": lemma}


def _session(title, lines, lemma="kunst", language="de"):
    segs = [{"start": i * 3.0, "end": i * 3.0 + 2, "text": t,
             "tokens": [_tok("Kunst", lemma)] if "Kunst" in t else []}
            for i, t in enumerate(lines)]
    return main.db.create_session(main.CON, language=language, title=title, source_type="text",
                                  media_path="x", srt_source="-", model_size="-",
                                  duration_secs=0, transcript_json=json.dumps(segs))


def _client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    c.post("/api/settings", json={"language": "de"})
    return c


# ---------- plantilla y nota ----------

def test_examples_and_notes_go_on_the_back_only():
    for layout in anki.CARD_LAYOUTS:
        front, back = anki.templates(layout)
        for campo in ("{{Exemples}}", "{{Notes}}"):
            assert campo not in front and campo in back
    card = {"paraula": "Kunst", "lema": "kunst", "paraula_es": "arte", "frase": "x",
            "frase_es": "", "exemples": "Das ist Kunst.", "notes": "die Kunst, Künste"}
    fields = anki.build_note(card, deck="D")["fields"]
    assert fields["Exemples"] == "Das ist Kunst." and fields["Notes"] == "die Kunst, Künste"
    assert list(fields) == config.NOTE_FIELDS, "mismo orden que el tipo de nota"


def test_a_template_never_names_a_field_the_note_type_lacks():
    old = config.NOTE_FIELDS[:config.NOTE_FIELDS.index("Definicio") + 1]
    _, back = anki.templates("reading", fields=old)
    assert "{{Definicio}}" in back
    assert "Exemples" not in back and "Notes" not in back
    assert "{{Font}}" in back


def test_an_old_note_type_gets_both_new_fields(monkeypatch):
    calls = []
    old = config.NOTE_FIELDS[:config.NOTE_FIELDS.index("Definicio") + 1]

    def invoke(action, **kw):
        calls.append((action, kw.get("fieldName")))
        return {"modelNames": ["LinguaMiner"], "modelFieldNames": list(old),
                "modelTemplates": {"Card 1": {"Front": "old", "Back": "old"}},
                "modelStyling": {"css": ""}}.get(action)
    monkeypatch.setattr(anki, "invoke", invoke)
    anki.ensure_note_type()
    assert [f for a, f in calls if a == "modelFieldAdd"] == ["Exemples", "Notes"]


# ---------- del editor a la base de datos ----------

def test_editor_text_is_stored_as_safe_html():
    assert main._html_lines("uno\n\n  dos  \n") == "uno<br>dos"
    assert main._html_lines("<b>ojo</b> & co") == "&lt;b&gt;ojo&lt;/b&gt; &amp; co"
    assert main._html_lines("") == ""


def test_card_keeps_what_was_written_in_the_editor(tmp_path, monkeypatch):
    c = _client(tmp_path)
    sid = _session("Buch", ["Die Kunst."])
    monkeypatch.setattr(main, "_flush", lambda: 0)
    monkeypatch.setattr(main, "_definition", lambda *a: "NO DEBÍA USARSE")
    r = c.post("/api/cards", json={
        "session_id": sid, "segment_index": 0, "paraula": "Kunst", "lema": "kunst",
        "frase": "Die Kunst.", "definicio": "art\nskill",
        "exemples": "Das ist Kunst.\nKunst kommt von Können.",
        "notes": "pl. Künste <ojo>"})
    assert r.status_code == 200
    card = main.db.pending_cards(main.CON)[0]
    assert card["definicio"] == "art<br>skill"
    assert card["exemples"] == "Das ist Kunst.<br>Kunst kommt von Können."
    assert card["notes"] == "pl. Künste &lt;ojo&gt;"


def test_a_cleared_definition_stays_cleared(tmp_path, monkeypatch):
    c = _client(tmp_path)
    sid = _session("Buch", ["Die Kunst."])
    monkeypatch.setattr(main, "_flush", lambda: 0)
    monkeypatch.setattr(main, "_definition", lambda *a: "del diccionario")
    base = {"session_id": sid, "segment_index": 0, "paraula": "Kunst", "lema": "kunst",
            "frase": "Die Kunst."}
    c.post("/api/cards", json={**base, "definicio": ""})
    c.post("/api/cards", json=base)              # cliente antiguo: sin el campo
    defs = sorted(x["definicio"] for x in main.db.pending_cards(main.CON))
    assert defs == ["", "del diccionario"]


# ---------- ejemplos de tus vídeos ----------

def test_examples_come_from_other_content_and_skip_the_card_sentence(tmp_path):
    _client(tmp_path)
    _session("Doku", ["Kunst ist schwer.", "Nichts.", "Moderne Kunst.", "Kunst am Bau."])
    sid = _session("Buch", ["Die Kunst des Lesens."])
    ex = main._examples_for("kunst", sid, "Die Kunst des Lesens.")
    assert len(ex) == 2 and "Die Kunst des Lesens." not in ex
    assert all("Kunst" in e for e in ex)


def test_examples_stay_in_the_study_language(tmp_path):
    _client(tmp_path)
    _session("Englisch", ["Kunst in English."], language="en")
    _session("Doku", ["Moderne Kunst."])
    assert main._examples_for("kunst", "", "") == ["Moderne Kunst."]


def test_examples_setting(tmp_path):
    c = _client(tmp_path)
    _session("Doku", ["Kunst ist schwer.", "Moderne Kunst.", "Kunst am Bau.", "Mehr Kunst."])
    assert c.get("/api/settings").json()["card_examples"] == 2
    assert c.post("/api/settings", json={"card_examples": 0}).status_code == 200
    assert main._examples_for("kunst", "", "") == []
    c.post("/api/settings", json={"card_examples": 3})
    assert len(main._examples_for("kunst", "", "")) == 3
    assert c.post("/api/settings", json={"card_examples": 4}).status_code == 400


def test_preview_brings_definition_and_examples(tmp_path, monkeypatch):
    c = _client(tmp_path)
    _session("Doku", ["Moderne Kunst."])
    sid = _session("Buch", ["Die Kunst des Lesens."])
    monkeypatch.setattr(main.piper_tts, "speak", lambda t: "")
    monkeypatch.setattr(main.translate, "sentence", lambda t: "ES")
    monkeypatch.setattr(main, "_word_info", lambda sel, txt: {
        "lemma": "kunst", "pos": "NOUN", "headword": "", "gloss_key": "kunst", "word_es": "arte"})
    monkeypatch.setattr(main, "_definition_text", lambda *a: "art\nskill")
    p = c.post("/api/cards/preview", json={"session_id": sid, "segment_index": 0,
                                           "selection": "Kunst"}).json()
    assert p["definicio"] == "art\nskill"
    assert p["exemples"] == "Moderne Kunst."
