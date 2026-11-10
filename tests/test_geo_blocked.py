"""Vídeos que el sitio no deja ver desde esta conexión (bloqueo por país).

Medido desde EE. UU. con RTVE: de un programa bloqueado, yt-dlp solo saca dos
mp4 sin altura ni códecs, y los dos responden 403 ("fvod in US"). La app los
tomaba por audio y abría el vídeo como podcast: sin imagen, en 0:00 y sin
ningún error. Importar fallaba con un «HTTP Error 403: Forbidden» crudo.
"""
import time

import pytest
import yt_dlp
from fastapi.testclient import TestClient

import app.main as main
from app import config, jobs, stream, youtube, ytdlp

# Lo que yt-dlp devuelve de RTVE para un programa bloqueado (EE. UU.)
_RTVE_OUTSIDE = {"title": "Colón ADN", "duration": 6370, "formats": [
    {"format_id": "0", "protocol": "http", "ext": "mp4",
     "url": "http://rtve-mediavod-lote3.rtve.es/resources/a.mp4"},
    {"format_id": "1", "protocol": "http", "ext": "mp4",
     "url": "http://rtve-mediavod-lote3.rtve.es/resources/b.mp4"}],
    "subtitles": {"es": [{"ext": "vtt", "url": "https://rtve/es.vtt"}]}}


@pytest.fixture(autouse=True)
def _fresh_cache():
    stream._CACHE.clear()
    yield
    stream._CACHE.clear()


def test_bare_mp4s_are_video_not_a_podcast(monkeypatch):
    """Donde sí se pueden ver, esos mp4 son un vídeo, no audio."""
    monkeypatch.setattr(stream, "_extract", lambda u: _RTVE_OUTSIDE)
    r = stream.resolve("https://www.rtve.es/play/videos/x/16281015/")
    assert r["is_audio"] is False and r["is_hls"] is False
    assert r["best_url"].endswith("b.mp4")             # el último: el mejor
    assert r["formats"] == [{"height": 0, "label": "MP4", "url": r["best_url"]}]


def test_forbidden_file_says_blocked_instead_of_opening(monkeypatch):
    monkeypatch.setattr(stream, "_extract", lambda u: _RTVE_OUTSIDE)
    monkeypatch.setattr(stream, "_forbidden", lambda u: True)
    r = stream.resolve("https://www.rtve.es/play/videos/x/16281015/")
    assert r == {"blocked": True, "title": "Colón ADN"}
    assert stream.stream_url("https://www.rtve.es/play/videos/x/16281015/") == ("", [], False)


def test_blocked_result_is_not_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(stream, "_extract", lambda u: calls.append(u) or _RTVE_OUTSIDE)
    monkeypatch.setattr(stream, "_forbidden", lambda u: True)
    stream.resolve("https://rtve/x")
    stream.resolve("https://rtve/x")
    assert len(calls) == 2, "un bloqueo puede ser temporal (VPN, viaje): se reintenta"


def test_hls_is_not_probed_twice(monkeypatch):
    """El HLS ya pasó por _browser_can_load: no hace falta otra petición."""
    info = {"title": "t", "duration": 10, "formats": [
        {"protocol": "m3u8_native", "height": 720, "vcodec": "avc1",
         "acodec": "mp4a", "url": "https://c/v.m3u8",
         "manifest_url": "https://c/master.m3u8"}]}
    monkeypatch.setattr(stream, "_extract", lambda u: info)
    monkeypatch.setattr(stream, "_browser_can_load", lambda u: True)
    monkeypatch.setattr(stream, "_forbidden",
                        lambda u: (_ for _ in ()).throw(AssertionError("no debía llamarse")))
    assert stream.resolve("https://c/page")["is_hls"] is True


def test_geo_error_during_extraction_says_blocked(monkeypatch):
    def geo(u):
        raise yt_dlp.utils.DownloadError(
            "ERROR: The uploader has not made this video available in your country")
    monkeypatch.setattr(stream, "_extract", geo)
    assert stream.resolve("https://www.youtube.com/watch?v=x") == {
        "blocked": True, "title": "https://www.youtube.com/watch?v=x"}


@pytest.mark.parametrize("exc,blocked", [
    (yt_dlp.utils.DownloadError("ERROR: unable to download video data: HTTP Error 403: Forbidden"), True),
    (yt_dlp.utils.DownloadError("ERROR: HTTP Error 451: Unavailable For Legal Reasons"), True),
    (yt_dlp.utils.DownloadError(
        "x", exc_info=(yt_dlp.utils.GeoRestrictedError, yt_dlp.utils.GeoRestrictedError("geo"), None)), True),
    (yt_dlp.utils.DownloadError("ERROR: Unsupported URL: https://example.com"), False),
    (RuntimeError("HTTP Error 404: Not Found"), False),
])
def test_is_blocked(exc, blocked):
    assert ytdlp.is_blocked(exc) is blocked


@pytest.mark.real_probe
@pytest.mark.parametrize("status,forbidden", [(403, True), (451, True), (401, True),
                                              (206, False), (200, False), (404, False)])
def test_forbidden_reads_the_status(monkeypatch, status, forbidden):
    import requests

    class R:
        status_code = status

        def close(self):
            pass
    seen = {}

    def get(url, headers=None, **k):
        seen.update(headers or {})
        return R()
    monkeypatch.setattr(requests, "get", get)
    assert stream._forbidden("http://x/a.mp4") is forbidden
    assert seen.get("Range") == "bytes=0-0", "solo un byte, no el vídeo entero"
    assert seen.get("User-Agent", "").startswith("Mozilla/"), (
        "como el navegador: RTVE da 403 al User-Agent de python-requests")


@pytest.mark.real_probe
def test_forbidden_lets_the_player_decide_when_offline(monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("sin red")
    monkeypatch.setattr(requests, "get", boom)
    assert stream._forbidden("http://x/a.mp4") is False


def test_watch_online_shows_the_blocked_message(tmp_path, monkeypatch):
    main.CON = main.db.connect(tmp_path / "t.db")
    monkeypatch.setattr(main.stream, "resolve", lambda u: {"blocked": True, "title": "t"})
    c = TestClient(main.app)
    jid = c.post("/api/sessions/stream",
                 json={"url": "https://www.rtve.es/play/videos/x/1/"}).json()["job_id"]
    t0 = time.time()
    while main.jobs.get(jid)["status"] not in ("done", "error"):
        assert time.time() - t0 < 60
        time.sleep(0.05)
    j = main.jobs.get(jid)
    assert j["status"] == "error" and j["key"] == "err.geo_blocked"
    assert "403" in j["message"]


def test_import_turns_a_403_into_the_blocked_message(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError(
                "ERROR: unable to download video data: HTTP Error 403: Forbidden")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(config, "DL_DIR", tmp_path)
    with pytest.raises(jobs.JobError) as e:
        youtube.download("x", "https://www.rtve.es/play/videos/x/1/")
    assert e.value.key == "err.geo_blocked"


def test_other_import_errors_pass_through(tmp_path, monkeypatch):
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError("ERROR: Unsupported URL")
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(config, "DL_DIR", tmp_path)
    with pytest.raises(yt_dlp.utils.DownloadError):
        youtube.download("x", "https://example.com/")


def test_stream_cache_follows_the_study_language(tmp_path, monkeypatch):
    """Los subtítulos elegidos dependen del idioma: la caché no puede
    devolver los del idioma anterior."""
    info = {"title": "t", "duration": 10, "formats": [
        {"height": 360, "vcodec": "avc1", "acodec": "mp4a", "protocol": "https",
         "format_note": "360p", "url": "u360"}],
        "subtitles": {"ca": [{"ext": "vtt", "url": "https://x/ca.vtt"}],
                      "es": [{"ext": "vtt", "url": "https://x/es.vtt"}]}}
    monkeypatch.setattr(stream, "_extract", lambda u: info)
    p = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", p)
    p.write_text('{"language": "ca", "base_language": "es"}', encoding="utf-8")
    assert stream.resolve("https://x/v")["subs_url"] == "https://x/ca.vtt"
    p.write_text('{"language": "es", "base_language": "en"}', encoding="utf-8")
    assert stream.resolve("https://x/v")["subs_url"] == "https://x/es.vtt"
