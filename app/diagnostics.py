"""Informe de diagnóstico para reportar problemas.

Nada se envía solo. Esto solo REDACTA el informe; abrirlo en GitHub y pulsar
enviar es cosa del usuario, que puede leerlo y editarlo antes. La app se
anuncia sin telemetría y eso incluye no mandar errores a escondidas.

Se redacta el directorio home: las rutas llevan el nombre de usuario y no hace
falta que acabe en un issue público.
"""
import collections
import logging
import platform
import sys
from pathlib import Path

from . import config

REPO = "https://github.com/thecopybookhare-cmd/lingua-miner"

# lo que de verdad ayuda a diagnosticar; el resto es ruido
_PKGS = ("pywebview", "fastapi", "uvicorn", "faster-whisper", "ctranslate2",
         "spacy", "wordfreq", "yt-dlp", "pyobjc-core")



# El informe se escribía solo desde el desktop.log, que únicamente existe si
# arrancaste por el lanzador. Quien usa ./run.sh o uvicorn mandaba issues con
# «(sin desktop.log)» y sin una sola pista. Esto captura el log pase lo que
# pase, y guarda los errores en su propia cola para que el ruido de arranque
# —los avisos de pyglossary, por ejemplo— nunca los desplace.
_FMT = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
_RING: collections.deque = collections.deque(maxlen=400)
_ERRS: collections.deque = collections.deque(maxlen=15)


class _Capture(logging.Handler):
    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:                             # noqa: BLE001
            return
        if record.levelno >= logging.ERROR:
            _ERRS.append(line)
        if _interesting(line):
            _RING.append(line)


_INSTALLED = False


def install():
    """Engancharse al log raíz. Idempotente: se puede llamar de más."""
    global _INSTALLED
    if _INSTALLED:
        return
    h = _Capture()
    h.setFormatter(_FMT)
    root = logging.getLogger()
    root.addHandler(h)
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)
    _INSTALLED = True


def _redact(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~") if home and home != "/" else text


def _version() -> str:
    try:
        import tomllib
        root = Path(__file__).resolve().parent.parent
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]
    except Exception:
        return "?"


def _packages() -> list[str]:
    import importlib.metadata as md
    out = []
    for p in _PKGS:
        try:
            out.append(f"{p} {md.version(p)}")
        except Exception:
            out.append(f"{p} (not installed)")
    return out


def _interesting(line: str) -> bool:
    """Un log lleno de `GET /media/thumb-… 200` no diagnostica nada.

    Se quitan los accesos correctos y se dejan los errores, los avisos y las
    trazas — que es lo único que sirve para entender qué falló.
    """
    if "uvicorn.access" in line and (" 200" in line or " 304" in line):
        return False
    # pyglossary avisa de un plugin saltado por cada formato que necesita lxml:
    # siete líneas idénticas en cada arranque que llenaban el informe entero.
    if "skipping plugin" in line or "not found in" in line:
        return False
    return True


def _log_tail(n: int = 40) -> str:
    log = config.APP_DIR / "desktop.log"
    raw: list[str] = []
    try:
        raw = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        pass
    except Exception as e:                            # noqa: BLE001
        return f"(could not read the log: {e})"
    if raw:
        lines = [ln for ln in raw if _interesting(ln)]
        skipped = len(raw) - len(lines)
        note = f"({skipped} routine lines omitted)\n" if skipped else ""
    else:
        lines, note = list(_RING), "(captured in memory — no desktop.log)\n"
    if not lines:
        return "(no warnings or errors logged)"
    return note + "\n".join(lines[-n:])


def _last_errors() -> str:
    """Los últimos errores con su traza, aparte del tail.

    Es lo único que de verdad se necesita para arreglar un fallo, y era justo
    lo que no llegaba: el tail se lo comían los avisos de arranque.
    """
    return "\n".join(_ERRS) if _ERRS else ""


def _commit() -> str:
    """El hash corto, para saber de un vistazo si el informe viene de una
    versión ya arreglada. Dos de los cinco primeros reportes llegaron de
    gente que no había actualizado, y no había forma de notarlo."""
    try:
        from . import update
        if update.is_git_checkout():
            return update._git("rev-parse", "--short", "HEAD").stdout.strip()
    except Exception:                                 # noqa: BLE001
        pass
    return ""


def _right_now() -> list[str]:
    """Qué estaba haciendo la app cuando se pidió el informe.

    «El vídeo se traba» es indiagnosticable sin esto: el sospechoso habitual
    es una transcripción de Whisper comiéndose la CPU de fondo, y eso no
    salía en ninguna parte del informe."""
    out = []
    try:
        from . import jobs
        run = [f"{j.get('label') or '?'} at {round((j.get('progress') or 0) * 100)}%"
               for j in jobs.JOBS.values() if j.get("status") == "running"]
        out.append(f"background jobs: {', '.join(run) if run else 'none'}")
    except Exception:                                 # noqa: BLE001
        pass
    try:
        from . import transcribe
        loaded = list(getattr(transcribe, "_MODELS", {}))
        out.append(f"whisper loaded in memory: {', '.join(loaded) if loaded else 'none'}")
    except Exception:                                 # noqa: BLE001
        pass
    import os
    out.append(f"cpu cores: {os.cpu_count()}")
    return out


def _degraded() -> list[str]:
    from . import failures
    return failures.details()


def report(extra: str = "") -> str:
    """Informe en texto plano, listo para pegar en un issue."""
    from . import languages
    try:
        lang, base = languages.active_code(), languages.base_code()
    except Exception:
        lang = base = "?"
    bloques = [
        "### What happened\n\n"
        # Un comentario HTML aquí se ve vacío en GitHub, así que la gente
        # escribía DENTRO de él y su descripción quedaba invisible en el issue
        # (le pasó a Rene-V en el #4). Un texto normal no tiene ese problema.
        f"{extra.strip() or '_Describe what you did and what you expected._'}\n",
        "### Environment\n",
        "```",
        f"LinguaMiner {_version()}" + (f"  ·  commit {_commit()}" if _commit() else ""),
        f"{platform.platform()}",
        f"{platform.machine()}  ·  Python {sys.version.split()[0]}",
        f"studying {lang} → {base}",
        "",
        *_packages(),
        "```\n",
        "### Right now\n",
        "```",
        *_right_now(),
        "```\n",
        *(["### Degraded right now\n", "```",
           *_degraded(), "```\n"] if _degraded() else []),
        *(["### Last errors (with traceback)\n", "```",
           _last_errors(), "```\n"] if _last_errors() else []),
        "### Log (last 40 lines)\n",
        "```",
        _log_tail(),
        "```",
    ]
    return _redact("\n".join(bloques))


def issue_url(extra: str = "", title: str = "") -> str:
    """URL de GitHub con el issue ya redactado.

    GitHub corta las URLs muy largas, así que el cuerpo se recorta: el usuario
    siempre puede pegar el log completo a mano, y el aviso se lo dice.
    """
    import urllib.parse
    body = report(extra)
    limit = 5500
    if len(body) > limit:
        body = (body[:limit].rstrip()
                + "\n```\n\n_(log truncated — the full one is in the path shown"
                  " in the app)_")
    q = urllib.parse.urlencode({
        # "Bug: " se enviaba tal cual y llegaba un issue sin título (#5).
        # Vacío obliga a GitHub a pedirlo antes de dejar publicar.
        "title": title or "",
        "body": body,
        "labels": "bug",
    })
    return f"{REPO}/issues/new?{q}"
