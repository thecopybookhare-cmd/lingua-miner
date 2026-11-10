"""Sustantivos: género y forma de diccionario (de momento, alemán).

Para quien aprende alemán el artículo es media palabra, y spaCy no basta:
de_core_news_sm acierta el género de ~85-90 % de los sustantivos y deja
muchos plurales sin lematizar («Handschuhe» se queda en «Handschuhe», y
neutro). Enseñar «das Handschuhe» es peor que no enseñar nada.

La tabla viene del Wikcionario alemán vía gambolputty/german-nouns
(CC BY-SA 4.0): ~100.000 sustantivos con su género y todas sus formas
declinadas. Descarga única (~20 MB) y offline después. Sin ella, lookup()
devuelve None y el popup queda como antes.
"""
import csv
import sqlite3
from pathlib import Path

import requests

from . import config, failures

_CONS: dict = {}       # código de idioma -> conexión sqlite (o None si falló)

# Filas que también son nombres propios («Hund» es un apellido): van detrás
_NAMES = ("Toponym", "Vorname", "Nachname", "Eigenname")


def build_from_lines(lines, db_path: Path):
    """Vuelca el CSV (iterable de líneas) a un índice forma -> (lema, género)."""
    tmp = db_path.with_suffix(".part")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(str(tmp))
    con.execute("CREATE TABLE forms (form TEXT, lemma TEXT, genus TEXT, prio INTEGER, "
                "plural TEXT)")
    reader = csv.reader(lines)
    head = next(reader)
    gi = [i for i, h in enumerate(head) if h.startswith("genus")]
    fi = [i for i, h in enumerate(head) if "singular" in h or "plural" in h]
    # el plural que se enseña: el primero de las columnas de nominativo plural
    pi = [i for i, h in enumerate(head) if h.startswith("nominativ plural")]

    def rows():
        for x in reader:
            if len(x) < len(head) or not x[0] or "Substantiv" not in x[1]:
                continue
            # «m/n» para los de dos géneros (der/das Joghurt); vacío si la
            # fuente no lo sabe, y entonces no se inventa un artículo
            genus = "/".join(dict.fromkeys(x[i] for i in gi if x[i] in ("m", "f", "n")))
            prio = 1 if any(n in x[1] for n in _NAMES) else 0
            plural = next((x[i] for i in pi if x[i]), "")
            for form in dict.fromkeys([x[0]] + [x[i] for i in fi if x[i]]):
                yield form.lower(), x[0], genus, prio, plural
    con.executemany("INSERT INTO forms VALUES (?,?,?,?,?)", rows())
    con.execute("CREATE INDEX ix_form ON forms(form)")
    con.commit()
    con.close()
    tmp.replace(db_path)          # atómico: un corte no deja un índice a medias


def _con():
    from . import languages
    code = languages.active_code()
    if code in _CONS:
        return _CONS[code]
    _CONS[code] = None
    url = languages.PROFILES.get(code, {}).get("noun_lexicon")
    if not url:
        return None
    try:
        # v2: con el plural. El índice anterior no lo tiene: se rehace.
        (config.MODELS_DIR / f"nouns-{code}.sqlite").unlink(missing_ok=True)
        dbp = config.MODELS_DIR / f"nouns-{code}-v2.sqlite"
        if not dbp.exists():
            with requests.get(url, stream=True, timeout=600) as r:
                r.raise_for_status()
                r.encoding = "utf-8"
                build_from_lines(r.iter_lines(chunk_size=1 << 16, decode_unicode=True), dbp)
        _CONS[code] = sqlite3.connect(str(dbp), check_same_thread=False)
    except Exception as e:
        failures.warn_once(f"nouns-{code}", "sin tabla de sustantivos: el popup no "
                           "mostrará el artículo ni el singular", e)
    return _CONS[code]


def lookup(form: str) -> tuple[str, str, str] | None:
    """(lema, género, plural) de una forma:
    «Handschuhe» -> ("Handschuh", "m", "Handschuhe")."""
    con = _con()
    f = (form or "").strip().lower()
    if con is None or not f:
        return None
    r = con.execute("SELECT lemma, genus, plural FROM forms WHERE form=? "
                    "ORDER BY prio, lower(lemma)=? DESC LIMIT 1", (f, f)).fetchone()
    return (r[0], r[1], r[2] or "") if r else None


def headword(*forms: str) -> tuple[str, str, str] | None:
    """(forma de diccionario, lema, género):
    («der Handschuh (pl. Handschuhe)», «Handschuh», «m»).

    Quien aprende alemán memoriza artículo y plural juntos. Sin plural
    (Milch) va solo el artículo; si la palabra solo existe en plural (Leute),
    «die Leute (pl.)». Prueba las formas en orden (lo seleccionado y luego el
    lema de spaCy)."""
    from . import languages
    arts = languages.profile().get("noun_articles") or {}
    for form in forms:
        hit = lookup(form)
        if not hit:
            continue
        lemma, genus, plural = hit
        art = "/".join(dict.fromkeys(arts[g] for g in genus.split("/") if g in arts))
        if not art and plural.lower() == lemma.lower():
            return f"{arts.get('pl', 'die')} {lemma} (pl.)", lemma, genus
        hw = f"{art} {lemma}" if art else lemma
        if plural and art:             # también si no cambia: das Mädchen (pl. Mädchen)
            hw += f" (pl. {plural})"
        return hw, lemma, genus
    return None
