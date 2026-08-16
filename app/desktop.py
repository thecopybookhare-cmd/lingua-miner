"""LinguaMiner como app de escritorio: uvicorn en un hilo + ventana webview.
Multiplataforma: WKWebView en macOS, WebView2 en Windows, GTK/QT en Linux;
si no hay motor webview disponible, cae al navegador por defecto."""
import html as _html
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

from . import config

LOG_PATH = config.APP_DIR / "desktop.log"

# macOS: lanzada por LaunchServices (doble clic), la app NO hereda el PATH de
# la terminal: ffmpeg/ffprobe/espeak-ng de Homebrew quedan invisibles y todo
# subprocess.run(["ffprobe", ...]) revienta con FileNotFoundError.
if sys.platform == "darwin":
    for _hb in ("/opt/homebrew/bin", "/usr/local/bin"):
        if _hb not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = _hb + os.pathsep + os.environ.get("PATH", "")


def _setup_logging():
    """La app empaquetada no tiene terminal — stdout/stderr van a /dev/null.
    Sin esto, cualquier excepción del servidor es indiagnosticable."""
    handler = logging.FileHandler(str(LOG_PATH))
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # Una excepción en un hilo va al excepthook, no al logger raíz: sin esto,
    # si el servidor moría al arrancar no quedaba ni rastro en el log y la
    # ventana salía en blanco sin explicación.
    def _hook(args):
        logging.getLogger("desktop").error(
            "hilo %s murió", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _hook


SERVER_ERROR: list = []      # excepción del hilo del servidor, si la hubo


def _serve():
    try:
        import uvicorn

        from .main import app
        uvicorn.run(app, host="127.0.0.1", port=config.PORT, log_level="info",
                    log_config=None)
    except BaseException as e:                       # noqa: BLE001
        # SystemExit incluido: uvicorn sale así cuando no puede enlazar el puerto
        SERVER_ERROR.append(e)
        logging.getLogger("desktop").exception("el servidor no pudo arrancar")
        raise


def _port_taken(port: int) -> bool:
    """¿Hay algo escuchando ya, antes de que arranquemos nosotros?"""
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _wait_ready(port: int, secs: float = 90.0) -> bool:
    """Espera a que la app RESPONDA, no solo a que el puerto acepte.

    Antes se comprobaba solo el TCP: si otro proceso ocupaba el 8977, o si
    uvicorn enlazaba pero la app moría después, la comprobación daba OK. Y con
    un primer arranque en frío (imports de faster-whisper, ctranslate2 y spaCy
    desde disco) 20 s se quedaban cortos en equipos lentos.
    """
    url = f"http://127.0.0.1:{port}/"
    t0 = time.time()
    while time.time() - t0 < secs:
        if SERVER_ERROR:
            return False                  # el hilo ya murió: no esperes más
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.3)
    return False


def _tail_log(n: int = 25) -> str:
    try:
        return "".join(LOG_PATH.read_text(
            encoding="utf-8", errors="replace").splitlines(keepends=True)[-n:])
    except Exception:
        return "(sin log)"


def _error_html(port_busy: bool) -> str:
    """Página de diagnóstico. Abrir una ventana en blanco cuando el servidor no
    levanta deja al usuario sin ninguna pista de qué ha pasado; esto al menos
    dice dónde mirar."""
    if port_busy:
        causa = (f"Another program is already using port {config.PORT}. "
                 "LinguaMiner needs it free.")
        arreglo = (f"Quit whatever is using port {config.PORT} and open "
                   "LinguaMiner again.")
    else:
        causa = "The LinguaMiner server didn't start."
        arreglo = "This is usually a missing dependency from the install step."
    return f"""<!doctype html><meta charset="utf-8">
<style>
 body {{ background:#0c0d13; color:#e9e9f2; margin:0; padding:44px 40px;
        font:16px/1.6 -apple-system,"Segoe UI",sans-serif; }}
 h1 {{ font-size:24px; margin:0 0 6px; }}
 p  {{ color:#8f93a8; max-width:60ch; }}
 code {{ background:#151827; padding:2px 7px; border-radius:6px; font-size:14px; }}
 pre {{ background:#151827; border:1px solid #262b42; border-radius:12px;
        padding:14px; font-size:12.5px; overflow:auto; max-height:44vh;
        white-space:pre-wrap; color:#b9bccb; }}
 .b {{ color:#e5a04c; }}
</style>
<h1>LinguaMiner couldn't start</h1>
<p class="b">{causa}</p>
<p>{arreglo} The full log is at:</p>
<p><code>{_html.escape(str(LOG_PATH))}</code></p>
<p>If you open an issue, pasting the lines below is the single most useful
thing you can include.</p>
<pre>{_html.escape(_tail_log())}</pre>
"""


def _reload_when_ready(window, url: str):
    """Si el servidor tarda más de la cuenta, carga la app en cuanto responda
    en vez de dejar la página de error para siempre."""
    if _wait_ready(config.PORT, secs=180.0):
        try:
            window.load_url(url)
        except Exception:
            logging.getLogger("desktop").exception("no pude recargar la ventana")


def main():
    _setup_logging()
    log = logging.getLogger("desktop")
    log.info("arrancando LinguaMiner desktop, log en %s", LOG_PATH)
    url = f"http://127.0.0.1:{config.PORT}"
    busy = _port_taken(config.PORT)
    if busy:
        log.warning("el puerto %s ya estaba ocupado antes de arrancar",
                    config.PORT)
    try:
        import webview
    except Exception:
        webview = None

    serving = False
    if webview is not None:
        try:
            threading.Thread(target=_serve, name="uvicorn", daemon=True).start()
            serving = _wait_ready(config.PORT)
            if serving:
                webview.create_window("LinguaMiner", url,
                                      width=1280, height=860, min_size=(980, 640))
            else:
                # NO abrir una ventana en blanco: decir qué pasó y dónde mirar
                log.error("la app no respondió en %s; abro la pantalla de error", url)
                w = webview.create_window("LinguaMiner", html=_error_html(busy),
                                          width=1080, height=760, min_size=(720, 520))
                threading.Thread(target=_reload_when_ready, args=(w, url),
                                 daemon=True).start()
            webview.start()
            log.info("cerrado normalmente")
            return
        except Exception:
            # sin motor webview utilizable (Linux sin GTK/QT, Windows sin
            # WebView2…): seguimos sirviendo y abrimos el navegador
            log.exception("webview no disponible; caigo al navegador")
    import webbrowser
    log.info("modo navegador: %s", url)
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    try:
        if serving:
            threading.Event().wait()      # el server ya corre en su hilo
        else:
            _serve()                      # bloquea (Ctrl+C para salir)
    except KeyboardInterrupt:
        pass
    log.info("cerrado normalmente")


if __name__ == "__main__":
    main()
