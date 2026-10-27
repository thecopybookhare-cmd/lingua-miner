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
