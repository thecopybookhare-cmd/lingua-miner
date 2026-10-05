"""yt-dlp con Deno, y «Ver online» sin sesiones mudas en 0:00."""
import sys
import types

import pytest
import requests
import yt_dlp

from app import stream, youtube, ytdlp


def _fake_deno(monkeypatch, path):
    mod = types.ModuleType("deno")
    mod.find_deno_bin = lambda: path
    monkeypatch.setitem(sys.modules, "deno", mod)


def test_deno_from_the_pypi_package(monkeypatch):
    _fake_deno(monkeypatch, "/venv/bin/deno")
    assert ytdlp.deno_path() == "/venv/bin/deno"
    assert ytdlp.base_opts() == {"js_runtimes": {"deno": {"path": "/venv/bin/deno"}}}


def test_without_deno_it_says_so(monkeypatch):
    monkeypatch.setitem(sys.modules, "deno", None)        # import deno -> ImportError
    monkeypatch.setattr(ytdlp.shutil, "which", lambda _: None)
    monkeypatch.setattr(ytdlp.failures, "_SEEN", {})
    assert ytdlp.base_opts() == {}
    assert "ytdlp-no-js" in ytdlp.failures._SEEN          # visible en la app, no solo en el log


class _Captured(Exception):
    pass


def _capture_ytdl_opts(monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, opts):
            seen.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, *a, **k):
            raise _Captured

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Fake)
    return seen


def test_watch_online_gives_ytdlp_deno(monkeypatch):
    _fake_deno(monkeypatch, "/venv/bin/deno")
    seen = _capture_ytdl_opts(monkeypatch)
    with pytest.raises(_Captured):
        stream._extract("https://www.youtube.com/watch?v=x")
    assert seen["js_runtimes"] == {"deno": {"path": "/venv/bin/deno"}}


def test_download_gives_ytdlp_deno(monkeypatch):
    _fake_deno(monkeypatch, "/venv/bin/deno")
    seen = _capture_ytdl_opts(monkeypatch)
    with pytest.raises(_Captured):
        youtube.download("job", "https://www.youtube.com/watch?v=x")
    assert seen["js_runtimes"] == {"deno": {"path": "/venv/bin/deno"}}


class _Resp:
    def __init__(self, acao):
        self.ok = True
        self.headers = {"Access-Control-Allow-Origin": acao} if acao else {}

    def close(self):
        pass


@pytest.mark.parametrize("acao,ok", [
    ("*", True),
    ("http://localhost:8977", True),
    (None, False),                          # YouTube: 200, pero sin CORS
    ("https://www.youtube.com", False),
])
def test_hls_needs_cors_for_the_browser(monkeypatch, acao, ok):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(acao))
    assert stream._browser_can_load("https://x/master.m3u8") is ok


def test_unreachable_hls_is_not_offered(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(requests, "get", boom)
    assert stream._browser_can_load("https://x/master.m3u8") is False


def test_youtube_hls_without_cors_sends_to_download(monkeypatch):
    # Sin Deno, YouTube no da el formato 18 y solo queda su HLS, que el
    # navegador no puede cargar. Antes se abría la sesión y se quedaba en 0:00.
    stream._CACHE.clear()
    info = {"title": "Rick", "duration": 213, "formats": [
        {"protocol": "m3u8_native", "height": 2160, "vcodec": "avc1", "acodec": "mp4a",
         "url": "https://manifest.googlevideo.com/v.m3u8",
         "manifest_url": "https://manifest.googlevideo.com/master.m3u8"},
        {"protocol": "https", "height": 1080, "vcodec": "vp9", "acodec": "none",
         "format_note": "1080p", "url": "https://rr/dash-video"}]}
    monkeypatch.setattr(stream, "_extract", lambda u: info)
    monkeypatch.setattr(stream, "_browser_can_load", lambda u: False)
    assert stream.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == \
        {"needs_download": True, "title": "Rick"}
    stream._CACHE.clear()
