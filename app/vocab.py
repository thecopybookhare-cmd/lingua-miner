"""Rangos de frecuencia del corpus (wordfreq) lematizados, y marcado en
masa de vocabulario conocido (estilo Language Reactor)."""

_RANKS: dict = {}   # {idioma: {lema: rango}}
_N = 5000


def ranks(n: int = _N) -> dict[str, int]:
    """{lema: rango} para las n palabras más frecuentes del idioma activo.
    Las formas se lematizan con el diccionario de formas; la primera
    aparición (rango más alto) gana."""
    from . import languages
    code = languages.active_code()
    if code not in _RANKS:
        from wordfreq import top_n_list

        from . import forms
        out: dict[str, int] = {}
        for i, w in enumerate(
                top_n_list(languages.PROFILES[code]["wordfreq"], n), start=1):
            cands = forms.lookup(w)
            lemma = (cands[0][0] if cands else w).lower()
            out.setdefault(lemma, i)
        _RANKS[code] = out
    return _RANKS[code]


def bulk_known(con, top_n: int, lang: str = "ca") -> int:
    """Marca como 'known' los lemas de rango <= top_n que aún no tienen
    estado (nunca pisa learning/ignored/tracking)."""
    from . import db
    current = db.word_statuses(con, lang)
    marked = 0
    for lemma, rank in ranks().items():
        if rank <= top_n and lemma not in current:
            db.set_word_status(con, lemma, "known", lang)
            marked += 1
    return marked


def _lemma_of(w: str, forms, nlp) -> str:
    """Lema de una palabra SUELTA, que no es lo mismo que dentro de una frase.

    spaCy necesita contexto: con «gos» a pelo devuelve «gosar» (atreverse), no
    «gos» (perro), porque sin frase alrededor lo toma por verbo. Importar así
    marcaba miles de lemas equivocados — y venía pasando desde que existe el
    sembrado desde Anki.

    El diccionario de formas sí acierta (su primer candidato para «gos» es
    «gos»), así que manda él. Sin diccionario de formas se usa la palabra tal
    cual: quedarse en la forma superficial es peor que nada, pero mucho mejor
    que marcar como conocida una palabra que el usuario no ha dicho.
    """
    w = (w or "").strip()
    cands = forms.lookup(w)
    if cands:
        return cands[0][0].lower().strip()
    return w.lower()


def seed_words(con, words: list[str], lang: str = "ca") -> dict:
    """Marca como 'known' una lista de palabras ya sabidas.

    Lematiza cada una con el modelo del idioma activo (así «coneixes» y
    «conèixer» cuentan como el mismo lema) y nunca pisa un estado existente:
    lo que ya marcaste a mano manda.
    """
    from . import db, forms, nlp
    current = db.word_statuses(con, lang)
    marked, skipped = 0, 0
    seen: set[str] = set()
    for w in words:
        lemma = _lemma_of(w, forms, nlp)
        if not lemma or not nlp.is_wordlike(lemma) or lemma in seen:
            continue
        seen.add(lemma)
        if lemma in current:
            skipped += 1
            continue
        db.set_word_status(con, lemma, "known", lang)
        marked += 1
    return {"marked": marked, "skipped": skipped, "read": len(words)}


def seed_from_anki(con, deck: str, lang: str = "ca") -> dict:
    """El mismo sembrado, leyendo el primer campo de un mazo de Anki."""
    from . import anki
    return seed_words(con, anki.deck_words(deck), lang)
