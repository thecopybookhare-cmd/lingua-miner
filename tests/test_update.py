"""Actualizador: check/apply sobre el checkout (git mockeado)."""
import subprocess
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app import update

LOCAL = "abc1234" + "0" * 33
REMOTE = "fed9876" + "0" * 33


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def _cp(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def _fake_git(outs, calls=None):
    """_git falso. Busca primero por los dos primeros argumentos (así
    `rev-parse --is-shallow-repository` y `rev-parse HEAD` pueden responder
    distinto) y si no, por el subcomando."""
    def run(*a, **k):
        if calls is not None:
            calls.append(a)
        return outs[a[:2]] if a[:2] in outs else outs[a[0]]
    return run


def test_check_reports_behind(tmp_path):
    c = client(tmp_path)
    outs = {"rev-parse": _cp(LOCAL + "\n"),
            "ls-remote": _cp(f"{REMOTE}\trefs/heads/main\n")}
    with patch.object(update, "_git", side_effect=_fake_git(outs)):
        r = c.get("/api/update/check").json()
    assert r == {"git": True, "current": "abc1234", "behind": 1, "latest": "fed9876"}


def test_check_up_to_date(tmp_path):
    c = client(tmp_path)
    outs = {"rev-parse": _cp(LOCAL + "\n"),
            "ls-remote": _cp(f"{LOCAL}\trefs/heads/main\n")}
    with patch.object(update, "_git", side_effect=_fake_git(outs)):
        r = c.get("/api/update/check").json()
    assert r == {"git": True, "current": "abc1234", "behind": 0, "latest": "abc1234"}


def test_check_failure_is_an_error_not_up_to_date(tmp_path):
    # La regresión de v1.33.2: si git falla, la respuesta no puede ser
    # «estás al día». Así quedaron dos usuarios una semana atrapados en 1.32.0.
    c = client(tmp_path)
    outs = {"rev-parse": _cp(LOCAL + "\n"),
            "ls-remote": _cp("", returncode=128, stderr="fatal: unable to access")}
    with patch.object(update, "_git", side_effect=_fake_git(outs)):
        r = c.get("/api/update/check").json()
    assert "unable to access" in r.get("error", "")
    assert "behind" not in r


def test_check_without_git_checkout(tmp_path):
    c = client(tmp_path)
    with patch.object(update, "is_git_checkout", return_value=False):
        assert c.get("/api/update/check").json() == {"git": False}


def test_apply_pull_and_deps_hint(tmp_path):
    c = client(tmp_path)
    outs = {("rev-parse", "--is-shallow-repository"): _cp("false\n"),
            "diff": _cp("pyproject.toml\napp/main.py\n"), "pull": _cp("ok"),
            "rev-parse": _cp("def5678\n")}
    with patch.object(update, "_git", side_effect=_fake_git(outs)), \
         patch.object(update, "install_deps", return_value="sin uv"):
        r = c.post("/api/update/apply").json()
    assert r["ok"] and r["deps_changed"] and r["current"] == "def5678"
    assert r["installer"] in ("./install.sh", "install.ps1")
    assert r["deps_installed"] is False


def test_apply_unshallows_a_shallow_clone_first(tmp_path):
    # El bootstrap clona con --depth 1: sin completar la historia, el
    # fast-forward no tiene contra qué avanzar.
    c = client(tmp_path)
    calls = []
    outs = {("rev-parse", "--is-shallow-repository"): _cp("true\n"),
            "fetch": _cp(), "pull": _cp("ok"), "diff": _cp(""),
            "rev-parse": _cp("def5678\n")}
    with patch.object(update, "_git", side_effect=_fake_git(outs, calls)):
        r = c.post("/api/update/apply").json()
    assert r["ok"]
    assert ("fetch", "--unshallow", "origin", "main") in calls
    subcmds = [a[0] for a in calls]
    assert subcmds.index("fetch") < subcmds.index("pull")


def test_apply_surfaces_pull_error(tmp_path):
    c = client(tmp_path)
    outs = {("rev-parse", "--is-shallow-repository"): _cp("false\n"),
            "diff": _cp(""),
            "pull": _cp("", returncode=1, stderr="error: local changes")}
    with patch.object(update, "_git", side_effect=_fake_git(outs)):
        r = c.post("/api/update/apply").json()
    assert "error" in r and "local changes" in r["error"]


def _pull_with_new_deps():
    return {("rev-parse", "--is-shallow-repository"): _cp("false\n"),
            "diff": _cp("pyproject.toml\n"), "pull": _cp("ok"),
            "rev-parse": _cp("def5678\n")}


def test_apply_installs_new_deps_itself(tmp_path, monkeypatch):
    # el botón ya no manda a volver a ejecutar el instalador (Mac/Linux)
    c = client(tmp_path)
    monkeypatch.setattr(update.sys, "platform", "darwin")
    with patch.object(update, "_git", side_effect=_fake_git(_pull_with_new_deps())), \
         patch.object(update, "install_deps", return_value=None) as inst:
        r = c.post("/api/update/apply").json()
    inst.assert_called_once()
    assert r["deps_changed"] and r["deps_installed"] and r["deps_error"] is None


def test_apply_falls_back_to_installer_if_deps_fail(tmp_path, monkeypatch):
    c = client(tmp_path)
    monkeypatch.setattr(update.sys, "platform", "linux")
    with patch.object(update, "_git", side_effect=_fake_git(_pull_with_new_deps())), \
         patch.object(update, "install_deps", return_value="network down"):
        r = c.post("/api/update/apply").json()
    assert r["deps_installed"] is False and r["deps_error"] == "network down"


def test_apply_never_installs_deps_on_windows(tmp_path, monkeypatch):
    # Windows bloquea los paquetes compilados cargados: instalación a medias
    c = client(tmp_path)
    monkeypatch.setattr(update.sys, "platform", "win32")
    with patch.object(update, "_git", side_effect=_fake_git(_pull_with_new_deps())), \
         patch.object(update, "install_deps") as inst:
        r = c.post("/api/update/apply").json()
    inst.assert_not_called()
    assert r["deps_installed"] is False


def test_install_deps_runs_uv_on_this_venv(monkeypatch):
    monkeypatch.setattr(update, "_uv", lambda: "/home/u/.local/bin/uv")
    seen = {}

    def fake_run(cmd, **k):
        seen["cmd"] = cmd
        return _cp("", 0)
    monkeypatch.setattr(update.subprocess, "run", fake_run)
    assert update.install_deps() is None
    assert seen["cmd"] == ["/home/u/.local/bin/uv", "pip", "install", "-p",
                           update.sys.executable, "-e", str(update.REPO_DIR)]


def test_install_deps_reports_uv_failure(monkeypatch):
    monkeypatch.setattr(update, "_uv", lambda: "uv")
    monkeypatch.setattr(update.subprocess, "run",
                        lambda *a, **k: _cp("", 2, "No solution found"))
    assert "No solution found" in update.install_deps()


def test_install_deps_without_uv(monkeypatch):
    monkeypatch.setattr(update, "_uv", lambda: None)
    assert update.install_deps() == "no encontré uv"


def test_uv_found_outside_path(tmp_path, monkeypatch):
    # abierta con doble clic, la app no tiene ~/.local/bin en el PATH
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "uv").write_text("", encoding="utf-8")
    monkeypatch.setattr(update.shutil, "which", lambda _: None)
    monkeypatch.setattr(update.Path, "home", lambda: tmp_path)
    assert update._uv() == str(tmp_path / ".local" / "bin" / "uv")
