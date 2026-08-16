"""Importar vocabulario ya sabido desde otra herramienta.

Quien viene de Migaku o jpdb con miles de palabras ve su primer vídeo rojo
entero si la app las trata como nuevas — y ahí es donde se abandona una
herramienta. El lector es deliberadamente tolerante en vez de soportar
formatos concretos: no tengo exportaciones reales para verificar sus esquemas.
"""
import pytest

from app import wordlist as W


def test_plain_text_one_per_line():
    assert W.parse("gos\ncasa\n\nllibre\n") == ["gos", "casa", "llibre"]


def test_comments_and_blank_lines_are_not_vocabulary():
    assert W.parse("# mi lista\ngos\n\n  \ncasa") == ["gos", "casa"]


def test_csv_with_header_picks_the_word_column():
    csv = "id,word,interval\n7,gos,21\n8,casa,4\n"
    assert W.parse(csv) == ["gos", "casa"]


def test_csv_without_header_uses_the_first_column():
    assert W.parse("gos,21\ncasa,4\n") == ["gos", "casa"]


def test_tsv_like_an_anki_export():
    assert W.parse("Expression\tMeaning\n映画\tmovie\n昨日\tyesterday\n") == ["映画", "昨日"]


def test_json_list_of_strings():
    assert W.parse('["gos","casa"]') == ["gos", "casa"]


def test_json_list_of_objects_picks_a_word_ish_key():
    raw = '[{"spelling":"映画","state":"known"},{"spelling":"本","state":"known"}]'
    assert W.parse(raw) == ["映画", "本"]


def test_our_own_export_is_readable_too():
    raw = '{"version":1,"statuses":{"gos":"known","cel":"known"}}'
    assert W.parse(raw) == ["gos", "cel"]


@pytest.mark.parametrize("estado", ["new", "learning", "ignored", "suspended"])
def test_words_the_source_says_you_do_not_know_are_skipped(estado):
    """Importar como conocida una palabra que estás aprendiendo la sacaría de
    las recomendaciones justo cuando más falta hacen."""
    raw = f'[{{"word":"sí","state":"known"}},{{"word":"no","state":"{estado}"}}]'
    assert W.parse(raw) == ["sí"]


def test_status_column_in_csv_is_honoured():
    csv = "word,status\ngos,known\ncasa,new\n"
    assert W.parse(csv) == ["gos"]


def test_notes_in_brackets_are_stripped():
    """Las exportaciones suelen traer «palabra (traducción)»."""
    assert W.parse("gos (perro)\ncasa [house]\n映画（えいが）") == ["gos", "casa", "映画"]


def test_duplicates_collapse_case_insensitively():
    assert W.parse("Gos\ngos\nGOS") == ["Gos"]


def test_empty_input_is_empty_not_an_error():
    assert W.parse("") == [] and W.parse("   \n\n") == []


def test_broken_json_falls_back_instead_of_exploding():
    """Un archivo a medias no debe reventar la importación."""
    assert W.parse('["gos", "casa"') != []


def test_bom_does_not_become_part_of_the_first_word():
    """Excel guarda CSV con BOM y sin esto la primera palabra sale con basura."""
    assert W.parse("﻿gos\ncasa") == ["gos", "casa"]


def test_import_endpoint_marks_without_overwriting(tmp_path):
    from fastapi.testclient import TestClient

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    main.db.set_word_status(main.CON, "gos", "learning", "ca")

    r = c.post("/api/words/import-list",
               files={"file": ("mis-palabras.txt", b"gos\ncasa\n", "text/plain")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["skipped"] >= 1, "lo que ya marcaste a mano manda"
    assert main.db.word_statuses(main.CON, "ca")["gos"] == "learning"


def test_import_endpoint_rejects_a_file_with_no_words(tmp_path):
    from fastapi.testclient import TestClient

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    r = c.post("/api/words/import-list",
               files={"file": ("vacio.txt", b"   \n\n", "text/plain")})
    assert r.status_code == 400
    assert "palabra" in r.json()["error"]


# ---------- el lema de una palabra suelta ----------

class _Formas:
    """Doble del diccionario de formas. Con datos reales «gos» devuelve
    [('gos', NOUN), ('gosar', VERB)] y «coneixes» devuelve [('conèixer',
    VERB)] — el conftest lo desactiva a propósito, así que aquí se prueba la
    lógica, no que el archivo esté descargado."""

    TABLA = {"gos": [("gos", "NOUN"), ("gosar", "VERB")],
             "coneixes": [("conèixer", "VERB")]}

    @classmethod
    def lookup(cls, w):
        return cls.TABLA.get(w.lower(), [])


def test_isolated_words_are_not_lemmatised_by_guesswork():
    """spaCy necesita contexto: con «gos» a pelo devuelve «gosar» (atreverse),
    no «gos» (perro). Importar así marcaba miles de lemas equivocados, y venía
    pasando desde que existe el sembrado desde mazos de Anki. El diccionario
    de formas manda porque su primer candidato sí es el correcto."""
    from app import nlp, vocab
    assert vocab._lemma_of("gos", _Formas, nlp) == "gos"


def test_inflected_forms_still_reach_their_lemma():
    """Arreglar lo de arriba no puede costar la lematización de verdad."""
    from app import nlp, vocab
    assert vocab._lemma_of("coneixes", _Formas, nlp) == "conèixer"


def test_without_a_forms_dictionary_the_word_is_kept_as_is():
    """Sin diccionario de formas, quedarse en la superficie es peor que
    lematizar bien pero mucho mejor que marcar una palabra que el usuario no
    ha dicho conocer."""
    from app import nlp, vocab

    class SinFormas:
        @staticmethod
        def lookup(_w):
            return []
    assert vocab._lemma_of("Gos", SinFormas, nlp) == "gos"
