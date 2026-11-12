"""Glosas del Wikcionario por idioma (extracciones de kaikki.org), en el
idioma base activo: las españolas para base es, las inglesas para base en.

Antes solo había españolas, así que quien estudiaba con base inglesa se
quedaba sin ninguna definición — solo con la traducción neural de la frase.

Descarga única por (idioma, base) y offline después. Degradación total a [] si
no está disponible.

Hay dos formatos de origen. Los JSONL de kaikki (uno por idioma) y, para el
español con base inglesa, el sqlite de WikDict: el JSONL inglés del español
pesa ~1 GB y WikDict trae las mismas traducciones es→en en 11 MB. Los dos
acaban en el mismo índice glosses(word, pos, gloss), así que lookup() no
distingue de dónde vino.
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


# WikDict guarda la categoría en español dentro del lexentry
# ("spa/gato__sustantivo_masculino__1"); el popup con base inglesa muestra las
# de kaikki ("noun", "verb"…), así que se traducen las que importan.
_WIKDICT_POS = {
    "sustantivo_propio": "name", "sustantivo": "noun", "verbo": "verb",
    "adjetivo": "adj", "adverbio": "adv", "locución": "phrase",
    "pronombre": "pron", "preposición": "prep", "conjunción": "conj",
    "artículo": "article", "interjección": "intj", "sufijo": "suffix",
    "prefijo": "prefix", "refrán": "proverb",
    # los sqlite X-es de WikDict vienen del Wikcionario de X: en alemán
    # («deu/Hund__Substantiv__1»)
    "Substantiv": "noun", "Eigenname": "name", "Vorname": "name",
    "Nachname": "name", "Toponym": "name", "Verb": "verb", "Adjektiv": "adj",
    "Präposition": "prep", "Konjunktion": "conj", "Subjunktion": "conj",
    "Artikel": "article", "Interjektion": "intj", "Grußformel": "intj",
    "Numerale": "num", "Redewendung": "phrase", "Wortverbindung": "phrase",
    "Sprichwort": "proverb", "Abkürzung": "abbrev", "Suffix": "suffix",
    "Präfix": "prefix",
}
# «Personalpronomen», «Lokaladverb», «Modalpartikel»…
_WIKDICT_POS_END = {"pronomen": "pron", "adverb": "adv", "partikel": "particle"}


def _wikdict_pos(lexentry: str | None) -> str:
    parts = (lexentry or "").split("__")
    if len(parts) < 3:
        return ""            # filas sin lexentry: vienen de tablas de traducción
    raw = parts[1]
    for k, v in _WIKDICT_POS.items():
        if raw.startswith(k):
            return v
    for k, v in _WIKDICT_POS_END.items():
        if raw.lower().endswith(k):
            return v
    return raw.replace("_", " ")


def build_from_wikdict(src: Path, db_path: Path):
    """Convierte un sqlite bilingüe de WikDict al índice glosses de siempre.

    Una fila por grupo de traducciones ("cat | tomcat" → "cat, tomcat"),
    ordenadas por importancia para que el LIMIT de lookup() se quede con las
    acepciones principales. WikDict repite a veces el mismo grupo en otro
    orden ("house | home" y "home | house"): se descarta el duplicado.
    """
    tmp = db_path.with_suffix(".part")
    if tmp.exists():
        tmp.unlink()
    out = sqlite3.connect(str(tmp))
    out.execute("CREATE TABLE glosses (word TEXT, pos TEXT, gloss TEXT)")
    inp = sqlite3.connect(f"file:{src}?mode=ro", uri=True)

    def rows():
        seen = set()
        q = ("SELECT written_rep, lexentry, trans_list FROM translation_grouped "
             "ORDER BY lower(written_rep), lexentry IS NULL, importance DESC")
        for word, lex, trans in inp.execute(q):
            w = (word or "").strip().lower()
            items = [t.strip() for t in (trans or "").split("|") if t.strip()]
            if not w or not items:
                continue
            key = (w, frozenset(i.lower() for i in items))
            if key in seen:
                continue
            seen.add(key)
            yield w, _wikdict_pos(lex), ", ".join(items)
    try:
        out.executemany("INSERT INTO glosses VALUES (?,?,?)", rows())
        out.execute("CREATE INDEX ix_gw ON glosses(word)")
        out.commit()
    finally:
        out.close()
        inp.close()
    tmp.replace(db_path)


def build(jsonl_text: str, db_path: Path):
    """Compat: misma construcción a partir del texto completo."""
    build_from_lines(jsonl_text.splitlines(), db_path)


def _url_for(code: str, base: str) -> str | None:
    from . import languages
    p = languages.PROFILES.get(code) or {}
    return p.get("wikdict_url_en") if base == "en" else p.get("wikdict_url")


def _extra_url_for(code: str, base: str) -> str | None:
    """Segunda fuente (un sqlite de WikDict) para un par con poca cobertura."""
    from . import languages
    p = languages.PROFILES.get(code) or {}
    return (p.get("wikdict_extra") or {}).get(base)


def _open(url: str, dbp: Path):
    """Índice de una fuente, descargándolo y construyéndolo si falta."""
    if not dbp.exists():
        if url.endswith((".sqlite3", ".sqlite")):
            src = dbp.with_suffix(".src.part")
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(src, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
            try:
                build_from_wikdict(src, dbp)
            finally:
                src.unlink(missing_ok=True)
        else:
            # Se indexa según llega, sin guardar el JSONL: los extractos
            # ingleses pesan cientos de MB y quedaban en disco para
            # siempre. Además, un JSONL cortado a media descarga se daba
            # por bueno en el siguiente arranque.
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                # iter_lines lee de 512 en 512 bytes por defecto: con
                # cientos de MB son millones de lecturas.
                build_from_lines(r.iter_lines(chunk_size=1 << 16), dbp)
    return sqlite3.connect(str(dbp), check_same_thread=False)


def _drop_stale_jsonl():
    """Las versiones anteriores dejaban el JSONL descargado junto al índice
    (hasta ~1 GB por idioma). Ya no se usa: se borra."""
    for p in config.MODELS_DIR.glob("wikdict-*.jsonl"):
        try:
            p.unlink()
        except OSError:
            pass


def _cons() -> list:
    """Conexiones a las fuentes de glosas del par activo, en orden de
    preferencia: el Wikcionario primero (definiciones), WikDict después."""
    from . import languages
    code, base = languages.active_code(), languages.base_code()
    key = (code, base)
    if key not in _CONS:
        _CONS[key] = None
        suffix = f"{code}-{base}" if base != "es" else code   # compat: es sin sufijo
        _drop_stale_jsonl()
        conns = []
        for url, dbp in ((_url_for(code, base), config.MODELS_DIR / f"wikdict-{suffix}.sqlite"),
                         (_extra_url_for(code, base), config.MODELS_DIR / f"wikdict-{suffix}-wd.sqlite")):
            if not url:
                continue
            try:
                conns.append(_open(url, dbp))
            except Exception as e:
                failures.warn_once(
                    f"wikdict-{key}-{dbp.stem}",
                    f"sin glosas del Wikcionario para {key[0]} (base {key[1]}): el "
                    "popup se quedará sin definiciones", e)
        _CONS[key] = conns or None
    v = _CONS[key]
    return v if isinstance(v, list) else ([v] if v is not None else [])


def lookup(term: str, limit: int = 6) -> list[tuple[str, str]]:
    """[(glosa, pos)] para el término, en el idioma base activo."""
    if not term:
        return []
    out: list[tuple[str, str]] = []
    for con in _cons():
        rs = con.execute(
            "SELECT gloss, pos FROM glosses WHERE word=? LIMIT ?",
            (term.strip().lower(), limit - len(out))).fetchall()
        out += [(r[0], r[1]) for r in rs]
        if len(out) >= limit:
            break
    return out
