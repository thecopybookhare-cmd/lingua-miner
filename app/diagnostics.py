"""Informe de diagnóstico para reportar problemas.

Nada se envía solo. Esto solo REDACTA el informe; abrirlo en GitHub y pulsar
enviar es cosa del usuario, que puede leerlo y editarlo antes. La app se
anuncia sin telemetría y eso incluye no mandar errores a escondidas.

Se redacta el directorio home: las rutas llevan el nombre de usuario y no hace
falta que acabe en un issue público.
"""
import platform
import sys
from pathlib import Path

from . import config

REPO = "https://github.com/thecopybookhare-cmd/lingua-miner"

# lo que de verdad ayuda a diagnosticar; el resto es ruido
_PKGS = ("pywebview", "fastapi", "uvicorn", "faster-whisper", "ctranslate2",
         "spacy", "wordfreq", "yt-dlp", "pyobjc-core")


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
            out.append(f"{p} (no instalado)")
    return out


def _interesting(line: str) -> bool:
    """Un log lleno de `GET /media/thumb-… 200` no diagnostica nada.

    Se quitan los accesos correctos y se dejan los errores, los avisos y las
    trazas — que es lo único que sirve para entender qué falló.
    """
    if "uvicorn.access" in line and (" 200" in line or " 304" in line):
        return False
    return True


def _log_tail(n: int = 40) -> str:
    log = config.APP_DIR / "desktop.log"
    try:
        raw = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return "(sin desktop.log — arrancado desde la terminal)"
    except Exception as e:                            # noqa: BLE001
        return f"(no se pudo leer el log: {e})"
    lines = [ln for ln in raw if _interesting(ln)]
    if not lines:
        return "(log sin errores ni avisos)"
    out = "\n".join(lines[-n:])
    quitadas = len(raw) - len(lines)
    if quitadas:
        out = f"({quitadas} líneas de acceso correctas omitidas)\n" + out
    return out


def report(extra: str = "") -> str:
    """Informe en texto plano, listo para pegar en un issue."""
    from . import languages
    try:
        lang, base = languages.active_code(), languages.base_code()
    except Exception:
        lang = base = "?"
    bloques = [
        "### What happened\n\n"
        f"{extra.strip() or '<!-- describe what you did and what you expected -->'}\n",
        "### Environment\n",
        "```",
        f"LinguaMiner {_version()}",
        f"{platform.platform()}",
        f"{platform.machine()}  ·  Python {sys.version.split()[0]}",
        f"studying {lang} → {base}",
        "",
        *_packages(),
        "```\n",
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
        "title": title or "Bug: ",
        "body": body,
        "labels": "bug",
    })
    return f"{REPO}/issues/new?{q}"
