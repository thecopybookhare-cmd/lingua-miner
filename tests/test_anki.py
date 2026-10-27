from unittest.mock import MagicMock, patch

import pytest

from app import anki


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
