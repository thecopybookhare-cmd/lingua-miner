"""Tokenization, lemmas, POS (spaCy ca) + word frequency (wordfreq).

spaCy's ca_core_news_sm may be missing; degrade to a regex tokenizer with
lemma == lowercased form so the app still works.
"""
import re

_WORD = re.compile(r"[\w·]+(?:['’][\w·]+)*", re.UNICODE)

# Qué cuenta como palabra de vocabulario: letras con apóstrofos/guiones/punt
# volat interiores («n'hi», «anem-hi», «l·l», «peut-être») y elisiones al
# borde («l'», «'s»). Números y engendros de subs automáticos («què?-no»,
# «tant.-i») quedan fuera del panel de palabras y del % conocido.
_WORDLIKE = re.compile(r"['’]?[^\W\d_]+(?:[·'’-][^\W\d_]+)*['’]?", re.UNICODE)


def is_wordlike(text: str) -> bool:
    return bool(_WORDLIKE.fullmatch(text))


_NLPS: dict = {}   # modelo spaCy por idioma

# Bump para re-tokenizar transcripciones guardadas con lemas antiguos.
# v2: is_word estricto (fuera números y tokens con puntuación interna) + ws.
# v3: verbos separables del alemán («fängt … an» → «anfangen»).
TOK_VERSION = 3

_POS_EQ = {("VERB", "AUX"), ("AUX", "VERB")}


def _correct(form: str, lemma: str, pos: str) -> tuple[str, str]:
    """Fix spaCy's lemma with the Softcatalà forms dictionary.

    spaCy sm mangles capitalized sentence-initial forms ('Ets' -> 'et' NOUN);
    the forms dict is authoritative, spaCy only disambiguates homographs.
    """
    from . import forms
    cands = forms.lookup(form)
    if not cands:
        return lemma, pos
    if lemma in {c[0].lower() for c in cands}:
        return lemma, pos
    for cl, cp in cands:
        if cp == pos or (cp, pos) in _POS_EQ:
            return cl.lower(), pos
    cl, cp = cands[0]
    return cl.lower(), cp or pos


def _head_morpheme(lemma: str) -> str:
    """Primer morfema del lema, para los idiomas cuyo modelo spaCy los encadena.

    El coreano devuelve «영화+를» (nombre + partícula) y «좋+ㄴ». Como el estado
    de cada palabra se guarda por lema, sin esto la misma palabra con dos
    partículas distintas contaría como dos palabras diferentes y nunca llegaría
    a marcarse como conocida.
    """
    from . import languages
    sep = languages.profile().get("lemma_split")
    if sep and sep in lemma:
        head = lemma.split(sep, 1)[0].strip()
        return head or lemma
    return lemma


def _spacy():
    from . import languages
    code = languages.active_code()
    if code not in _NLPS:
        try:
            import spacy
            # El parser solo hace falta para unir la partícula separable con
            # su verbo; cuesta ~0,3 ms por frase.
            off = (["ner"] if languages.PROFILES[code].get("separable_particles")
                   else ["parser", "ner"])
            _NLPS[code] = spacy.load(languages.PROFILES[code]["spacy"], disable=off)
        except Exception:
            _NLPS[code] = None
    return _NLPS[code]


def freq_badge(zipf_value: float) -> str:
    if zipf_value >= 5.0:
        return "common"
    if zipf_value >= 3.3:
        return "medium"
    return "rare"


_ZIPF_WARNED: set = set()


def zipf(word: str) -> float:
    """Frecuencia Zipf de la palabra en el idioma activo.

    Devolver 0.0 en silencio ocultaba un fallo grave: el chino necesita jieba
    (wordfreq[jieba]) para tokenizar, y sin él TODAS las palabras salían con
    zipf 0 — o sea, la recomendación i+1 dejaba de funcionar entera sin que
    nada lo dijera. Ahora se avisa una vez por idioma.
    """
    from . import languages
    lang = languages.profile()["wordfreq"]
    try:
        from wordfreq import zipf_frequency
        return zipf_frequency(word, lang)
    except Exception as e:                       # noqa: BLE001
        if lang not in _ZIPF_WARNED:
            _ZIPF_WARNED.add(lang)
            import logging
            logging.getLogger("nlp").warning(
                "sin frecuencias para «%s» (%s): la recomendación i+1 no podrá "
                "priorizar palabras", lang, e)
        return 0.0


def _zipf_of(surface: str, lemma: str) -> float:
    """Frecuencia de la forma; si no está en la lista, la del lema.

    En coreano «봤어요» no aparece (es una forma conjugada) y salía con 0, o
    sea, descartada por rara cuando es de lo más común. El lema sí está.
    """
    z = zipf(surface)
    if z <= 0 and lemma and lemma != surface.lower():
        z = zipf(lemma)
    return z


def naive_tokenize(text: str) -> list[dict]:
    # "ws": espacio original tras el token — el frontend reconstruye el texto
    # exacto (contracciones como «dels» no se parten en «d els»)
    toks, i = [], 0
    for m in _WORD.finditer(text):
        if m.start() > i:
            gap = text[i:m.start()]
            if gap.strip():
                if toks:
                    toks[-1]["ws"] = " " if gap[:1].isspace() else ""
                toks.append({"t": gap.strip(), "lemma": "", "pos": "",
                             "is_word": False, "zipf": 0.0,
                             "ws": " " if gap[-1:].isspace() else ""})
        w = m.group(0)
        word = is_wordlike(w)
        lemma, pos = _correct(w, w.lower(), "") if word else ("", "")
        toks.append({"t": w, "lemma": lemma, "pos": pos,
                     "is_word": word, "zipf": zipf(w) if word else 0.0,
                     "ws": " " if text[m.end():m.end() + 1].isspace() else ""})
        i = m.end()
    tail = text[i:].strip()
    if tail:
        if toks:
            toks[-1]["ws"] = " " if text[i:i + 1].isspace() else ""
        toks.append({"t": tail, "lemma": "", "pos": "", "is_word": False,
                     "zipf": 0.0, "ws": ""})
    return toks


_UMLAUT = str.maketrans("äöü", "aou")


def _infinitive_guesses(form: str, lemma: str) -> list[str]:
    """Infinitivos posibles de un verbo conjugado. spaCy sm falla a veces
    («stehst» → «stehsen», el imperativo «Komm» → «komm»): se prueba también
    quitando la desinencia, con y sin la metafonía («fängt» → «fangen»)."""
    f = form.lower()
    out = [lemma.lower()]
    for suf in ("est", "st", "et", "t", "e", "en", "n", ""):
        if suf and not f.endswith(suf):
            continue
        stem = f[:len(f) - len(suf)] if suf else f
        if len(stem) < 2:
            continue
        for st in dict.fromkeys((stem, stem.translate(_UMLAUT))):
            out += [st + "n", st + "en"] if st.endswith(("el", "er")) else [st + "en"]
    return list(dict.fromkeys(out))


def _separable_lemmas(doc) -> dict:
    """{índice del token: (infinitivo, partícula)} para los verbos separables.

    En «Der Film fängt um acht Uhr an» el parser engancha «an» a «fängt»
    (dep «svp»); el verbo es «anfangen», no «fangen» (capturar). Los dos
    tokens se quedan con el mismo lema, así que tocar cualquiera de los dos
    abre «anfangen». Entre los candidatos gana el más frecuente en wordfreq:
    descarta «aufstehsen» sin depender de ningún diccionario descargado."""
    from . import languages
    prof = languages.profile()
    if not prof.get("separable_particles"):
        return {}
    import wordfreq
    out = {}
    for tok in doc:
        head = tok.head
        if (tok.dep_ not in ("svp", "compound:prt") or head.i == tok.i
                or head.pos_ not in ("VERB", "AUX")):
            continue
        part = tok.text.lower()
        cands = [part + c for c in _infinitive_guesses(head.text, head.lemma_)]
        best = max(cands, key=lambda c: wordfreq.zipf_frequency(c, prof["wordfreq"]))
        if wordfreq.zipf_frequency(best, prof["wordfreq"]) > 0:
            out[head.i] = out[tok.i] = (best, part)
    return out


def tokenize(text: str) -> list[dict]:
    nlp_model = _spacy()
    if nlp_model is None:
        return naive_tokenize(text)
    toks = []
    doc = nlp_model(text)
    sep = _separable_lemmas(doc)
    for tok in doc:
        if tok.is_space:
            continue
        is_word = not tok.is_punct and is_wordlike(tok.text)
        lemma, pos = ("", "")
        if is_word and tok.i in sep:
            lemma, pos = sep[tok.i][0], "VERB"
        elif is_word:
            lemma, pos = _correct(tok.text, tok.lemma_.lower(), tok.pos_)
            # Sin lematizador (zh_core_web_sm no trae) spaCy devuelve "" y el
            # estado de la palabra se guarda POR LEMA: sin esto, en chino no
            # se podría marcar ninguna palabra. La forma superficial es el
            # lema en los idiomas sin flexión, así que es la caída correcta.
            lemma = lemma or tok.text.lower()
            lemma = _head_morpheme(lemma)
        d = {"t": tok.text, "lemma": lemma, "pos": pos, "is_word": is_word,
             "zipf": _zipf_of(tok.text, lemma) if is_word else 0.0,
             "ws": tok.whitespace_}
        if is_word and tok.i in sep:
            d["sep"] = sep[tok.i][1]           # la partícula: «an» de «anfangen»
        toks.append(d)
    return toks


def selection_info(text: str, context: str = "") -> dict:
    """{lemma, pos, separable} de una palabra o expresión seleccionada
    (separable: la partícula si es un verbo separable, «an»; si no, "").

    When `context` (the full sentence) is given, the selection is located
    inside it and lemma/POS are taken from the in-context analysis — an
    isolated "gos" gets mis-lemmatized as the verb "gosar", but inside
    "El gos corre" spaCy tags it correctly as a noun. Lo mismo hace falta para
    los verbos separables: «fängt» solo no dice nada de «an».
    """
    target = [t["t"].lower() for t in tokenize(text) if t["is_word"]]
    if context and target:
        ctx = [t for t in tokenize(context) if t["is_word"]]
        n = len(target)
        for i in range(len(ctx) - n + 1):
            if [w["t"].lower() for w in ctx[i:i + n]] == target:
                span = ctx[i:i + n]
                if n == 1:
                    return {"lemma": span[0]["lemma"], "pos": span[0]["pos"],
                            "separable": span[0].get("sep") or ""}
                return {"lemma": " ".join(w["lemma"] for w in span), "pos": "EXPR",
                        "separable": ""}
    words = [t for t in tokenize(text) if t["is_word"]]
    if not words:
        return {"lemma": text.lower(), "pos": "", "separable": ""}
    if len(words) == 1:
        return {"lemma": words[0]["lemma"], "pos": words[0]["pos"],
                "separable": words[0].get("sep") or ""}
    return {"lemma": " ".join(w["lemma"] for w in words), "pos": "EXPR",
            "separable": ""}


def analyze_selection(text: str, context: str = "") -> tuple[str, str]:
    """Return (lemma, pos) for a selected word/expression."""
    i = selection_info(text, context)
    return i["lemma"], i["pos"]
