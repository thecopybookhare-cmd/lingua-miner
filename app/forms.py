"""Softcatalà/LanguageTool forms dictionary: inflected form -> (lemma, POS).

diccionari.txt (1.3M lines, "form lemma TAG") is downloaded once and dumped
into a small SQLite index so lookups don't keep ~300 MB of dicts in RAM.
Everything degrades to empty results when the file can't be fetched.
"""
import sqlite3
from pathlib import Path

import requests

from . import config, sqlshare

_TXT_PATH = config.MODELS_DIR / "diccionari-lt.txt"   # nombre legado (ca)
_DB_PATH = config.MODELS_DIR / "forms.sqlite"         # nombre legado (ca)

_CON = None
_TRIED = False
_LANG = None

_POS = {"V": "VERB", "N": "NOUN", "A": "ADJ", "R": "ADV", "D": "DET",
        "P": "PRON", "C": "CONJ", "S": "ADP", "I": "INTJ", "M": "NUM",
        "Z": "NUM"}


def _pos_of(tag: str) -> str:
    if tag.startswith("NP"):
        return "PROPN"
    return _POS.get(tag[:1], "")


def build(txt: str, db_path: Path):
    """One-shot dump of diccionari.txt into an indexed SQLite file.
    Guarda también el tag morfológico crudo (VMIP3S00…) para las tablas de
    conjugación, e indexa por lema."""
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(str(db_path))
    con.execute("CREATE TABLE forms (form TEXT, lemma TEXT, pos TEXT, tag TEXT)")

    def rows():
        for line in txt.splitlines():
            p = line.split(" ")
            if len(p) >= 3 and p[0] and p[1]:
                yield p[0], p[1], _pos_of(p[2]), p[2]
    con.executemany("INSERT INTO forms VALUES (?,?,?,?)", rows())
    con.execute("CREATE INDEX ix_form ON forms(form)")
    con.execute("CREATE INDEX ix_lemma ON forms(lemma)")
    con.commit()
    con.close()


def _has_tag_column(dbp: Path) -> bool:
    try:
        c = sqlite3.connect(str(dbp))
        cols = {r[1] for r in c.execute("PRAGMA table_info(forms)")}
        c.close()
        return "tag" in cols
    except Exception:
        return False


def _paths(code: str) -> tuple[Path, Path]:
    if code == "ca":            # rutas legadas de instalaciones previas
        return _TXT_PATH, _DB_PATH
    return (config.MODELS_DIR / f"diccionari-lt-{code}.txt",
            config.MODELS_DIR / f"forms-{code}.sqlite")


def _con():
    global _CON, _TRIED, _LANG
    from . import languages
    code = languages.active_code()
    if code != _LANG:
        _CON, _TRIED, _LANG = None, False, code
    if _CON is None and not _TRIED:
        _TRIED = True
        try:
            url = languages.PROFILES[code].get("forms_url")
            txt, dbp = _paths(code)
            if dbp.exists() and not _has_tag_column(dbp):
                dbp.unlink()          # esquema viejo sin 'tag' → reconstruir
            if not dbp.exists():
                if not url:
                    _CON = None
                    return _CON
                if not txt.exists():
                    resp = requests.get(url, timeout=120)
                    resp.raise_for_status()
                    txt.write_text(resp.text, encoding="utf-8")
                build(txt.read_text(encoding="utf-8"), dbp)
            _CON = sqlshare.connect(dbp)
        except Exception:
            _CON = None
    return _CON


def lookup(form: str) -> list[tuple[str, str]]:
    """[(lemma, POS)] for the exact form, falling back to lowercase."""
    con = _con()
    if con is None or not form:
        return []
    for f in dict.fromkeys((form, form.lower())):
        rs = con.execute("SELECT DISTINCT lemma, pos FROM forms WHERE form=?",
                         (f,)).fetchall()
        if rs:
            return [(r[0], r[1]) for r in rs]
    return []


def verb_forms(lemma: str) -> list[tuple[str, str]]:
    """[(form, tag)] de todas las formas verbales de un lema (tag empieza por V).
    Vacío si no hay diccionario de formas para el idioma activo."""
    con = _con()
    if con is None or not lemma:
        return []
    rs = con.execute(
        "SELECT form, tag FROM forms WHERE lemma=? AND tag LIKE 'V%'",
        (lemma.strip().lower(),)).fetchall()
    return [(r[0], r[1]) for r in rs]


def known_exact(form: str) -> bool:
    """The form exists spelled exactly like this (e.g. 'Barcelona')."""
    con = _con()
    if con is None:
        return False
    return con.execute("SELECT 1 FROM forms WHERE form=? LIMIT 1",
                       (form,)).fetchone() is not None


def knows_lower(form: str) -> bool:
    """The lowercased form is a known common word (e.g. 'Ets' -> 'ets')."""
    con = _con()
    if con is None:
        return False
    return con.execute("SELECT 1 FROM forms WHERE form=? LIMIT 1",
                       (form.lower(),)).fetchone() is not None
