"""Glosas del Wikcionario por idioma (extracciones de kaikki.org), en el
idioma base activo: las españolas para base es, las inglesas para base en.

Antes solo había españolas, así que quien estudiaba con base inglesa se
quedaba sin ninguna definición — solo con la traducción neural de la frase.

Descarga única por (idioma, base) y offline después. Degradación total a [] si
no está disponible.
"""
import json
import sqlite3
from pathlib import Path

import requests

from . import config, failures

_CONS: dict = {}          # (code, base) -> conexión sqlite (o None si falló)


def build_from_lines(lines, db_path: Path):
    """Vuelca un JSONL de kaikki a un índice sqlite word->glosas.

    Recibe un iterable de líneas, no el texto entero: los extractos ingleses
    llegan a 153 MB (chino) y cargarlos en memoria dos veces era gratuito
    cuando solo había españoles de 1-8 MB, pero ya no.
    """
    tmp = db_path.with_suffix(".part")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    con.execute("CREATE TABLE glosses (word TEXT, pos TEXT, gloss TEXT)")

    def rows():
        seen = set()
        for line in lines:
            try:
                d = json.loads(line)
            except Exception:
                continue
            w = (d.get("word") or "").strip().lower()
            if not w:
                continue
            pos = d.get("pos") or ""
            for s in d.get("senses") or []:
                for g in s.get("glosses") or []:
                    g = " ".join(g.split())
                    key = (w, g.lower())
                    if g and key not in seen:
                        seen.add(key)
                        yield w, pos, g
    con.executemany("INSERT INTO glosses VALUES (?,?,?)", rows())
    con.execute("CREATE INDEX ix_gw ON glosses(word)")
    con.commit()
    con.close()
    # rename atómico: un corte a media construcción no deja un índice a medias
    # que luego parecería válido
    tmp.replace(db_path)


def build(jsonl_text: str, db_path: Path):
    """Compat: misma construcción a partir del texto completo."""
    build_from_lines(jsonl_text.splitlines(), db_path)


def _url_for(code: str, base: str) -> str | None:
    from . import languages
    p = languages.PROFILES.get(code) or {}
    return p.get("wikdict_url_en") if base == "en" else p.get("wikdict_url")


def _con():
    from . import languages
    code, base = languages.active_code(), languages.base_code()
    key = (code, base)
    if key in _CONS:
        return _CONS[key]
    _CONS[key] = None
    try:
        url = _url_for(code, base)
        if not url:
            return None
        suffix = f"{code}-{base}" if base != "es" else code   # compat: es sin sufijo
        dbp = config.MODELS_DIR / f"wikdict-{suffix}.sqlite"
        if not dbp.exists():
            jsonl = config.MODELS_DIR / f"wikdict-{suffix}.jsonl"
            if not jsonl.exists():
                with requests.get(url, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    with open(jsonl, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1 << 20):
                            f.write(chunk)
            with open(jsonl, encoding="utf-8") as f:
                build_from_lines(f, dbp)
        _CONS[key] = sqlite3.connect(str(dbp), check_same_thread=False)
    except Exception as e:
        failures.warn_once(
            f"wikdict-{key}",
            f"sin glosas del Wikcionario para {key[0]} (base {key[1]}): el "
            "popup se quedará sin definiciones", e)
        _CONS[key] = None
    return _CONS[key]


def lookup(term: str) -> list[tuple[str, str]]:
    """[(glosa, pos)] para el término, en el idioma base activo."""
    con = _con()
    if con is None or not term:
        return []
    rs = con.execute(
        "SELECT gloss, pos FROM glosses WHERE word=? LIMIT 6",
        (term.strip().lower(),)).fetchall()
    return [(r[0], r[1]) for r in rs]
