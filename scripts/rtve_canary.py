"""Canario semanal de RTVE Play: ¿«Ver online» sigue funcionando en español?

Coge lo que haya hoy en la portada de RTVE Play y de su radio (los enlaces
caducan, así que no se fijan) y comprueba lo mismo que necesita la app:
formato reproducible, subtítulos en español y que la URL del vídeo responda.

Corre en las máquinas de GitHub, en EE. UU.: si RTVE limita algo a España,
aquí se ve como «blocked». Solo informa, no abre issues: RTVE es una fuente
más, no lo que sostiene la app.

Salida: 0 funciona · 1 roto · 2 no concluyente (todo bloqueado por país).
"""
import re
import sys
import urllib.request

sys.path.insert(0, ".")
import yt_dlp  # noqa: E402

from app import stream  # noqa: E402

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"


def _links(page: str, kind: str, n: int) -> list[str]:
    req = urllib.request.Request(page, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    pat = rf"https://www\.rtve\.es/play/{kind}/[a-z0-9-]+/[a-z0-9-]+/\d{{6,}}/"
    return list(dict.fromkeys(re.findall(pat, html)))[:n]


def check(url: str) -> tuple[str, str]:
    stream._CACHE.clear()
    try:
        info = stream._extract(url)          # resolve() se traga el error; aquí se ve
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if isinstance(e, yt_dlp.utils.GeoRestrictedError) or "location" in msg.lower():
            return "blocked", f"geo-restricted from this runner: `{msg[:200]}`"
        return "broken", f"yt-dlp could not extract it: `{msg[:300]}`"
    subs, _ = stream._subs_url(info, "es")
    r = stream.resolve(url)
    if not r or r.get("needs_download"):
        return "broken", "no format the player can load"
    req = urllib.request.Request(r["best_url"], headers={"Range": "bytes=0-1023",
                                                         "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.status
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None) or str(e)[:120]
    if code == 403:
        return "blocked", "the media URL answered 403 (geo-restricted CDN?)"
    if code not in (200, 206):
        return "broken", f"the URL the player would get answered `{code}`"
    kind = "audio" if r.get("is_audio") else ("HLS" if r.get("is_hls") else "MP4")
    return "ok", (f"{kind}, {int(r.get('duration') or 0)} s, URL answers {code}, "
                  f"Spanish subtitles: {'yes' if subs else 'no'}")


def main() -> int:
    lines = ["## RTVE Play canary (Spanish)", "",
             f"- yt-dlp `{yt_dlp.version.__version__}`", ""]
    try:
        urls = (_links("https://www.rtve.es/play/", "videos", 3)
                + _links("https://www.rtve.es/play/radio/", "audios", 1))
    except Exception as e:  # noqa: BLE001
        print("\n".join(lines + [f"- ❌ could not read RTVE Play's front page: `{e}`"]))
        return 1
    if not urls:
        print("\n".join(lines + ["- ❌ no video links on RTVE Play's front page "
                                 "(the page layout changed?)"]))
        return 1
    results = []
    for url in urls:
        status, detail = check(url)
        results.append(status)
        mark = {"ok": "✅", "broken": "❌", "blocked": "⚠️"}[status]
        lines.append(f"- {mark} {url} — {detail}")
    print("\n".join(lines))
    if "ok" in results:
        return 0
    return 1 if "broken" in results else 2


if __name__ == "__main__":
    sys.exit(main())
