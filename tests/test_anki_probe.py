"""AnkiConnect cerrado tiene que descartarse rápido, también en Windows."""
import socket

from app import anki


def test_closed_port_is_down_without_an_http_request(monkeypatch):
    def refused(*a, **k):
        raise ConnectionRefusedError
    monkeypatch.setattr(anki.socket, "create_connection", refused)
    monkeypatch.setattr(anki.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debía llamar")))
    assert anki.probe(8765) == "down"


def test_tcp_check_is_short(monkeypatch):
    seen = {}

    def fake(addr, timeout):
        seen["timeout"] = timeout
        raise TimeoutError
    monkeypatch.setattr(anki.socket, "create_connection", fake)
    anki.probe(8765)
    assert seen["timeout"] <= 0.5


def test_real_closed_port_is_fast():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    import time
    t = time.time()
    assert anki.probe(port) == "down"
    assert time.time() - t < 1


def test_configured_port_beats_a_cached_one(monkeypatch):
    """Con anki_port puesto, un AnkiConnect descubierto antes en otro puerto
    no puede llevarse las tarjetas."""
    monkeypatch.setattr(anki, "_PORT", 8767)
    monkeypatch.setattr(anki, "probe", lambda p: "ok" if p == 8767 else "down")
    assert anki.find_port(65000)[0] is None
    assert anki.find_port(None)[0] == 8767


def test_health_respects_the_configured_port(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    seen = []
    monkeypatch.setattr(main.anki, "is_up", lambda p=None: seen.append(p) or False)
    monkeypatch.setattr(main, "_settings", lambda: {**main.DEFAULT_SETTINGS, "anki_port": 9999})
    TestClient(main.app).get("/api/health")
    assert seen == [9999]
