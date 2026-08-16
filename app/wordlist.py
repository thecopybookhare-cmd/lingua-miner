"""Leer listas de palabras exportadas por otras herramientas.

Quien llega desde Migaku, jpdb, LingQ o un mazo de Anki ya sabe miles de
palabras. Si la app las marca todas como nuevas, el primer vídeo sale rojo
entero y la recomendación no sirve para nada — es el momento exacto en que se
abandona una herramienta.

**No hay soporte por formato, y es a propósito.** No tengo exportaciones reales
de Migaku ni de jpdb para verificar sus esquemas, y decir «compatible con
Migaku» sin haberlo probado sería mentir. Lo que hay es un lector tolerante que
reconoce las CUATRO FORMAS en que todas ellas guardan una lista: texto plano,
CSV/TSV, JSON de cadenas y JSON de objetos. Si una herramienta cambia su
formato mañana, esto probablemente lo siga leyendo.
"""
import csv
import io
import json
import re

# Cabeceras que suelen contener la palabra en un CSV. En orden de preferencia:
# "word" gana a "expression" si están las dos.
_COLS = ("word", "vocab", "vocabulary", "term", "expression", "lemma",
         "headword", "spelling", "front", "palabra", "kanji", "reading")

# Estados que significan "esto NO lo sé": si el archivo trae una columna de
# estado, no tiene sentido importar como conocido lo que está marcado nuevo.
# "learning" entra aquí a propósito: quien está aprendiendo una palabra no la
# sabe, y marcarla conocida la sacaría de las recomendaciones justo cuando más
# falta hacen. Restaurar estados tal cual es lo que hace /api/words/import.
_NOT_KNOWN = {"new", "unknown", "nuevo", "nueva", "0", "never-forget-no",
              "ignore", "ignored", "suspended", "blacklisted",
              "learning", "aprendiendo", "aprenent", "tracking"}
_STATUS_COLS = ("status", "state", "known", "estado", "card_state")


def _clean(w: str) -> str:
    w = (w or "").strip().strip('"\'' + "﻿")
    # las exportaciones suelen traer "palabra (nota)" o "palabra [lectura]"
    w = re.sub(r"\s*[\(\[（【].*?[\)\]）】]\s*$", "", w)
    return w.strip()


def _from_json(data) -> list[str]:
    out: list[str] = []
    if isinstance(data, dict):
        # {"statuses": {...}} — nuestro propio export
        for k in ("statuses", "words", "vocabulary", "terms", "cards", "data"):
            if k in data:
                return _from_json(data[k])
        # {"palabra": "known", ...}
        for k, v in data.items():
            if isinstance(v, str) and v.lower() in _NOT_KNOWN:
                continue
            out.append(str(k))
        return out
    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                estado = next((str(item[c]).lower() for c in _STATUS_COLS
                               if c in item), "")
                if estado in _NOT_KNOWN:
                    continue
                for c in _COLS:
                    if item.get(c):
                        out.append(str(item[c]))
                        break
    return out


def _from_table(text: str) -> list[str]:
    """CSV o TSV. Elige la columna de palabra por cabecera; si no hay
    cabecera reconocible, usa la primera."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel_tab if "\t" in sample else csv.excel
    filas = list(csv.reader(io.StringIO(text), dialect))
    if not filas:
        return []
    cabecera = [c.strip().lower().lstrip("﻿") for c in filas[0]]
    i_word = next((cabecera.index(c) for c in _COLS if c in cabecera), None)
    i_est = next((cabecera.index(c) for c in _STATUS_COLS if c in cabecera), None)
    cuerpo = filas[1:] if i_word is not None or i_est is not None else filas
    if i_word is None:
        i_word = 0
    out = []
    for fila in cuerpo:
        if len(fila) <= i_word:
            continue
        if i_est is not None and len(fila) > i_est:
            if fila[i_est].strip().lower() in _NOT_KNOWN:
                continue
        out.append(fila[i_word])
    return out


def parse(raw: bytes | str) -> list[str]:
    """Palabras de un archivo exportado, sea cual sea su forma.

    Devuelve las cadenas tal cual (sin lematizar): de eso se encarga quien
    importa, con el modelo del idioma activo.
    """
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
    text = text.lstrip("﻿").strip()
    if not text:
        return []

    crudas: list[str] = []
    if text[0] in "[{":
        try:
            crudas = _from_json(json.loads(text))
        except Exception:
            crudas = []
    if not crudas and re.search(r"[,;\t|]", text.split("\n", 1)[0]):
        try:
            crudas = _from_table(text)
        except Exception:
            crudas = []
    if not crudas:                       # texto plano, una por línea
        crudas = text.splitlines()

    vistas: set[str] = set()
    out: list[str] = []
    for w in crudas:
        w = _clean(str(w))
        # los comentarios y las líneas de cabecera sueltas no son vocabulario
        if not w or w.startswith("#") or w.lower() in _COLS:
            continue
        clave = w.lower()
        if clave in vistas:
            continue
        vistas.add(clave)
        out.append(w)
    return out
