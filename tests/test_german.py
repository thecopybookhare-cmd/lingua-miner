"""Alemán para hispanohablantes.

Probado de punta a punta antes de este cambio, el alemán funcionaba pero
enseñaba mal: «Der Film fängt um acht an» daba «fangen» → «captura»; los
sustantivos salían en minúscula, sin artículo y sin singular («handschuhe»,
sin definición); el Wikcionario español tenía 3.920 palabras alemanas;
ARD etiqueta sus subtítulos «deu» y la app solo buscaba «de»; y la fuente
Deutschlandfunk, que la app recomendaba, devolvía «no soportado».
"""
import sqlite3
from unittest.mock import patch

import pytest

import app.main as main
from app import config, languages, nlp, nouns, stream, wikdict


def _set(tmp_path, monkeypatch, lang="de", base="es"):
    p = tmp_path / "settings.json"
    p.write_text(f'{{"language": "{lang}", "base_language": "{base}"}}', encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", p)


# ---------- perfil ----------

def test_german_profile_for_spanish_speakers():
    de = languages.PROFILES["de"]
    assert languages.bases("de")[0] == "es"
    assert de["separable_particles"] is True
    assert de["wikdict_extra"]["es"].endswith("/de-es.sqlite3")
    assert "/8386d23dcf1847906f0f2988d3b0b82ef46975aa/" in de["noun_lexicon"], "fijado a un commit"
    assert de["noun_articles"] == {"m": "der", "f": "die", "n": "das"}
    assert "medium" in de["piper_voice"]
    names = [s["name"] for s in de["sources"]]
    assert "DW" in names and "Nachrichtenleicht" in names


# ---------- subtítulos con código de tres letras ----------

def test_sub_tags_include_iso_639_2():
    assert languages.sub_tags("de") == ["de", "deu", "ger"]
    assert languages.sub_tags("es") == ["es", "spa"]
    assert languages.sub_tags("xx") == ["xx"]


def test_ard_subtitles_tagged_deu_are_found():
    info = {"subtitles": {"deu": [{"ext": "vtt", "url": "https://ard/ut.vtt"}]}}
    assert stream._subs_url(info, "de") == ("https://ard/ut.vtt", False)


def test_import_finds_a_deu_subtitle_file(tmp_path, monkeypatch):
    import yt_dlp

    from app import youtube
    _set(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DL_DIR", tmp_path)
    seen = {}
    media = tmp_path / "Tatort-1.mp4"

    class FakeYDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            media.write_bytes(b"x")
            (tmp_path / "Tatort-1.deu.vtt").write_text("WEBVTT\n", encoding="utf-8")
            return {"title": "Tatort", "duration": 60, "subtitles": {"deu": [{}]}}

        def prepare_filename(self, info):
            return str(media)
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    out = youtube.download("x", "https://www.ardmediathek.de/video/x")
    assert "deu" in seen["subtitleslangs"]
    assert out["subtitles"].endswith(".deu.vtt")
    assert out["subs_kind"] == "youtube_subs"


# ---------- páginas que son listas (Deutschlandfunk) ----------

_PODCAST = {"_type": "playlist", "title": "Nachrichtenleicht", "entries": [
    {"title": "Nachrichtenleicht vom 09.11.2026", "duration": 329,
     "formats": [{"protocol": "https", "url": "https://dlf/nl_0911.mp3",
                  "ext": "mp3", "acodec": "mp3", "vcodec": "none"}]},
    {"title": "vom 06.11.2026", "duration": 321, "formats": []}]}


def test_playlist_page_opens_its_latest_episode(monkeypatch):
    monkeypatch.setattr(stream, "_extract", lambda u: _PODCAST)
    stream._CACHE.clear()
    r = stream.resolve("https://www.deutschlandfunk.de/podcast-nachrichtenleicht-100.html")
    stream._CACHE.clear()
    assert r["title"] == "Nachrichtenleicht vom 09.11.2026"
    assert r["is_audio"] is True and r["best_url"] == "https://dlf/nl_0911.mp3"


def test_import_downloads_only_the_first_item(tmp_path, monkeypatch):
    import yt_dlp

    from app import youtube
    _set(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DL_DIR", tmp_path)
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            return {"_type": "playlist", "entries": [{"title": "Episode 1", "duration": 300}]}

        def prepare_filename(self, info):
            seen["filename_for"] = info.get("title")
            return str(tmp_path / "ep1.mp3")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    out = youtube.download("x", "https://www.deutschlandfunk.de/podcast-100.html")
    assert seen["playlist_items"] == "1", "una lista de 100 episodios se bajaba entera"
    assert seen["filename_for"] == "Episode 1" and out["title"] == "Episode 1"


# ---------- diccionarios ----------

def test_german_wikdict_categories():
    assert wikdict._wikdict_pos("deu/Hund__Substantiv__1") == "noun"
    assert wikdict._wikdict_pos("deu/anfangen__Verb__1") == "verb"
    assert wikdict._wikdict_pos("deu/aber__Konjunktion__1") == "conj"
    assert wikdict._wikdict_pos("deu/ich__Personalpronomen__1") == "pron"
    assert wikdict._wikdict_pos("deu/hier__Lokaladverb__1") == "adv"
    assert wikdict._wikdict_pos("deu/doch__Modalpartikel__1") == "particle"


def test_glosses_merge_wiktionary_and_wikdict(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    a, b = sqlite3.connect(":memory:"), sqlite3.connect(":memory:")
    for con, rows in ((a, [("hund", "noun", "(Canis lupus familiaris) Perro.")]),
                      (b, [("hund", "noun", "perro, can"), ("kühlschrank", "noun", "nevera")])):
        con.execute("CREATE TABLE glosses (word TEXT, pos TEXT, gloss TEXT)")
        con.executemany("INSERT INTO glosses VALUES (?,?,?)", rows)
    monkeypatch.setattr(wikdict, "_CONS", {("de", "es"): [a, b]})
    assert wikdict.lookup("Hund") == [("(Canis lupus familiaris) Perro.", "noun"),
                                      ("perro, can", "noun")]
    assert wikdict.lookup("Kühlschrank") == [("nevera", "noun")], "solo en WikDict"
    assert len(wikdict.lookup("Hund", limit=1)) == 1


_CSV = """lemma,pos,genus,genus 1,genus 2,nominativ singular,nominativ plural,genitiv singular,dativ plural
Milch,Substantiv,f,,,Milch,,Milch,
Hund,Substantiv,m,,,Hund,Hunde,Hundes,Hunden
Hund,"Nachname,Substantiv",,,,Hund,,,
Handschuh,Substantiv,m,,,Handschuh,Handschuhe,Handschuhs,Handschuhen
Joghurt,Substantiv,,m,n,Joghurt,Joghurts,Joghurts,Joghurts
Leute,Substantiv,,,,,Leute,,Leuten
"""


def test_noun_lexicon_gives_article_and_singular(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    dbp = tmp_path / "nouns-de.sqlite"
    nouns.build_from_lines(_CSV.splitlines(), dbp)
    monkeypatch.setattr(nouns, "_CONS", {"de": sqlite3.connect(str(dbp))})
    assert nouns.lookup("Handschuhe") == ("Handschuh", "m", "Handschuhe")
    assert nouns.headword("Handschuhe") == ("der Handschuh (pl. Handschuhe)", "Handschuh", "m")
    assert nouns.headword("hund")[0] == "der Hund (pl. Hunde)", "el apellido va detrás"
    assert nouns.headword("Joghurt")[0] == "der/das Joghurt (pl. Joghurts)"
    assert nouns.headword("Leute")[0] == "die Leute (pl.)", "solo existe en plural"
    assert nouns.headword("xyz") is None
    assert nouns.headword("Milch")[0] == "die Milch", "sin plural, solo el artículo"


def test_old_noun_index_without_plural_is_replaced(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(nouns, "_CONS", {})
    (tmp_path / "nouns-de.sqlite").write_bytes(b"v1")

    class R:
        encoding = None

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self, chunk_size=1, decode_unicode=False):
            yield from _CSV.splitlines()
    monkeypatch.setattr(nouns.requests, "get", lambda *a, **k: R())
    assert nouns.lookup("Hunde") == ("Hund", "m", "Hunde")
    assert not (tmp_path / "nouns-de.sqlite").exists()
    assert (tmp_path / "nouns-de-v2.sqlite").exists()


# ---------- verbos separables ----------

def test_infinitive_guesses_cover_spacy_mistakes():
    assert "stehen" in nlp._infinitive_guesses("stehst", "stehsen")
    assert "kommen" in nlp._infinitive_guesses("Komm", "Komm")
    assert nlp._infinitive_guesses("fängt", "fangen")[0] == "fangen"
    assert "fangen" in nlp._infinitive_guesses("fängt", "")


def test_separable_verbs_with_real_spacy(tmp_path, monkeypatch):
    pytest.importorskip("de_core_news_sm")
    _set(tmp_path, monkeypatch)
    nlp._NLPS.pop("de", None)
    toks = {t["t"]: t for t in nlp.tokenize("Der Film fängt um acht Uhr an.")}
    assert toks["fängt"]["lemma"] == toks["an"]["lemma"] == "anfangen"
    assert toks["an"]["sep"] == "an"
    assert nlp.selection_info("stehst", "Wann stehst du auf?") == {
        "lemma": "aufstehen", "pos": "VERB", "separable": "auf"}
    assert nlp.analyze_selection("ging", "Sie ging ins Kino.")[0] == "gehen"


def test_token_version_bumped_so_old_transcripts_retokenize():
    assert nlp.TOK_VERSION >= 3


# ---------- lo que ve quien estudia ----------

def test_separable_verb_is_translated_as_an_infinitive(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    calls = []

    def tr(text):
        calls.append(text)
        return "para levantarse."
    monkeypatch.setattr(main.translate, "translate", tr)
    with patch("app.main.nlp.selection_info",
               return_value={"lemma": "aufstehen", "pos": "VERB", "separable": "auf"}):
        info = main._word_info("stehst", "Wann stehst du auf?")
    assert calls == ["um aufzustehen"], "suelto, «aufstehen» sale como «Levántate»"
    assert info["word_es"] == "levantarse"
    assert main._card_word(info) == "aufstehen — levantarse"


def test_noun_card_shows_article_and_spanish_gender(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    calls = []

    def tr(text):
        calls.append(text)
        return "Una llave"
    monkeypatch.setattr(main.translate, "translate", tr)
    monkeypatch.setattr(main.nouns, "headword", lambda *f: ("der Schlüssel", "Schlüssel", "m"))
    with patch("app.main.nlp.selection_info",
               return_value={"lemma": "schlüssel", "pos": "NOUN", "separable": ""}):
        info = main._word_info("Schlüssel", "Wo ist mein Schlüssel?")
    assert calls == ["ein Schlüssel"], "con «der» el traductor lo lee como genitivo"
    assert info["gloss_key"] == "Schlüssel"
    assert main._card_word(info) == "der Schlüssel — la llave"


def test_other_languages_keep_the_plain_translation(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch, lang="ca")
    monkeypatch.setattr(main, "_word_es", lambda sel, lemma: "perro")
    with patch("app.main.nlp.selection_info",
               return_value={"lemma": "gos", "pos": "NOUN", "separable": ""}):
        info = main._word_info("gos", "El gos corre.")
    assert info["headword"] == "" and main._card_word(info) == "perro"


# ---------- reproducción HLS en Chrome / WebView2 ----------

def test_chromium_uses_hls_js_not_its_native_hls():
    """Chrome 152 contesta «maybe» a HLS nativo y el de DW no lo reproduce:
    el vídeo se quedaba en 0:00. En Chromium manda hls.js; el nativo, solo en
    Safari/WKWebView."""
    import re
    from pathlib import Path
    js = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert re.search(r"const IS_CHROMIUM = /Chrome\\/\|Chromium\\/\|Edg\\//", js)
    assert 'IS_CHROMIUM || !V.canPlayType("application/vnd.apple.mpegurl")' in js



def test_any_german_verb_is_shown_and_translated_as_infinitive(tmp_path, monkeypatch):
    """Suelto, «weiß» se traducía «Blancos» y «diskutiere», «Discuta»."""
    _set(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(main.translate, "translate", lambda t: calls.append(t) or "Para saber.")
    with patch("app.main.nlp.selection_info",
               return_value={"lemma": "wissen", "pos": "VERB", "separable": ""}):
        info = main._word_info("weiß", "Ich weiß nicht.")
    assert calls == ["um zu wissen"]
    assert main._card_word(info) == "wissen — saber"


def test_verb_already_in_infinitive_has_no_redundant_headword(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch)
    monkeypatch.setattr(main.translate, "translate", lambda t: "para apagar")
    with patch("app.main.nlp.selection_info",
               return_value={"lemma": "ausschalten", "pos": "VERB", "separable": ""}):
        info = main._word_info("ausschalten", "Schalt das aus.")
    assert info["headword"] == "" and main._card_word(info) == "apagar"


def test_checked_infinitive_repairs_spacy_lemmas():
    assert nlp._checked_infinitive("Komm", "komm", "de") == "kommen"
    assert nlp._checked_infinitive("stehst", "stehsen", "de") == "stehen"
    assert nlp._checked_infinitive("weiß", "wissen", "de") == "wissen"
    assert nlp._checked_infinitive("ging", "gehen", "de") == "gehen"
