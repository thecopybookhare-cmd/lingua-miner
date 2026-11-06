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


# Sin player_client fijo: yt-dlp elige los clientes de YouTube. Forzar «web»
# (el arreglo del issue #9, cuando TVHTML5 daba 403) dejó de servir en
# noviembre de 2026: con yt-dlp 2026.10.26 ese cliente devuelve «No video
# formats found» para todos los vídeos, y los clientes por defecto vuelven a
# dar el formato 18 con URLs que responden 206.
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
