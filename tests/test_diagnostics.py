"""Informe de diagnóstico.

La app se anuncia sin telemetría, y eso es una promesa hecha en el README, en
Reddit y a los moderadores de r/languagelearning. El informe REDACTA el texto y
abre GitHub; enviarlo lo decide el usuario. Estos tests vigilan justo eso.
"""
from fastapi.testclient import TestClient

import app.main as main
from app import diagnostics


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def test_report_carries_what_is_needed_to_debug():
    r = diagnostics.report("la ventana sale en blanco")
    assert "la ventana sale en blanco" in r
    assert "LinguaMiner" in r                  # versión
    assert "Python" in r
    for pkg in ("pywebview", "faster-whisper", "ctranslate2"):
        assert pkg in r, f"falta la versión de {pkg}"


def test_report_redacts_the_home_directory():
    """Las rutas llevan el nombre de usuario y esto acaba en un issue público."""
    from pathlib import Path
    r = diagnostics.report()
    home = str(Path.home())
    assert home not in r, "el informe filtra la ruta del home"


def test_log_tail_drops_the_successful_access_noise():
    """95.000 líneas de `GET /media/thumb-… 200` no diagnostican nada."""
    ruido = '2026-01-01 INFO uvicorn.access: 127.0.0.1:1 - "GET /media/thumb-a.jpg HTTP/1.1" 200'
    error = "2026-01-01 ERROR desktop: el servidor no pudo arrancar"
    assert diagnostics._interesting(ruido) is False
    assert diagnostics._interesting(error) is True
    assert diagnostics._interesting(
        '2026-01-01 INFO uvicorn.access: - "GET /api/x HTTP/1.1" 500') is True


def test_issue_url_is_prefilled_and_bounded():
    u = diagnostics.issue_url("algo falló")
    assert u.startswith(diagnostics.REPO + "/issues/new?")
    assert "title=" in u and "body=" in u
    # GitHub corta las URLs largas; el cuerpo va acotado a propósito
    assert len(u) < 9000, "la URL se pasa de lo que GitHub acepta"


def test_endpoint_returns_the_report_without_sending_anything(tmp_path):
    c = client(tmp_path)
    r = c.get("/api/diagnostics", params={"extra": "prueba"})
    assert r.status_code == 200
    d = r.json()
    assert "prueba" in d["report"]
    assert d["issue_url"].startswith("https://github.com/")


def test_endpoint_is_refused_to_network_guests(tmp_path, monkeypatch):
    """Con el modo compartir activo, un invitado no debe poder leer la versión
    del sistema ni el log del anfitrión."""
    c = client(tmp_path)
    monkeypatch.setattr(main, "_is_local_client", lambda request: False)
    assert c.get("/api/diagnostics").status_code == 403


def test_nothing_in_the_code_posts_the_report_anywhere():
    """La red solo se toca para ABRIR GitHub en el navegador del usuario."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "app" / "diagnostics.py").read_text(
        encoding="utf-8")
    for prohibido in ("requests.post", "urlopen", "http.client", "socket."):
        assert prohibido not in src, f"diagnostics.py no debería usar {prohibido}"
