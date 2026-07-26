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


def seed_from_anki(con, deck: str, lang: str = "ca") -> dict:
    """Marca como 'known' el vocabulario que ya estudias en un mazo de Anki.

    Lematiza cada palabra con el modelo del idioma activo (así «coneixes» y
    «conèixer» cuentan como el mismo lema) y nunca pisa un estado existente:
    lo que ya marcaste a mano manda."""
    from . import anki, db, nlp
    words = anki.deck_words(deck)
    current = db.word_statuses(con, lang)
    marked, skipped = 0, 0
    seen: set[str] = set()
    for w in words:
        lemma, _pos = nlp.analyze_selection(w)
        lemma = (lemma or w).lower().strip()
        if not lemma or not nlp.is_wordlike(lemma) or lemma in seen:
            continue
        seen.add(lemma)
        if lemma in current:
            skipped += 1
            continue
        db.set_word_status(con, lemma, "known", lang)
        marked += 1
    return {"marked": marked, "skipped": skipped, "read": len(words)}
