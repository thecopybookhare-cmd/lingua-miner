"""Actualización de la app: git fetch/pull sobre el propio checkout.

El bootstrap instala clonando el repo, así que actualizar = git pull. Si la
instalación no es un checkout (zip suelto), se informa y no se toca nada.
"""
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO_DIR,
                          capture_output=True, text=True, timeout=timeout)


def is_git_checkout() -> bool:
    return (REPO_DIR / ".git").exists()


def is_shallow() -> bool:
    """El bootstrap clona con --depth 1. En un clon superficial la historia
    está cortada, y ahí `rev-list HEAD..origin/main` puede fallar en vez de
    contar."""
    r = _git("rev-parse", "--is-shallow-repository")
    return r.stdout.strip() == "true"


def check() -> dict:
    """¿Hay algo nuevo publicado? Compara SHAs, no cuenta commits.

    Antes esto hacía `git fetch` + `rev-list --count HEAD..origin/main` y se
    quedaba con stdout sin mirar el código de salida. En un clon superficial
    —que es como instala el bootstrap— rev-list falla, stdout viene vacío,
    int("" or 0) da 0, y la app anunciaba «estás al día» a alguien que iba
    dos versiones por detrás. Comparar el SHA local con el que publica
    ls-remote no necesita historia conectada, ni fetch, ni refs de
    seguimiento: funciona igual en un clon superficial y en uno completo.
    """
    if not is_git_checkout():
        return {"git": False}
    head = _git("rev-parse", "HEAD")
    if head.returncode != 0:
        return {"git": True, "error": (head.stderr.strip() or "git rev-parse falló")[:200]}
    local = head.stdout.strip()
    try:
        ls = _git("ls-remote", "origin", "refs/heads/main", timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"git": True, "error": str(e)[:200]}
    if ls.returncode != 0 or not ls.stdout.strip():
        return {"git": True,
                "error": (ls.stderr.strip() or "no pude consultar el remoto")[:200]}
    remote = ls.stdout.split()[0]
    return {
        "git": True,
        "current": local[:7],
        "behind": 0 if remote == local else 1,   # hay algo nuevo, sí o no
        "latest": remote[:7],
    }


def apply() -> dict:
    """git pull --ff-only. Avisa si cambiaron las dependencias (reinstalar)."""
    if not is_git_checkout():
        return {"error": "la instalación no es un checkout de git"}
    # Un clon superficial no puede hacer fast-forward contra una historia que
    # no tiene. Se completa una vez —tarda unos segundos— y a partir de ahí
    # las actualizaciones son un pull normal.
    if is_shallow():
        u = _git("fetch", "--unshallow", "origin", "main", timeout=300)
        if u.returncode != 0:
            _git("fetch", "origin", "main", timeout=120)
    try:
        p = _git("pull", "--ff-only", "origin", "main", timeout=120)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": str(e)[:300]}
    if p.returncode != 0:
        return {"error": (p.stderr or p.stdout).strip()[:300]}
    diff = _git("diff", "--name-only", "HEAD@{1}..HEAD").stdout
    deps_changed = "pyproject.toml" in diff or "uv.lock" in diff
    return {"ok": True, "deps_changed": deps_changed,
            "current": _git("rev-parse", "--short", "HEAD").stdout.strip()}


def installer_hint() -> str:
    return "install.ps1" if sys.platform.startswith("win") else "./install.sh"
