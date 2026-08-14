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
TOK_VERSION = 2

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


def _spacy():
    from . import languages
    code = languages.active_code()
    if code not in _NLPS:
        try:
            import spacy
            _NLPS[code] = spacy.load(languages.PROFILES[code]["spacy"],
                                     disable=["parser", "ner"])
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


def tokenize(text: str) -> list[dict]:
    nlp_model = _spacy()
    if nlp_model is None:
        return naive_tokenize(text)
    toks = []
    for tok in nlp_model(text):
        if tok.is_space:
            continue
        is_word = not tok.is_punct and is_wordlike(tok.text)
        lemma, pos = ("", "")
        if is_word:
            lemma, pos = _correct(tok.text, tok.lemma_.lower(), tok.pos_)
            # Sin lematizador (zh_core_web_sm no trae) spaCy devuelve "" y el
            # estado de la palabra se guarda POR LEMA: sin esto, en chino no
            # se podría marcar ninguna palabra. La forma superficial es el
            # lema en los idiomas sin flexión, así que es la caída correcta.
            lemma = lemma or tok.text.lower()
        toks.append({"t": tok.text, "lemma": lemma, "pos": pos,
                     "is_word": is_word,
                     "zipf": zipf(tok.text) if is_word else 0.0,
                     "ws": tok.whitespace_})
    return toks


def analyze_selection(text: str, context: str = "") -> tuple[str, str]:
    """Return (lemma, pos) for a selected word/expression.

    When `context` (the full sentence) is given, the selection is located
    inside it and lemma/POS are taken from the in-context analysis — an
    isolated "gos" gets mis-lemmatized as the verb "gosar", but inside
    "El gos corre" spaCy tags it correctly as a noun.
    """
    target = [t["t"].lower() for t in tokenize(text) if t["is_word"]]
    if context and target:
        ctx = [t for t in tokenize(context) if t["is_word"]]
        n = len(target)
        for i in range(len(ctx) - n + 1):
            if [w["t"].lower() for w in ctx[i:i + n]] == target:
                span = ctx[i:i + n]
                if n == 1:
                    return span[0]["lemma"], span[0]["pos"]
                return " ".join(w["lemma"] for w in span), "EXPR"
    words = [t for t in tokenize(text) if t["is_word"]]
    if not words:
        return text.lower(), ""
    if len(words) == 1:
        return words[0]["lemma"], words[0]["pos"]
    return " ".join(w["lemma"] for w in words), "EXPR"
