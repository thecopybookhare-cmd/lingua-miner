"""Docker: Anki en el anfitrión y la puerta de invitados detrás de un NAT."""
from fastapi.testclient import TestClient

import app.main as main
from app import anki, config

# desde dentro de un contenedor, el navegador del anfitrión llega por aquí
DOCKER_GATEWAY = ("172.17.0.1", 51234)


def test_anki_url_uses_configured_host(monkeypatch):
    monkeypatch.setattr(config, "ANKI_HOST", "host.docker.internal")
    assert anki._url(8765) == "http://host.docker.internal:8765"


def test_anki_url_defaults_to_loopback():
    assert config.ANKI_HOST == "127.0.0.1"
    assert anki._url(8765) == "http://127.0.0.1:8765"


def test_gateway_client_is_a_guest_by_default(tmp_path):
    # fuera de Docker no cambia nada: una IP que no es loopback es un invitado
    main.CON = main.db.connect(tmp_path / "t.db")
    assert config.TRUST_ALL_CLIENTS is False
    c = TestClient(main.app, client=DOCKER_GATEWAY)
    assert c.post("/api/settings", json={}).status_code == 403


def test_gateway_client_can_administer_in_container(tmp_path, monkeypatch):
    # la regresión que esto evita: en Docker la app arrancaba, el health check
    # pasaba, y cualquier acción de administración devolvía 403
    main.CON = main.db.connect(tmp_path / "t.db")
    monkeypatch.setattr(config, "TRUST_ALL_CLIENTS", True)
    c = TestClient(main.app, client=DOCKER_GATEWAY)
    assert c.post("/api/settings", json={}).status_code == 200


def test_container_still_rejects_foreign_host_header(tmp_path, monkeypatch):
    # confiar en el cliente no desactiva la protección anti DNS-rebinding
    main.CON = main.db.connect(tmp_path / "t.db")
    monkeypatch.setattr(config, "TRUST_ALL_CLIENTS", True)
    c = TestClient(main.app, client=DOCKER_GATEWAY)
    r = c.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 421
