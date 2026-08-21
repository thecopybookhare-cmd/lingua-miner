"""Diccionarios propios importados por el usuario (StarDict, Yomitan…) con
pyglossary. Cada uno se vuelca a un sqlite word→definición y se consulta en el
popup junto a las glosas del Wikcionario. Todo degrada a [] si pyglossary o el
archivo fallan."""
import re
import sqlite3
from pathlib import Path

from . import config, jobs

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_CONS: dict = {}


def _dir() -> Path:
    d = config.MODELS_DIR / "userdicts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean(html: str) -> str:
    """Definición a texto plano (las de StarDict/Yomitan suelen traer HTML)."""
    return _WS.sub(" ", _TAG.sub(" ", html or "")).strip()


def _close(p: Path):
    """Cierra y descarta la conexión cacheada. Imprescindible antes de borrar
    el archivo: en Windows no se puede unlink() un sqlite con la conexión
    abierta (WinError 32); en Unix daría igual, pero así es portable."""
    con = _CONS.pop(str(p), None)
    if con is not None:
        try:
            con.close()
        except Exception:
            pass


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "dic"


def import_file(path: str) -> dict:
    """Lee un diccionario con pyglossary y lo vuelca a un sqlite indexado.
    Devuelve {name, slug, entries}. Lanza ValueError si no se puede leer."""
    from pyglossary.glossary_v2 import Glossary
    Glossary.init()
    g = Glossary()
    if not g.directRead(path):
        raise jobs.JobError("err.dict_unreadable",
                            "no se pudo leer el diccionario")
    name = g.getInfo("name") or g.getInfo("title") or Path(path).stem
    slug = _slug(name)
    dbp = _dir() / f"{slug}.sqlite"
    _close(dbp)
    if dbp.exists():
        dbp.unlink()
    con = sqlite3.connect(str(dbp))
    con.execute("CREATE TABLE d (word TEXT, defi TEXT)")
    con.execute("CREATE TABLE meta (name TEXT, entries INTEGER)")
    count = 0

    def rows():
        nonlocal count
        for e in g:
            defi = _clean(e.defi)
            if not defi:
                continue
            for w in e.l_word:
                w = (w or "").strip().lower()
                if w:
                    count += 1
                    yield w, defi
    con.executemany("INSERT INTO d VALUES (?,?)", rows())
    con.execute("CREATE INDEX ix_w ON d(word)")
    con.execute("INSERT INTO meta VALUES (?,?)", (name, count))
    con.commit()
    con.close()
    return {"name": name, "slug": slug, "entries": count}


def list_dicts() -> list[dict]:
    out = []
    for p in sorted(_dir().glob("*.sqlite")):
        try:
            r = _con(p).execute("SELECT name, entries FROM meta").fetchone()
            out.append({"slug": p.stem, "name": r[0] if r else p.stem,
                        "entries": r[1] if r else 0})
        except Exception:
            out.append({"slug": p.stem, "name": p.stem, "entries": 0})
    return out


def remove(slug: str) -> bool:
    p = _dir() / f"{_slug(slug)}.sqlite"
    _close(p)                             # cerrar antes de borrar (Windows)
    if p.exists():
        p.unlink()
        return True
    return False


def _con(p: Path):
    key = str(p)
    if key not in _CONS:
        _CONS[key] = sqlite3.connect(str(p), check_same_thread=False)
    return _CONS[key]


def lookup(term: str) -> list[tuple[str, str]]:
    """[(definición, nombre_diccionario)] de todos los diccionarios propios."""
    term = (term or "").strip().lower()
    if not term:
        return []
    out: list[tuple[str, str]] = []
    for p in sorted(_dir().glob("*.sqlite")):
        try:
            con = _con(p)
            name = con.execute("SELECT name FROM meta").fetchone()
            name = name[0] if name else p.stem
            for r in con.execute("SELECT defi FROM d WHERE word=? LIMIT 3",
                                 (term,)).fetchall():
                out.append((r[0], name))
        except Exception:
            pass
    return out
