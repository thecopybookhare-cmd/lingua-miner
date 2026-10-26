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


# yt-dlp 2026.10.21 empezó a sacar los formatos de YouTube del cliente
# TVHTML5, cuyas URLs responden 403 tanto al navegador como al propio yt-dlp:
# «Ver online» dejó de reproducir y la descarga del formato 18 también (lo
# detectó el canario, issue #9). Con el cliente WEB el mismo vídeo responde
# 206. Tiene que ir solo: junto a los clientes por defecto, yt-dlp se queda
# con el formato de TVHTML5 igualmente.
YOUTUBE_ARGS = {"youtube": {"player_client": ["web"]}}


def base_opts() -> dict:
    opts = {"extractor_args": YOUTUBE_ARGS}
    path = deno_path()
    if path:
        opts["js_runtimes"] = {"deno": {"path": path}}
        return opts
    failures.warn_once(
        "ytdlp-no-js",
        "no hay Deno: YouTube pierde formatos y «Ver online» puede quedarse "
        "en 0:00. Vuelve a ejecutar el instalador para traerlo.")
    return opts
