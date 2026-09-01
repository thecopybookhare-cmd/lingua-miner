"""Resolución de streams reproducibles (YouTube, 3cat…) sin descargar.

yt-dlp extrae las URLs de los formatos progresivos (video+audio en un solo
archivo, proto http) que un <video> puede reproducir directo y ffmpeg puede
leer para las tarjetas. Las URLs caducan y van atadas a la IP, así que se
re-resuelven al abrir la sesión y al minar."""
import re
import time

from . import failures

_DIRECT = re.compile(r"\.(mp4|m3u8|webm|mov|m4v)(\?|$)", re.I)

# Abrir una sesión de streaming dispara varias llamadas a yt-dlp seguidas
# (resolver + cambiar calidad + minar), cada una ~1-3 s. Las URLs de yt-dlp
# caducan en horas, así que cachear el resultado unos minutos es seguro y
# recorta la latencia de esas ráfagas.
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL = 240.0


def _cache_get(url: str) -> dict | None:
    now = time.time()
    for k in [k for k, (t, _) in _CACHE.items() if now - t >= _TTL]:
        del _CACHE[k]                     # poda: que no crezca sin límite
    hit = _CACHE.get(url)
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


def _subs_url(info: dict) -> tuple[str, bool]:
    """(url del .vtt en catalán, es_automático) o ('', False)."""
    for key, auto in (("subtitles", False), ("automatic_captions", True)):
        tracks = (info.get(key) or {}).get("ca") or []
        for t in tracks:
            if (t.get("ext") == "vtt" or "vtt" in (t.get("url") or "")) and t.get("url"):
                return t["url"], auto
        if tracks and tracks[-1].get("url"):
            return tracks[-1]["url"], auto
    return "", False


def _extract(url: str) -> dict:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as y:
        return y.extract_info(url, download=False)


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
        if f.get("acodec") == "none":
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
        if f.get("vcodec") not in (None, "none") or f.get("height"):
            return True
    return False


def resolve(url: str) -> dict:
    """{title, duration, formats:[{height,label,url}], best_url, subs_url,
    subs_auto} — o {} si no se pudo resolver. Cacheado con TTL."""
    cached = _cache_get(url)
    if cached is not None:
        return cached
    try:
        info = _extract(url)
    except Exception as e:
        failures.warn_once("stream-resolve",
                           "yt-dlp no pudo resolver un enlace; «Ver online» "
                           "fallará hasta que se actualice o cambie el sitio", e)
        return {}
    formats = _progressive(info)            # ideal: mp4 progresivo (mejor para ffmpeg)
    is_hls = is_audio = False
    if not formats:                         # si no hay, caer a HLS (m3u8)
        hls_url, hls_h = _hls_stream(info)
        if hls_url:
            formats = [{"height": hls_h, "label": "HLS", "url": hls_url}]
            is_hls = True
    if not formats and not _has_video(info):   # ni vídeo ni HLS: ¿podcast/radio?
        formats = _audio_only(info)
        is_audio = bool(formats)
    if not formats:
        # Hay vídeo, pero ninguno que un <video> pueda reproducir. Mejor
        # decirlo y mandar a la descarga —que además ya trae los subtítulos—
        # que abrir una sesión muda.
        if _has_video(info):
            return {"needs_download": True, "title": info.get("title") or url}
        return {}
    subs_url, subs_auto = _subs_url(info)
    r = {"title": info.get("title") or url,
         "duration": float(info.get("duration") or 0),
         "formats": formats,
         "best_url": formats[-1]["url"],
         "best_height": formats[-1]["height"],
         "is_hls": is_hls, "is_audio": is_audio,
         "subs_url": subs_url, "subs_auto": subs_auto}
    _CACHE[url] = (time.time(), r)          # solo éxitos; los fallos reintentan
    return r


def stream_url(url: str, height: int = 0) -> tuple[str, list[dict], bool]:
    """URL fresca para la altura pedida (o la mejor) + alturas + si es HLS."""
    r = resolve(url)
    if not r or r.get("needs_download"):
        return "", [], False
    fmts = r["formats"]
    chosen = r["best_url"]
    if height:
        exact = [f for f in fmts if f["height"] == height]
        if exact:
            chosen = exact[0]["url"]
    heights = [{"height": f["height"], "label": f["label"]} for f in fmts]
    return chosen, heights, bool(r.get("is_hls"))
