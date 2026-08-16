"""Arranque de la app de escritorio.

Un usuario en un Mac con chip M reportó que la app abría "una ventana blanca,
sin nada dentro". El arranque comprobaba solo que el puerto TCP aceptara y
después abría la ventana **pasara lo que pasara**: si el servidor moría al
arrancar, se abría una ventana en blanco, y la excepción del hilo ni siquiera
llegaba al log.
"""
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import config, desktop


@pytest.fixture(autouse=True)
def _clean_error():
    desktop.SERVER_ERROR.clear()
    yield
    desktop.SERVER_ERROR.clear()


def _serve_once(status: int) -> int:
    """Servidor mínimo en un puerto libre que responde `status` en /."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


def test_ready_when_the_app_actually_answers():
    port = _serve_once(200)
    assert desktop._wait_ready(port, secs=5.0) is True


def test_not_ready_when_something_else_squats_the_port():
    """Que el puerto acepte no basta: otro programa puede tenerlo cogido.
    Antes se comprobaba solo el TCP y esto daba OK."""
    port = _serve_once(404)
    assert desktop._wait_ready(port, secs=2.0) is False


def test_gives_up_immediately_when_the_server_thread_died():
    """Sin esto se esperaban los 90 s completos con el fallo ya conocido."""
    desktop.SERVER_ERROR.append(RuntimeError("boom"))
    t0 = time.time()
    assert desktop._wait_ready(config.PORT, secs=30.0) is False
    assert time.time() - t0 < 2.0, "no debería esperar si el hilo ya murió"


def test_server_thread_records_its_exception(monkeypatch):
    """uvicorn sale con SystemExit cuando no puede enlazar el puerto, y
    SystemExit no es Exception: sin capturarlo, el fallo era invisible."""
    def boom():
        raise SystemExit(1)
    monkeypatch.setattr(desktop, "config", config)
    import app.main  # noqa: F401  (que el import no sea lo que falle)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn",
                        type("M", (), {"run": staticmethod(lambda *a, **k: boom())})())
    with pytest.raises(SystemExit):
        desktop._serve()
    assert desktop.SERVER_ERROR, "la excepción del servidor debe quedar registrada"
    assert isinstance(desktop.SERVER_ERROR[0], SystemExit)


def test_error_page_says_what_happened_and_where_to_look():
    h = desktop._error_html(port_busy=False)
    assert str(desktop.LOG_PATH) in h
    assert "didn't start" in h
    busy = desktop._error_html(port_busy=True)
    assert f"already using port {config.PORT}" in busy
    assert "<script" not in h.lower(), "la página de error no ejecuta nada"


def test_error_page_escapes_the_log_contents(monkeypatch):
    """El log lleva rutas y trazas; si trae <> rompería la página."""
    monkeypatch.setattr(desktop, "_tail_log", lambda n=25: "<img src=x onerror=1>")
    h = desktop._error_html(port_busy=False)
    assert "&lt;img" in h and "<img" not in h
