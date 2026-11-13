from unittest.mock import MagicMock, patch

import pytest

from app import anki, config


@pytest.fixture(autouse=True)
def _reset_port(monkeypatch):
    anki._PORT = None
    # estos tests simulan AnkiConnect a nivel HTTP: el puerto «escucha»
    monkeypatch.setattr(anki, "_port_open", lambda port: True)
    yield
    anki._PORT = None


def _resp(result=None, error=None):
    m = MagicMock()
    m.json.return_value = {"result": result, "error": error}
    return m


def _squat():
    m = MagicMock()
    m.json.return_value = {"detail": "invalid bearer token"}
    return m


def test_note_payload():
    card = {"paraula": "gos", "paraula_es": "perro", "frase": "El gos",
            "frase_es": "El perro", "audio_file": "a.mp3",
            "image_file": "i.jpg", "font": "V @ 0:01", "freq_rank": "common"}
    note = anki.build_note(card, deck="Català")
    assert note["deckName"] == "Català"
    assert note["modelName"] == "LinguaMiner"
    assert note["fields"]["Audio"] == "[sound:a.mp3]"
    assert note["fields"]["Imatge"] == '<img src="i.jpg">'
    assert note["options"]["allowDuplicate"] is False


def test_empty_word_falls_back_to_lemma():
    # una Paraula vacía hacía que Anki rechazara la nota y atascaba la cola
    card = {"paraula": "", "lema": "gleich", "paraula_es": "", "frase": "x",
            "frase_es": ""}
    assert anki.build_note(card, deck="D")["fields"]["Paraula"] == "gleich"


@patch("app.anki.requests.post")
def test_invoke_ok_and_error(post):
    post.return_value = _resp(result=["Default"])
    assert anki.invoke("deckNames") == ["Default"]
    post.return_value = _resp(error="boom")
    import pytest
    with pytest.raises(anki.AnkiError):
        anki.invoke("deckNames")


@patch("app.anki.requests.post")
def test_is_up_false_when_down(post):
    post.side_effect = ConnectionError()
    assert anki.is_up() is False


@patch("app.anki.requests.post")
def test_is_up_false_when_port_squatted(post):
    post.return_value = _squat()
    assert anki.is_up() is False


@patch("app.anki.requests.post")
def test_find_port_discovers_8766_when_8765_squatted(post):
    def se(url, **kw):
        if ":8765" in url:
            return _squat()
        if ":8766" in url:
            return _resp(result=6)
        raise ConnectionError()

    post.side_effect = se
    port, diag = anki.find_port()
    assert port == 8766
    assert diag["8765"] == "squatted" and diag["8766"] == "ok"
    # discovered port is remembered and reused by invoke
    assert anki._PORT == 8766
    assert anki.invoke("version") == 6


def test_listening_layout_hides_the_text_on_the_front():
    # modo oído: delante solo imagen y audio; palabra, frase y traducciones detrás
    front, back = anki.templates("listening")
    for campo in ("{{Paraula}}", "{{Frase}}", "{{ParaulaES}}", "{{FraseES}}"):
        assert campo not in front and campo in back
    assert "{{Audio}}" in front and "{{Imatge}}" in front
    assert anki.templates("reading") == (anki.FRONT, anki.BACK)


def test_definition_goes_on_the_back_only():
    for layout in anki.CARD_LAYOUTS:
        front, back = anki.templates(layout)
        assert "{{Definicio}}" not in front and "{{Definicio}}" in back
    card = {"paraula": "Trabi", "lema": "trabi", "paraula_es": "Trabi",
            "frase": "x", "frase_es": "", "definicio": "clipping of Trabant"}
    assert anki.build_note(card, deck="D")["fields"]["Definicio"] == "clipping of Trabant"


def _fake_anki(model_state):
    calls = []

    def invoke(action, **kw):
        calls.append(action)
        return {"modelNames": ["LinguaMiner"],
                "modelFieldNames": list(model_state["fields"]),
                "modelTemplates": {"Card 1": model_state["tmpl"]},
                "modelStyling": {"css": model_state["css"]}}.get(action)
    return invoke, calls


def test_unchanged_note_type_is_not_rewritten(monkeypatch):
    # con un editor abierto en Anki, cualquier escritura del modelo falla y
    # atascaba la cola: si no hay cambios, no se escribe nada
    front, back = anki.templates("listening")
    invoke, calls = _fake_anki({"fields": config.NOTE_FIELDS,
                                "tmpl": {"Front": front, "Back": back},
                                "css": anki.CARD_CSS})
    monkeypatch.setattr(anki, "invoke", invoke)
    anki.ensure_note_type("listening")
    assert not {"updateModelTemplates", "updateModelStyling", "modelFieldAdd"} & set(calls)


def test_old_note_type_gets_the_new_field(monkeypatch):
    invoke, calls = _fake_anki({"fields": config.NOTE_FIELDS[:-1],
                                "tmpl": {"Front": "old", "Back": "old"}, "css": ""})
    monkeypatch.setattr(anki, "invoke", invoke)
    anki.ensure_note_type()
    assert calls.count("modelFieldAdd") == 1
    assert "updateModelTemplates" in calls and "updateModelStyling" in calls


# ---------- que un fallo de Anki no deje la cola parada ----------

def test_old_ankiconnect_without_field_add_still_gets_a_valid_template(monkeypatch):
    """Un AnkiConnect anterior a modelFieldAdd: la tarjeta tiene que salir,
    y sin nombrar un campo que el tipo de nota no tiene (Anki enseñaría
    «{{Definicio}}: field not found» en todas)."""
    from app import failures
    failures.reset()
    written = {}

    def invoke(action, **kw):
        if action == "modelFieldAdd":
            raise anki.AnkiError("unsupported action")
        if action == "updateModelTemplates":
            written.update(kw["model"]["templates"]["Card 1"])
        return {"modelNames": ["LinguaMiner"],
                "modelFieldNames": config.NOTE_FIELDS[:-1],
                "modelTemplates": {"Card 1": {"Front": "old", "Back": "old"}},
                "modelStyling": {"css": ""}}.get(action)
    monkeypatch.setattr(anki, "invoke", invoke)
    assert anki.ensure_note_type() == "LinguaMiner"
    assert "Definicio" not in written["Back"] and "{{FraseES}}" in written["Back"]
    assert any("Definicio" in m for m in failures.active()), "y lo dice"
    failures.reset()


def test_open_editor_does_not_stop_the_card(monkeypatch):
    """Con una ventana de edición abierta AnkiConnect rechaza reescribir la
    plantilla. La nota se manda con la plantilla que haya."""
    from app import failures
    failures.reset()

    def invoke(action, **kw):
        if action == "updateModelTemplates":
            raise anki.AnkiError("Close the affected editor windows")
        return {"modelNames": ["LinguaMiner"], "modelFieldNames": config.NOTE_FIELDS,
                "modelTemplates": {"Card 1": {"Front": "old", "Back": "old"}},
                "modelStyling": {"css": anki.CARD_CSS}, "deckNames": ["D"],
                "addNote": 42}.get(action)
    monkeypatch.setattr(anki, "invoke", invoke)
    card = {"paraula": "Hund", "lema": "hund", "paraula_es": "perro", "frase": "x", "frase_es": ""}
    assert anki.send_card(card, "D") == 42
    assert failures.active()
    failures.reset()


def test_one_rejected_card_does_not_block_the_queue(tmp_path, monkeypatch):
    """El «enviando 2…» del PR #16: Anki rechazaba una tarjeta y todas las de
    detrás se quedaban sin mandar."""
    import app.main as main
    from app import failures
    failures.reset()
    main.CON = main.db.connect(tmp_path / "t.db")
    sid = main.db.create_session(main.CON, language="de", title="t", source_type="file",
                                 media_path="x", srt_source="none", model_size="-",
                                 duration_secs=1, transcript_json="[]")
    for w in ("mala", "buena", "otra"):
        main.db.create_card(main.CON, session_id=sid, segment_index=0, paraula=w, lema=w,
                            pos="", paraula_es="", frase=w, frase_es="", freq_rank="",
                            audio_file="", image_file="", font="", language="de")

    def send(card, deck, *a):
        if card["paraula"] == "mala":
            raise anki.AnkiError("cannot create note because it is empty")
        return 7
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: True)
    monkeypatch.setattr(main.anki, "send_card", send)
    assert main._flush() == 2
    assert [c["paraula"] for c in main.db.pending_cards(main.CON)] == ["mala"]
    assert any("mala" in m for m in failures.active())
    failures.reset()


def test_queue_stops_when_anki_stops_answering(tmp_path, monkeypatch):
    import requests

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    sid = main.db.create_session(main.CON, language="de", title="t", source_type="file",
                                 media_path="x", srt_source="none", model_size="-",
                                 duration_secs=1, transcript_json="[]")
    for w in ("a", "b"):
        main.db.create_card(main.CON, session_id=sid, segment_index=0, paraula=w, lema=w,
                            pos="", paraula_es="", frase=w, frase_es="", freq_rank="",
                            audio_file="", image_file="", font="", language="de")
    calls = []

    def send(card, deck, *a):
        calls.append(card["paraula"])
        raise requests.ConnectionError("Anki cerrado")
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: True)
    monkeypatch.setattr(main.anki, "send_card", send)
    assert main._flush() == 0 and len(calls) == 1, "no se insiste tarjeta por tarjeta"


def test_definition_uses_the_dictionary_entry_of_a_german_plural(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main.nouns, "lookup",
                        lambda f: ("Handschuh", "m", "Handschuhe") if f == "Handschuhe" else None)
    monkeypatch.setattr(main.wikdict, "lookup",
                        lambda t, limit=6: [("Guante.", "noun")] if t == "Handschuh" else [])
    assert main._definition("Handschuhe", "handschuhe", "NOUN") == "Guante."
    assert main._definition("xyz", "xyz", "NOUN") == ""
