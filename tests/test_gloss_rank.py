"""Glosas del popup ordenadas por la categoría de la palabra.

WikDict da para «pero» apple, though, apple tree: es el «pero» manzana. La
conjunción («but») no está. Sin ordenar, lo primero que veía quien aprende
español al tocar una de las palabras más frecuentes era «apple».
"""
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.main import _rank_glosses

PERO = [("apple", "noun"), ("though", "adv"), ("apple tree", "noun")]


def test_function_word_drops_glosses_of_a_homograph():
    assert _rank_glosses(PERO, "CCONJ", ("pero",)) == []


def test_function_word_keeps_matching_and_uncategorised():
    sobre = [("above", "prep"), ("envelope", "noun")]
    assert _rank_glosses(sobre, "ADP", ("sobre",)) == [("above", "prep")]
    sino = [("but", "")]                       # WikDict sin categoría: puede valer
    assert _rank_glosses(sino, "CCONJ", ("sino",)) == [("but", "")]


def test_content_word_reorders_but_keeps_everything():
    rapido = [("quick, fast", "adj"), ("quickly, swiftly", "adv")]
    assert _rank_glosses(rapido, "ADV", ("rápido",)) == [
        ("quickly, swiftly", "adv"), ("quick, fast", "adj")]
    assert _rank_glosses(PERO, "NOUN", ("pero",)) == [
        ("apple", "noun"), ("apple tree", "noun"), ("though", "adv")]


def test_proper_noun_homograph_is_dropped_for_lowercase_words():
    como = [("as", ""), ("Como", "")]
    assert _rank_glosses(como, "SCONJ", ("como",)) == [("as", "")]
    madrid = [("Madrid", "name")]
    assert _rank_glosses(madrid, "PROPN", ("Madrid",)) == madrid   # clicada en mayúscula


def test_unknown_pos_changes_nothing():
    assert _rank_glosses(PERO, "", ("pero",)) == PERO
    assert _rank_glosses(PERO, "X", ("pero",)) == PERO


@patch("app.main.ipa.ipa", return_value="")
@patch("app.main.translate.sentence", side_effect=lambda t: "EN:" + t)
@patch("app.main.translate.translate", side_effect=lambda t: "but")
@patch("app.main.nlp.selection_info",
       return_value={"lemma": "pero", "pos": "CCONJ", "separable": False})
def test_popup_for_pero_does_not_say_apple(_an, _tr, _sen, _ipa, tmp_path, monkeypatch):
    from app import wikdict
    seen = {}

    def fake_lookup(t, limit=6):
        seen["limit"] = limit
        return PERO if t == "pero" else []
    monkeypatch.setattr(wikdict, "lookup", fake_lookup)
    main.CON = main.db.connect(tmp_path / "t.db")
    r = TestClient(main.app).post(
        "/api/lookup", json={"selection": "pero", "sentence": "Pero no quiero."}).json()
    assert r["glosses"] == []
    assert seen["limit"] > 6, "se piden más para poder ordenar y quedarse con 4"
