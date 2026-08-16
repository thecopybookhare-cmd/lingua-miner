"""Los fallos que degradan en silencio deben dejar rastro.

Tres veces en una semana un `except Exception: return ""` costó horas: spaCy
saliendo por SystemExit, wordfreq devolviendo 0 sin jieba, y el hilo del
servidor muriendo sin log. La degradación se queda — es correcta — pero ahora
avisa una vez.
"""
import logging

import pytest

from app import failures


@pytest.fixture(autouse=True)
def _reset():
    failures.reset()
    yield
    failures.reset()


def test_warns_once_per_cause_not_once_per_call(caplog):
    """Traducir 500 subtítulos con el motor roto debe dejar UNA línea."""
    with caplog.at_level(logging.WARNING):
        for _ in range(500):
            failures.warn_once("traductor", "el traductor no cargó")
    assert len(caplog.records) == 1


def test_different_causes_each_get_their_line(caplog):
    with caplog.at_level(logging.WARNING):
        failures.warn_once("a", "una cosa")
        failures.warn_once("b", "otra cosa")
    assert len(caplog.records) == 2


def test_the_exception_type_and_message_survive(caplog):
    """Sin el tipo y el mensaje el aviso no diagnostica nada."""
    with caplog.at_level(logging.WARNING):
        failures.warn_once("x", "no pude cargar el traductor",
                           FileNotFoundError("falta model.bin"))
    txt = caplog.text
    assert "FileNotFoundError" in txt and "falta model.bin" in txt


def test_translation_failure_leaves_a_trace(caplog, monkeypatch):
    """Era el peor de todos: sin traductor, TODAS las tarjetas salen con los
    campos vacíos y el usuario no tiene ni una pista."""
    from app import translate
    monkeypatch.setattr(translate, "_ENGINES", {})
    monkeypatch.setattr(translate, "_FAILED_AT", {})
    monkeypatch.setattr(translate, "is_downloaded", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("model.bin corrupto")
    monkeypatch.setattr(translate, "_Engine", boom)

    with caplog.at_level(logging.WARNING):
        out = translate.translate("hola")
    assert out == "", "debe seguir degradando, no reventar"
    assert "traductor" in caplog.text.lower()
    assert "model.bin corrupto" in caplog.text


def test_the_warning_reaches_the_diagnostics_report():
    """De nada sirve avisar si el informe que manda el usuario no lo lleva."""
    from app import diagnostics
    linea = "2026-01-01 WARNING degradado: no pude cargar el traductor ca→es"
    assert diagnostics._interesting(linea) is True


# ---------- lo degradado tiene que llegar al usuario ----------

def test_user_message_stays_clean_and_detail_goes_to_the_report():
    """Volcar la excepción cruda en la interfaz da avisos de seis líneas:
    yt-dlp mete el traceback entero dentro del mensaje."""
    failures.warn_once("s", "«Ver online» no funciona",
                       RuntimeError("ERROR: [generic] blah " + "x" * 400))
    visible = failures.active()
    assert visible == ["«Ver online» no funciona"]
    assert len(visible[0]) < 60, "el aviso de la interfaz debe caber en una línea"
    detalle = failures.details()[0]
    assert "RuntimeError" in detalle and "x" * 50 in detalle


def test_health_tells_the_frontend_what_is_degraded(tmp_path):
    from fastapi.testclient import TestClient

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    assert c.get("/api/health").json()["degraded"] == []
    failures.warn_once("x", "el traductor no carga")
    assert c.get("/api/health").json()["degraded"] == ["el traductor no carga"]


def test_the_report_includes_the_degraded_section():
    from app import diagnostics
    failures.warn_once("y", "sin glosas", ValueError("db corrupta"))
    r = diagnostics.report()
    assert "### Degraded right now" in r
    assert "sin glosas" in r and "db corrupta" in r
