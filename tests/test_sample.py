"""El vídeo de ejemplo: probar el bucle sin buscar contenido ni esperar Whisper.

Las frases se escriben a mano, así que lo que hay que vigilar no es el código
sino el TEXTO: que las palabras existan de verdad en las listas de frecuencia
del idioma. Una frase con una palabra inventada o mal escrita rompería justo lo
que el ejemplo va a enseñar — el resaltado por frecuencia.
"""
import pytest

from app import languages, sample


def test_only_languages_whose_sentences_can_be_vouched_for():
    """Escribir japonés o coreano de muestra sin poder juzgar el resultado
    sería colar texto dudoso en la primera impresión del producto."""
    assert set(sample.SENTENCES) <= set(languages.PROFILES) | {"es"}
    for code in ("ja", "ko", "yue", "zh", "ru"):
        assert not sample.available(code), (
            f"{code} tiene ejemplo sin que nadie haya validado las frases")


@pytest.mark.parametrize("code", sorted(sample.SENTENCES))
def test_sentences_are_short_enough_to_read_on_screen(code):
    for frase in sample.SENTENCES[code]:
        assert 15 < len(frase) < 90, f"{code}: «{frase}» no cabe cómoda"
        assert frase[-1] in ".?!", f"{code}: «{frase}» sin puntuación final"


@pytest.mark.parametrize("code", sorted(sample.SENTENCES))
def test_every_word_exists_in_the_frequency_list(code):
    """Si una palabra no está en wordfreq sale con frecuencia 0 y el ejemplo
    la marcaría como rarísima — justo lo contrario de lo que enseña."""
    import re

    import wordfreq
    wf = languages.PROFILES.get(code, {}).get("wordfreq", code)
    raras = []
    for frase in sample.SENTENCES[code]:
        for w in re.findall(r"[^\W\d_]+", frase, re.UNICODE):
            if len(w) < 2:
                continue
            z = wordfreq.zipf_frequency(w.lower(), wf)
            if z < 2.0:
                raras.append((w, round(z, 2)))
    assert not raras, f"{code}: palabras que no reconoce wordfreq → {raras}"


@pytest.mark.parametrize("code", sorted(sample.SENTENCES))
def test_there_is_something_worth_recommending(code):
    """Un ejemplo donde nada supere el umbral no enseñaría el resaltado."""
    import re

    import wordfreq
    wf = languages.PROFILES.get(code, {}).get("wordfreq", code)
    frecuentes = sum(
        1 for frase in sample.SENTENCES[code]
        for w in re.findall(r"[^\W\d_]+", frase, re.UNICODE)
        if wordfreq.zipf_frequency(w.lower(), wf) >= 3.5)
    assert frecuentes >= 10, f"{code}: solo {frecuentes} palabras recomendables"


def test_languages_with_a_sample_can_actually_speak_it():
    """El ejemplo se genera con Piper: sin voz no hay audio que sincronizar."""
    for code in sample.SENTENCES:
        if code == "es":
            continue                      # el español es base, no de estudio
        assert languages.PROFILES[code].get("piper_voice"), (
            f"{code} tiene frases de ejemplo pero ninguna voz para leerlas")


def test_the_sample_session_is_tagged_with_its_language(tmp_path):
    """La biblioteca filtra por idioma: sin etiquetar, la sesión se crea y no
    se ve nunca. Pasó exactamente eso al escribir el endpoint."""
    from app import db
    con = db.connect(tmp_path / "t.db")
    sid = db.create_session(
        con, language="de", title="Deutsch — sample", source_type="local",
        media_path="/x.mp4", srt_source="sample", model_size="-",
        duration_secs=13.0, transcript_json="[]")
    assert [s["id"] for s in db.list_sessions(con, "de")] == [sid]
    assert db.list_sessions(con, "ca") == [], "no debe aparecer en otro idioma"


def test_unknown_language_is_rejected_not_crashed():
    with pytest.raises(ValueError):
        sample.build("xx")
