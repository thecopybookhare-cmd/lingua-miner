"""Canario semanal: ¿«Ver online» sigue funcionando con YouTube?

YouTube cambia y rompe yt-dlp cada pocos meses, y la app falla en silencio:
el último fallo así (v1.34.1) dejó «Ver online» en 0:00 para todo el mundo
durante semanas, y solo lo reportó una persona. Esto lo prueba cada lunes
desde una instalación limpia, con lo que se baja hoy un usuario nuevo.

Salida: 0 funciona · 1 roto (el workflow abre un issue) · 2 no concluyente
(YouTube pidió verificar que no somos un bot: pasa con las IPs de GitHub y
no dice nada de la app). El informe sale en inglés: es el cuerpo del issue.
"""
import sys
import urllib.request

sys.path.insert(0, ".")
import yt_dlp  # noqa: E402

from app import stream, ytdlp  # noqa: E402

VIDEOS = ["https://www.youtube.com/watch?v=dQw4w9WgXcQ",
          "https://www.youtube.com/watch?v=9bZkp7q19f0",
          "https://www.youtube.com/watch?v=kJQP7kiw5Fk"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0"


def check(url: str) -> tuple[str, str]:
    stream._CACHE.clear()
    try:
        stream._extract(url)                 # resolve() se traga el error; aquí se ve
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "not a bot" in msg or "Sign in to confirm" in msg:
            return "blocked", "YouTube asked to confirm we're not a bot (GitHub IP)"
        return "broken", f"yt-dlp could not extract it: `{msg[:300]}`"
    r = stream.resolve(url)
    if not r:
        return "broken", "`resolve()` returned nothing"
    if r.get("needs_download"):
        return "broken", ("no directly playable format (format 18 missing) — "
                          "*Watch online* would send people to download instead")
    if r.get("is_hls"):
        return "broken", "fell back to YouTube's HLS, which the browser can't load (no CORS)"
    if not r.get("duration"):
        return "broken", "duration came back as 0 — the player would sit at 0:00"
    req = urllib.request.Request(r["best_url"], headers={"Range": "bytes=0-1023",
                                                         "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            code = resp.status
    except Exception as e:  # noqa: BLE001
        code = getattr(e, "code", None) or str(e)[:120]
    if code not in (200, 206):
        return "broken", f"the URL the player would get answered `{code}`"
    return "ok", f"{r.get('best_height')}p, {int(r['duration'])} s, URL answers {code}"


def main() -> int:
    deno = ytdlp.deno_path()
    lines = ["## YouTube canary", "",
             f"- yt-dlp `{yt_dlp.version.__version__}`",
             f"- Deno: `{deno or 'MISSING'}`", ""]
    results = []
    for url in VIDEOS:
        status, detail = check(url)
        results.append(status)
        mark = {"ok": "✅", "broken": "❌", "blocked": "⚠️"}[status]
        lines.append(f"- {mark} {url} — {detail}")
    if not deno:
        lines.append("- ❌ Deno is missing: yt-dlp can't solve YouTube's challenge")
    print("\n".join(lines))
    # Un vídeo que funciona basta: otro puede fallar por motivos suyos
    # (retirado, restringido). Sin Deno está roto aunque alguno pase hoy.
    if deno and "ok" in results:
        return 0
    if not deno or "broken" in results:
        print("\n**Watch online with YouTube is broken for new installs.** "
              "Likely fix: bump `yt-dlp` / `yt-dlp-ejs` / `deno` in `pyproject.toml`.")
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
