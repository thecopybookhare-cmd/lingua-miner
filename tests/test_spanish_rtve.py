"""Español como idioma de estudio, y RTVE Play como fuente.

Añadirlo destapó tres fallos que ya afectaban a otros idiomas: «Ver online»
buscaba siempre subtítulos en catalán, RTVE no entrega su lista de subtítulos
si no se le pide, y el asistente de primer arranque no daba nunca por listo
un idioma sin diccionario Apertium que descargar.
"""
import sqlite3
import sys
import types

from app import config, stream, wikdict
from app import languages as L


def _set(tmp_path, monkeypatch, lang, base="en"):
    p = tmp_path / "settings.json"
    p.write_text(f'{{"language": "{lang}", "base_language": "{base}"}}',
                 encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", p)


# ---------- perfil ----------

def test_spanish_is_activable_with_english_base_only():
    assert "es" in L.activable()
    assert L.bases("es") == ["en"], "estudiar español con base española no tiene sentido"
    assert L.has_spanish_base("es") is False


def test_spanish_never_falls_back_to_spanish_base(tmp_path, monkeypatch):
    """Con la interfaz en español, "auto" pediría base es: tiene que caer al inglés."""
    p = tmp_path / "settings.json"
    p.write_text('{"language": "es", "ui_lang": "es"}', encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", p)
    assert L.active_code() == "es"
    assert L.base_code() == "en"
    spec = L.translate_spec()
    assert spec["repo"] == "gaudi/opus-mt-es-en-ctranslate2"
    assert spec["dir"] == "translate-spa-eng"


def test_spanish_profile_is_complete():
    es = L.PROFILES["es"]
    need = ["name", "wordfreq", "espeak", "spacy", "whisper_models",
            "default_whisper", "translate_dir", "piper_voice", "wikdict_url_en"]
    assert not [k for k in need if not es.get(k)]
    assert es["spacy"] == "es_core_news_sm"
    assert any("rtve.es/play" in s["url"] for s in es["sources"])


def test_spanish_glosses_come_from_the_small_wikdict_file():
    u = L.PROFILES["es"]["wikdict_url_en"]
    assert u.startswith("https://download.wikdict.com/") and u.endswith("es-en.sqlite3")


# ---------- glosas desde WikDict ----------

def _fake_wikdict(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE translation_grouped (lexentry TEXT, written_rep TEXT,"
                " min_sense_num TEXT, sense_list TEXT, trans_list TEXT,"
                " score REAL, importance REAL)")
    con.executemany("INSERT INTO translation_grouped VALUES (?,?,?,?,?,?,?)", [
        ("spa/gato__sustantivo_masculino__1", "gato", "", "", "jack", 100, 3.2),
        ("spa/gato__sustantivo_masculino_y_femenino__1", "gato", "", "",
         "cat | tomcat", 180, 5.3),
        ("spa/casa__sustantivo_femenino__1", "casa", "", "", "house | home", 140, 5.0),
        ("spa/casa__sustantivo_femenino__1", "casa", "01", "", "home | house", 120, 4.4),
        (None, "trabajar", None, None, "work", 2, 0.4),
        ("spa/Madrid__sustantivo_propio__1", "Madrid", "", "", "Madrid", 140, 1.0),
    ])
    con.commit()
    con.close()


def test_wikdict_sqlite_becomes_the_usual_gloss_index(tmp_path, monkeypatch):
    src, dbp = tmp_path / "es-en.sqlite3", tmp_path / "wikdict-es-en.sqlite"
    _fake_wikdict(src)
    wikdict.build_from_wikdict(src, dbp)
    monkeypatch.setattr(wikdict, "_CONS", {
        ("es", "en"): sqlite3.connect(str(dbp), check_same_thread=False)})
    _set(tmp_path, monkeypatch, "es")
    assert wikdict.lookup("gato") == [("cat, tomcat", "noun"), ("jack", "noun")]
    assert wikdict.lookup("casa") == [("house, home", "noun")]   # mismo grupo, otro orden
    assert wikdict.lookup("trabajar") == [("work", "")]          # fila sin lexentry
    assert wikdict.lookup("Madrid") == [("Madrid", "name")]
    assert not (tmp_path / "wikdict-es-en.part").exists()


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        yield self.body

    def iter_lines(self, chunk_size=512, decode_unicode=False, delimiter=None):
        yield from self.body.splitlines()


def test_kaikki_is_indexed_on_the_fly_and_old_jsonl_removed(tmp_path, monkeypatch):
    """Antes el JSONL entero (hasta ~1 GB) se guardaba y no se borraba nunca."""
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    _set(tmp_path, monkeypatch, "de")
    monkeypatch.setattr(wikdict, "_CONS", {})
    viejo = tmp_path / "wikdict-ru-en.jsonl"
    viejo.write_text("{}", encoding="utf-8")
    body = b'{"word": "Hund", "pos": "noun", "senses": [{"glosses": ["dog"]}]}\n'
    monkeypatch.setattr(wikdict.requests, "get", lambda *a, **k: _Resp(body))
    assert wikdict.lookup("hund") == [("dog", "noun")]
    assert (tmp_path / "wikdict-de-en.sqlite").exists()
    assert not list(tmp_path.glob("*.jsonl"))


def test_wikdict_download_goes_through_the_sqlite_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    _set(tmp_path, monkeypatch, "es")
    monkeypatch.setattr(wikdict, "_CONS", {})
    src = tmp_path / "fuente.sqlite3"
    _fake_wikdict(src)
    monkeypatch.setattr(wikdict.requests, "get",
                        lambda *a, **k: _Resp(src.read_bytes()))
    assert wikdict.lookup("gato")[0] == ("cat, tomcat", "noun")
    assert not list(tmp_path.glob("*.src.part")), "la descarga temporal debe borrarse"


# ---------- subtítulos del propio vídeo ----------

def test_subs_follow_the_study_language_not_catalan(tmp_path, monkeypatch):
    _set(tmp_path, monkeypatch, "es")
    info = {"subtitles": {
        "ca": [{"ext": "vtt", "url": "https://x/ca.vtt"}],
        "es": [{"ext": "vtt", "url": "https://x/es.vtt"}]}}
    assert stream._subs_url(info) == ("https://x/es.vtt", False)


def test_subs_accept_regional_variants():
    info = {"subtitles": {}, "automatic_captions": {
        "pt-BR": [{"ext": "vtt", "url": "https://x/ptbr.vtt"}]}}
    assert stream._subs_url(info, "pt") == ("https://x/ptbr.vtt", True)
    assert stream._subs_url(info, "p") == ("", False), "un prefijo suelto no vale"


def test_extract_asks_for_the_subtitle_list(monkeypatch):
    """RTVE solo consulta su API de subtítulos con writesubtitles activado."""
    seen = {}

    class FakeYDL:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            assert download is False
            return {}
    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=FakeYDL))
    stream._extract("https://www.rtve.es/play/videos/x/1/")
    assert seen.get("writesubtitles") is True
    assert seen.get("skip_download") is True


def test_rtve_video_resolves_with_spanish_subtitles(tmp_path, monkeypatch):
    """Forma real de RTVE: mp4 progresivos sin altura ni códecs, DASH y HLS."""
    _set(tmp_path, monkeypatch, "es")
    info = {"title": "¿Somos gregarios?", "duration": 1855.2, "formats": [
        {"protocol": "http", "url": "http://rtve/2.mp4", "ext": "mp4"},
        {"protocol": "http_dash_segments", "height": 720, "vcodec": "avc1",
         "acodec": "none", "url": "https://rtve/d.mpd"},
        {"protocol": "m3u8_native", "height": 1080, "vcodec": "avc1",
         "acodec": "mp4a", "url": "https://rtve/1080.m3u8",
         "manifest_url": "https://rtve/master.m3u8"}],
        "subtitles": {"es": [{"ext": "vtt", "url": "https://rtve/sub.vtt"}]}}
    monkeypatch.setattr(stream, "_extract", lambda u: info)
    monkeypatch.setattr(stream, "_browser_can_load", lambda u: True)
    stream._CACHE.clear()
    r = stream.resolve("https://www.rtve.es/play/videos/asi-somos/x/17276514/")
    stream._CACHE.clear()
    assert r["is_hls"] is True and r["is_audio"] is False
    assert r["best_url"] == "https://rtve/master.m3u8"
    assert r["subs_url"] == "https://rtve/sub.vtt"


def test_radio_with_mp3_and_hls_opens_as_podcast(monkeypatch):
    """RTVE Play Radio sirve mp3 y HLS. Con el HLS primero se abría como un
    vídeo sin imagen."""
    info = {"title": "Episodio", "duration": 1884, "formats": [
        {"protocol": "m3u8_native", "url": "https://rtve/a.m3u8",
         "manifest_url": "https://rtve/a.m3u8", "ext": "mp4"},
        {"protocol": "https", "url": "https://rtve/a.mp3", "acodec": "mp3",
         "ext": "mp3"}]}
    monkeypatch.setattr(stream, "_extract", lambda u: info)
    monkeypatch.setattr(stream, "_browser_can_load", lambda u: True)
    stream._CACHE.clear()
    r = stream.resolve("https://www.rtve.es/play/audios/x/1/")
    stream._CACHE.clear()
    assert r["is_audio"] is True and r["is_hls"] is False
    assert r["best_url"] == "https://rtve/a.mp3"


# ---------- asistente de primer arranque ----------

def test_setup_is_ready_without_apertium_or_forms(tmp_path, monkeypatch):
    """Sin bidix_url ni forms_url no hay nada que bajar: el paso está hecho."""
    import app.main as main
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    for code in ("es", "de", "ja"):
        _set(tmp_path, monkeypatch, code)
        c = main._setup_checks()
        assert c["dictionary"] is True, code
        assert c["forms"] is True, code


def test_setup_still_waits_for_catalan_dictionaries(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    _set(tmp_path, monkeypatch, "ca", base="es")
    c = main._setup_checks()
    assert c["dictionary"] is False and c["forms"] is False


def test_streamed_subtitles_keep_their_accents(monkeypatch):
    """RTVE manda "text/vtt" sin charset y requests lo leía como Latin-1."""
    import requests

    import app.main as main
    body = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nSí, la canción del año.\n".encode()

    class R:
        content = body
        text = body.decode("latin-1")             # lo que daba requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    tj, kind = main._stream_subs_transcript({"subs_url": "https://rtve/sub.vtt"})
    assert kind == "youtube_subs"
    import json
    texto = json.loads(tj)[0]["text"]
    assert texto == "Sí, la canción del año.", texto


# ---------- subtítulos troceados en HLS (radio de RTVE) ----------

_PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXTINF:5.184,
https://rne/0/sub.vtt
#EXTINF:5.184,
1/sub.vtt
#EXT-X-ENDLIST
"""
_SEG0 = """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0

00:00:00.949 --> 00:00:01.930
Hola, buenas tardes,

00:00:03.000 --> 00:00:05.184
¿España se juega algo?
"""
_SEG1 = """WEBVTT
X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0

00:00:05.184 --> 00:00:06.500
¿España se juega algo?

00:00:07.000 --> 00:00:09.000
Nos jugamos todos.
"""


def test_hls_subtitle_playlist_is_read_fragment_by_fragment(monkeypatch):
    """Antes se parseaba la lista .m3u8 como si fuera el subtítulo: 0 líneas."""
    pages = {"https://rne/vtt/x.m3u8": _PLAYLIST, "https://rne/0/sub.vtt": _SEG0,
             "https://rne/vtt/1/sub.vtt": _SEG1}
    monkeypatch.setattr(stream, "_get_text", lambda u: pages[u])
    segs = stream.subtitle_segments("https://rne/vtt/x.m3u8")
    assert [s["text"] for s in segs] == [
        "Hola, buenas tardes,", "¿España se juega algo?", "Nos jugamos todos."]
    assert segs[1]["start"] == 3.0 and segs[1]["end"] == 6.5, "frase partida entre dos trozos"
    assert not any("WEBVTT" in s["text"] or "X-TIMESTAMP" in s["text"] for s in segs)


def test_plain_vtt_still_parses_directly(monkeypatch):
    monkeypatch.setattr(stream, "_get_text", lambda u: _SEG0)
    assert len(stream.subtitle_segments("https://rtve/sub.vtt")) == 2
