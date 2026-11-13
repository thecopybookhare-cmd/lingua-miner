"""Opciones que toda llamada a yt-dlp tiene que llevar.

Desde finales de 2025, yt-dlp necesita un motor de JavaScript para resolver
el desafío de YouTube. Sin él avisa —y la app lo callaba con no_warnings— y
sigue, pero sin el único formato que un <video> reproduce directo (el 18,
mp4 progresivo). «Ver online» caía entonces al HLS de YouTube, que no manda
cabeceras CORS, y el navegador se quedaba en 0:00 sin dar ningún error.

yt-dlp[default] trae yt-dlp-ejs (los scripts que resuelven el desafío) y el
paquete oficial deno de PyPI trae el binario. Hay que pasarle la ruta: la app
arranca el python del venv sin activarlo, así que deno no está en el PATH.
"""
import re
import shutil

from . import failures


def deno_path() -> str | None:
    try:
        import deno
        found = deno.find_deno_bin()
        if found:
            return str(found)
    except Exception:  # noqa: BLE001 — instalación anterior sin el paquete
        pass
    return shutil.which("deno")


# Ningún cliente de YouTube sirve en todas partes. Medido el 13-nov-2026 con
# yt-dlp 2026.10.26 y el mismo vídeo:
#
#                    por defecto   tv_simply   web
#   GitHub (EE. UU.)     403          206      206
#   Múnich (PR #16)      206          206      «No video formats found»
#
# Fijar «web» (issue #9) arregló a unos y rompió a otros, y fijar cualquier
# otro haría lo mismo en cuanto YouTube cambie. Así que no se fija ninguno:
# se prueban en orden y se recuerda el que funcionó en esta máquina.
YOUTUBE_CLIENTS: tuple = (None, ("tv_simply",), ("web",))   # None = los de yt-dlp
_YOUTUBE = re.compile(r"(^|[/.])(youtube\.com|youtu\.be)/", re.I)
_yt_good = 0            # índice del último cliente que funcionó


def is_youtube(url: str) -> bool:
    return bool(_YOUTUBE.search(url or ""))


def _yt_args(i: int) -> dict | None:
    c = YOUTUBE_CLIENTS[i]
    return {"youtube": {"player_client": list(c)}} if c else None


def youtube_attempts(url: str) -> list[dict | None]:
    """Los extractor_args a probar, en orden: primero el que funcionó la
    última vez. Fuera de YouTube hay un solo intento, sin argumentos."""
    if not is_youtube(url):
        return [None]
    order = [_yt_good] + [i for i in range(len(YOUTUBE_CLIENTS)) if i != _yt_good]
    return [_yt_args(i) for i in order]


def youtube_worked(args: dict | None) -> None:
    """Recuerda el cliente que acaba de funcionar: el siguiente vídeo empieza
    por él y no repite los intentos fallidos."""
    global _yt_good
    for i in range(len(YOUTUBE_CLIENTS)):
        if _yt_args(i) == args:
            _yt_good = i


def base_opts() -> dict:
    opts: dict = {}
    path = deno_path()
    if path:
        opts["js_runtimes"] = {"deno": {"path": path}}
        return opts
    failures.warn_once(
        "ytdlp-no-js",
        "no hay Deno: YouTube pierde formatos y «Ver online» puede quedarse "
        "en 0:00. Vuelve a ejecutar el instalador para traerlo.")
    return opts


# Texto de reserva (castellano) del error err.geo_blocked; el navegador lo
# traduce por la clave.
BLOCKED_MSG = ("El sitio no deja reproducir este vídeo desde tu conexión "
               "(error 403). Suele pasar con programas que solo se pueden ver "
               "en algunos países: prueba con otro. Si te pasa con todos, "
               "actualiza LinguaMiner (⚙️ → Buscar actualizaciones).")

_BLOCKED = ("http error 403", "http error 451", "geo restriction",
            "geo-restrict", "available in your country",
            "available from your location")


def is_blocked(exc: BaseException) -> bool:
    """¿Falló porque el sitio no deja ver el vídeo desde esta conexión?

    Bloqueo por país (GeoRestrictedError, que extract_info envuelve en un
    DownloadError) o un 403/451 al pedir el archivo: RTVE fuera de su zona da
    las URLs de los mp4 y luego responde 403 al pedirlos."""
    inner = (getattr(exc, "exc_info", None) or (None, None))[1]
    if any(type(e).__name__ == "GeoRestrictedError" for e in (exc, inner) if e):
        return True
    msg = str(exc).lower()
    return any(s in msg for s in _BLOCKED)
