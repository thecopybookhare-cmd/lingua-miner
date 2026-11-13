"""Resolución de streams reproducibles (YouTube, 3cat…) sin descargar.

yt-dlp extrae las URLs de los formatos progresivos (video+audio en un solo
archivo, proto http) que un <video> puede reproducir directo y ffmpeg puede
leer para las tarjetas. Las URLs caducan y van atadas a la IP, así que se
re-resuelven al abrir la sesión y al minar."""
import re
import time

from . import failures, subs, ytdlp

_DIRECT = re.compile(r"\.(mp4|m3u8|webm|mov|m4v)(\?|$)", re.I)
_VIDEO_EXT = {"mp4", "webm", "mkv", "mov", "m4v", "flv", "ts"}
# Quien reproduce es el navegador: las comprobaciones se hacen como él. El CDN
# de RTVE responde 403 al User-Agent de python-requests y 206 a un navegador.
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# Abrir una sesión de streaming dispara varias llamadas a yt-dlp seguidas
# (resolver + cambiar calidad + minar), cada una ~1-3 s. Las URLs de yt-dlp
# caducan en horas, así que cachear el resultado unos minutos es seguro y
# recorta la latencia de esas ráfagas.
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 240.0


def _cache_get(key: str) -> dict | None:
    now = time.time()
    for k in [k for k, (t, _) in _CACHE.items() if now - t >= _TTL]:
        del _CACHE[k]                     # poda: que no crezca sin límite
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _TTL:
        return hit[1]
    return None


def is_direct(url: str) -> bool:
    return bool(_DIRECT.search(url or ""))


def _progressive(info: dict) -> list[dict]:
    """Formatos reproducibles directo (un solo archivo http con video+audio).

    La distinción fiable es el PROTOCOLO: 'https'/'http' progresivo vs
    'http_dash_segments' (fragmentado) o 'm3u8'. Los códecs pueden venir
    como None (3cat no los reporta) — no se puede filtrar por ahí."""
    out = []
    for f in info.get("formats", []):
        proto = f.get("protocol") or ""
        if "dash" in proto or "m3u8" in proto or not proto.startswith("http"):
            continue
        if not f.get("url") or not f.get("height"):
            continue
        note = (f.get("format_note") or "").lower()
        if "only" in note:
            continue
        if f.get("acodec") == "none" or f.get("vcodec") == "none":
            continue                     # explícitamente pista suelta
        out.append({"height": f.get("height") or 0,
                    "label": f.get("format_note") or f"{f.get('height')}p",
                    "url": f["url"]})
    # dedupe por altura (quedarse con el primero)
    seen, uniq = set(), []
    for f in sorted(out, key=lambda x: x["height"]):
        if f["height"] in seen:
            continue
        seen.add(f["height"])
        uniq.append(f)
    return uniq


def _bare_file(f: dict) -> bool:
    """Archivo http suelto con extensión de vídeo pero sin altura ni códecs.

    Es todo lo que RTVE da fuera de su zona: dos mp4 sin metadatos. Sin esto
    contaban como «solo audio» y el vídeo se abría como podcast, sin imagen y
    en 0:00 (el mismo síntoma del issue #4)."""
    proto = f.get("protocol") or ""
    return (proto.startswith("http") and "dash" not in proto
            and "m3u8" not in proto and not f.get("height")
            and f.get("vcodec") is None and f.get("acodec") is None
            and (f.get("ext") or "") in _VIDEO_EXT and bool(f.get("url")))


def _unlabeled_video(info: dict) -> list[dict]:
    """El mejor de esos mp4 sin altura, como último recurso de vídeo."""
    bare = [f for f in info.get("formats", []) if _bare_file(f)]
    if not bare:
        return []
    f = bare[-1]                         # yt-dlp ordena de peor a mejor
    return [{"height": 0, "label": f.get("format_note") or "MP4", "url": f["url"]}]


def _forbidden(url: str) -> bool:
    """¿El servidor rechaza el archivo elegido (401/403/451)?

    Se pide un solo byte. Sin esto, un vídeo bloqueado por país abría la
    sesión igual y el reproductor se quedaba mudo. Si la comprobación no
    llega a responder, se deja decidir al reproductor."""
    import requests
    try:
        r = requests.get(url, headers={"Range": "bytes=0-0",
                                       "User-Agent": _BROWSER_UA},
                         timeout=8, stream=True)
        r.close()
    except Exception:  # noqa: BLE001
        return False
    return r.status_code in (401, 403, 451)


def _hls_stream(info: dict) -> tuple[str, int]:
    """(url de un manifiesto HLS reproducible, altura) o ('', 0).

    Muchos sitios legítimos (y enlaces directos) sirven HLS en vez de un mp4
    progresivo. Preferimos el máster .m3u8 (deja que el reproductor/hls.js haga
    bitrate adaptativo); si no, la mejor variante suelta."""
    master = ""
    best = ("", 0)
    for f in info.get("formats", []):
        proto = f.get("protocol") or ""
        if "m3u8" not in proto:
            continue
        mu = f.get("manifest_url") or ""
        if mu and not master:
            master = mu
        if f.get("url"):
            h = f.get("height") or 0
            if h >= best[1]:
                best = (f["url"], h)
    if master:
        return master, best[1]
    return best


def _subs_url(info: dict, lang: str | None = None) -> tuple[str, bool]:
    """(url del .vtt en el idioma de estudio, es_automático) o ('', False).

    Venía fijado a "ca" desde CatalàMiner: con cualquier otro idioma «Ver
    online» nunca encontraba los subtítulos del propio vídeo y había que
    transcribir con Whisper. Se aceptan también las variantes regionales
    ("es-ES", "pt-BR", "zh-Hans"), que es como etiquetan muchos sitios."""
    from . import languages
    if lang is None:
        lang = languages.active_code()
    tags = languages.sub_tags(lang)
    for key, auto in (("subtitles", False), ("automatic_captions", True)):
        found = info.get(key) or {}
        tag = next((t for t in tags if t in found), None) or next(
            (k for k in found for t in tags if k.startswith(t + "-")), None)
        tracks = (found.get(tag) or []) if tag else []
        for t in tracks:
            if (t.get("ext") == "vtt" or "vtt" in (t.get("url") or "")) and t.get("url"):
                return t["url"], auto
        if tracks and tracks[-1].get("url"):
            return tracks[-1]["url"], auto
    return "", False


def _get_text(url: str) -> str:
    import requests
    # WebVTT siempre es UTF-8, pero RTVE lo sirve como "text/vtt" sin
    # charset y requests cae entonces a Latin-1: los acentos llegaban
    # rotos («SÃ» en vez de «Sí»).
    return requests.get(url, timeout=20, headers={"User-Agent": _BROWSER_UA}
                        ).content.decode("utf-8", errors="replace")


def subtitle_segments(url: str) -> list[dict]:
    """[{start, end, text}] de los subtítulos de un stream.

    Puede ser un .vtt/.srt o una lista HLS de trozos .vtt: la radio de RTVE
    los sirve así, y se leía la lista como si fuera el subtítulo (0 líneas,
    y a transcribir con Whisper algo que ya venía transcrito)."""
    body = _get_text(url)
    if not body.lstrip().startswith("#EXTM3U"):
        return subs.parse_subtitles(body)
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import urljoin
    parts = [urljoin(url, ln.strip()) for ln in body.splitlines()
             if ln.strip() and not ln.startswith("#")]
    # Trozos de ~5 s: una hora son ~700 peticiones, mejor en paralelo.
    # Cada trozo trae su propia cabecera WEBVTT: se parsean por separado.
    with ThreadPoolExecutor(max_workers=12) as ex:
        texts = list(ex.map(_get_text, parts))
    return subs.merge_split_cues([c for t in texts for c in subs.parse_subtitles(t)])


def _first_item(info: dict) -> dict:
    """Una página que es una lista (la de un podcast de Deutschlandfunk, con
    sus 100 episodios) abre el primero, que en esas listas es el más reciente.
    Antes caía en «yt-dlp no soporta ese sitio»."""
    if info.get("formats") or not info.get("entries"):
        return info
    first = next(iter(info["entries"]), None)
    return first if isinstance(first, dict) else info


def _extract(url: str, extractor_args: dict | None = None) -> dict:
    import yt_dlp
    # writesubtitles: algunos extractores (RTVE) solo piden la lista de
    # subtítulos a su API cuando se la piden; sin esto info["subtitles"]
    # llega vacío aunque el vídeo los tenga. Con download=False no se escribe
    # ningún archivo.
    opts = {**ytdlp.base_opts(), "quiet": True, "no_warnings": True,
            "noplaylist": True, "skip_download": True, "writesubtitles": True}
    if extractor_args:
        opts["extractor_args"] = extractor_args
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=False)


def _browser_can_load(url: str) -> bool:
    """¿Dejará el navegador que hls.js cargue este manifiesto?

    hls.js baja el .m3u8 y los segmentos con XHR, así que el servidor tiene que
    mandar Access-Control-Allow-Origin. YouTube no la manda: su HLS responde
    200 y el navegador lo bloquea igual. Abrir esa sesión era dejar a alguien
    delante de un vídeo en 0:00 sin ningún error."""
    import requests

    from . import config
    origin = f"http://localhost:{config.PORT}"
    try:
        r = requests.get(url, headers={"Origin": origin, "User-Agent": _BROWSER_UA},
                         timeout=8, stream=True)
        r.close()
    except Exception:  # noqa: BLE001
        return False
    return r.ok and r.headers.get("Access-Control-Allow-Origin", "") in ("*", origin)


def _audio_only(info: dict) -> list[dict]:
    """Formatos solo-audio (podcasts, radio, charlas). Son fuentes de primera
    para escuchar un idioma, y sin esto quedaban fuera: _progressive() exige
    altura de vídeo y descarta las pistas sueltas."""
    out = []
    for f in info.get("formats", []):
        proto = f.get("protocol") or ""
        if "dash" in proto or "m3u8" in proto or not proto.startswith("http"):
            continue
        if not f.get("url") or f.get("vcodec") not in (None, "none"):
            continue
        if f.get("acodec") == "none" or _bare_file(f):
            continue
        out.append({"height": 0, "url": f["url"],
                    "label": f.get("format_note") or "Audio",
                    "abr": f.get("abr") or 0})
    out.sort(key=lambda x: x["abr"])
    return [{k: v for k, v in f.items() if k != "abr"} for f in out[-1:]]


def _has_video(info: dict) -> bool:
    """¿La página trae vídeo, aunque no en un formato reproducible directo?

    YouTube sirve casi todo en DASH y deja un solo progresivo (el 18, 360p);
    cuando falta, _progressive() y _hls_stream() vuelven vacíos y la cadena
    caía en _audio_only(), que sí acepta la pista m4a. La sesión se abría
    entonces como podcast: sin imagen, ventana encogida y 0:00 (issue #4).
    Con esto, la rama de audio queda para lo que de verdad es sólo audio."""
    for f in info.get("formats", []):
        if f.get("vcodec") not in (None, "none") or f.get("height") or _bare_file(f):
            return True
    return False


def _resolve_with(url: str, lang: str, args: dict | None) -> dict:
    """Un intento de resolver, con unos extractor_args. Devuelve el resultado
    completo (lleva "formats"), {"blocked"}, {"needs_download"} o {}."""
    info = _first_item(_extract(url) if args is None else _extract(url, args))
    formats = _progressive(info)            # ideal: mp4 progresivo (mejor para ffmpeg)
    is_hls = is_audio = False
    has_video = _has_video(info)
    if not formats and not has_video:       # podcast/radio: el archivo de audio
        # Va antes que el HLS: la radio de RTVE sirve mp3 y HLS a la vez, y
        # con el HLS primero se abría como vídeo sin imagen, no como podcast.
        formats = _audio_only(info)
        is_audio = bool(formats)
    if not formats:                         # si no hay, caer a HLS (m3u8)
        hls_url, hls_h = _hls_stream(info)
        if hls_url and _browser_can_load(hls_url):
            formats = [{"height": hls_h, "label": "HLS", "url": hls_url}]
            is_hls = True
    if not formats and has_video:           # mp4 sin metadatos (RTVE fuera de zona)
        formats = _unlabeled_video(info)
    if not formats:
        # Hay vídeo, pero ninguno que un <video> pueda reproducir. Mejor
        # decirlo y mandar a la descarga —que además ya trae los subtítulos—
        # que abrir una sesión muda.
        if has_video:
            return {"needs_download": True, "title": info.get("title") or url}
        return {}
    if not is_hls and _forbidden(formats[-1]["url"]):
        # El HLS ya se probó en _browser_can_load; esto cubre mp4 y audio.
        return {"blocked": True, "title": info.get("title") or url}
    subs_url, subs_auto = _subs_url(info, lang)
    return {"title": info.get("title") or url,
            "duration": float(info.get("duration") or 0),
            "formats": formats,
            "best_url": formats[-1]["url"],
            "best_height": formats[-1]["height"],
            "is_hls": is_hls, "is_audio": is_audio,
            "subs_url": subs_url, "subs_auto": subs_auto}


def resolve(url: str) -> dict:
    """{title, duration, formats:[{height,label,url}], best_url, subs_url,
    subs_auto} — o {} si no se pudo resolver. Cacheado con TTL.

    La clave lleva el idioma de estudio: los subtítulos elegidos dependen de
    él, y con solo la URL un cambio de idioma reusaba los del anterior.

    En YouTube se prueban varios clientes (ytdlp.youtube_attempts): el mismo
    vídeo da 403, «No video formats found» o un mp4 que funciona según el
    cliente y el sitio desde donde se pida. La idea de la reserva es de
    @ihonomic (PR #16)."""
    from . import languages
    lang = languages.active_code()
    key = f"{lang}|{url}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    fail: dict = {}
    err = None
    for args in ytdlp.youtube_attempts(url):
        try:
            r = _resolve_with(url, lang, args)
        except Exception as e:  # noqa: BLE001
            err = err or e
            r = {"blocked": True, "title": url} if ytdlp.is_blocked(e) else {}
        if r.get("formats"):
            ytdlp.youtube_worked(args)
            _CACHE[key] = (time.time(), r)      # solo éxitos; los fallos reintentan
            return r
        fail = fail or r                        # el primer fallo que diga algo
    if not fail and err is not None:
        failures.warn_once("stream-resolve",
                           "yt-dlp no pudo resolver un enlace; «Ver online» "
                           "fallará hasta que se actualice o cambie el sitio", err)
    return fail


def stream_url(url: str, height: int = 0) -> tuple[str, list[dict], bool]:
    """URL fresca para la altura pedida (o la mejor) + alturas + si es HLS."""
    r = resolve(url)
    if not r or r.get("needs_download") or r.get("blocked"):
        return "", [], False
    fmts = r["formats"]
    chosen = r["best_url"]
    if height:
        exact = [f for f in fmts if f["height"] == height]
        if exact:
            chosen = exact[0]["url"]
    heights = [{"height": f["height"], "label": f["label"]} for f in fmts]
    return chosen, heights, bool(r.get("is_hls"))
