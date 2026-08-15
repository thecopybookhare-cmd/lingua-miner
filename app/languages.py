"""Perfiles de idioma: todo lo específico de un idioma vive aquí.

Un perfil es activable cuando tiene traductor validado (translate_repo).
El francés queda preparado pero inactivo hasta validar su traductor →es.
"""
import json

from . import config

PROFILES = {
    "ca": {
        "name": "Català",
        "wordfreq": "ca",
        "espeak": "ca",
        "spacy": "ca_core_news_sm",
        "whisper_models": config.WHISPER_MODELS,
        "default_whisper": config.DEFAULT_WHISPER,
        "translate_repo": config.TRANSLATE_REPO,
        "translate_dir": "translate-cat-spa",     # compat con instalaciones previas
        "bidix_url": config.BIDIX_URL,
        "bidix_file": "apertium-spa-cat.dix",     # compat
        "forms_url": config.FORMS_URL,
        "wikdict_url": ("https://kaikki.org/eswiktionary/Catal%C3%A1n/"
                        "kaikki.org-dictionary-Catal%C3%A1n.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Catalan/kaikki.org-dictionary-Catalan.jsonl",
        # voz neural Piper (ONNX) para la pronunciación; ruta en rhasspy/piper-voices
        "piper_voice": "ca/ca_ES/upc_ona/x_low/ca_ES-upc_ona-x_low.onnx",
        "sources": [
            {"name": "3Cat", "kind": "tv", "url": "https://www.3cat.cat/3cat/",
             "note": "Series y programas de la TV pública catalana", "note_en": "Series and shows from Catalan public TV"},
            {"name": "3Cat Podcasts", "kind": "pod",
             "url": "https://www.3cat.cat/3cat/podcasts/",
             "note": "Podcasts de Catalunya Ràdio", "note_en": "Podcasts from Catalunya Ràdio"},
        ],
        # idiomas base alternativos: traductor estudio→base (además del es)
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-ca-en-ctranslate2",
                   "dir": "translate-cat-eng", "eos": True},
        },
    },
    "fr": {
        "name": "Français",
        "wordfreq": "fr",
        "espeak": "fr",
        "spacy": "fr_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # OPUS-MT fr→es convertido a CTranslate2 (Marian → necesita </s>).
        "translate_repo": "gaudi/opus-mt-fr-es-ctranslate2",
        "translate_eos": True,
        "translate_dir": "translate-fra-spa",
        "bidix_url": ("https://raw.githubusercontent.com/apertium/apertium-fr-es/"
                      "master/apertium-fra-spa.fra-spa.dix"),
        "bidix_file": "apertium-fra-spa.dix",
        "bidix_src": "l",                         # <l>=fra, <r>=spa (fra→spa)
        "forms_url": None,                        # spaCy fr_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Franc%C3%A9s/"
                        "kaikki.org-dictionary-Franc%C3%A9s.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/French/kaikki.org-dictionary-French.jsonl",
        "piper_voice": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
        "sources": [
            {"name": "france.tv", "kind": "tv", "url": "https://www.france.tv/",
             "note": "Televisión pública francesa", "note_en": "French public television"},
            {"name": "Radio France", "kind": "pod",
             "url": "https://www.radiofrance.fr/podcasts",
             "note": "Podcasts de France Inter, Culture…", "note_en": "Podcasts from France Inter, France Culture…"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-fr-en-ctranslate2",
                   "dir": "translate-fra-eng", "eos": True},
        },
    },
    "en": {
        "name": "English",
        "wordfreq": "en",
        "espeak": "en",
        "spacy": "en_core_web_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        "translate_repo": "michaelfeil/ct2fast-opus-mt-en-es",   # OPUS-MT en→es CT2
        "translate_eos": True,
        "translate_dir": "translate-eng-spa",
        "bidix_url": None,                        # sentidos vía Wikcionario
        "bidix_file": "apertium-eng-spa.dix",
        "forms_url": None,                        # spaCy en_core_web_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Ingl%C3%A9s/"
                        "kaikki.org-dictionary-Ingl%C3%A9s.jsonl"),
        "piper_voice": "en/en_US/amy/low/en_US-amy-low.onnx",
        "sources": [
            {"name": "TED Talks", "kind": "tv", "url": "https://www.ted.com/talks",
             "note": "Charlas con subtítulos y transcripción", "note_en": "Talks with subtitles and transcripts"},
            {"name": "Archive.org", "kind": "archive",
             "url": "https://archive.org/details/feature_films",
             "note": "Películas de dominio público", "note_en": "Public-domain films"},
        ],
    },
    "de": {
        "name": "Deutsch",
        "wordfreq": "de",
        "espeak": "de",
        "spacy": "de_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        "translate_repo": "gaudi/opus-mt-de-es-ctranslate2",     # OPUS-MT de→es CT2
        "translate_eos": True,
        "translate_dir": "translate-deu-spa",
        "bidix_url": None,
        "bidix_file": "apertium-deu-spa.dix",
        "forms_url": None,                        # spaCy de_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Alem%C3%A1n/"
                        "kaikki.org-dictionary-Alem%C3%A1n.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl",
        "piper_voice": "de/de_DE/thorsten/low/de_DE-thorsten-low.onnx",
        "sources": [
            {"name": "ARD Mediathek", "kind": "tv",
             "url": "https://www.ardmediathek.de/",
             "note": "Televisión pública alemana", "note_en": "German public television"},
            {"name": "ZDF", "kind": "tv", "url": "https://www.zdf.de/",
             "note": "Segunda cadena pública", "note_en": "The second public channel"},
            {"name": "Deutschlandfunk", "kind": "pod",
             "url": "https://www.deutschlandfunk.de/podcasts-100.html",
             "note": "Podcasts de la radio pública", "note_en": "Podcasts from public radio"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-de-en-ctranslate2",
                   "dir": "translate-deu-eng", "eos": True},
        },
    },
    "pt": {
        "name": "Português",
        "wordfreq": "pt",
        "espeak": "pt",                       # espeak-ng: pt = europeo (pt-br = BR)
        "spacy": "pt_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # No existe un OPUS-MT pt→es bilingüe ni un CT2 pre-hecho; se usa el
        # modelo multilingüe romance (itc-itc): se baja el zip Marian y se
        # convierte a CT2 (torch-free) con el token de destino >>spa<<.
        "translate_repo": None,
        "translate_zip": ("https://object.pouta.csc.fi/Tatoeba-MT-models/"
                          "itc-itc/opus-2020-07-07.zip"),
        "translate_token": ">>spa<<",
        "translate_eos": True,
        "translate_dir": "translate-por-spa",
        "bidix_url": None,                    # sentidos vía Wikcionario (español)
        "bidix_file": "apertium-spa-por.dix",
        "forms_url": None,                    # spaCy pt_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Portugu%C3%A9s/"
                        "kaikki.org-dictionary-Portugu%C3%A9s.jsonl"),
        # voz neural europea (pt_PT), no brasileña
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Portuguese/kaikki.org-dictionary-Portuguese.jsonl",
        "piper_voice": "pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium.onnx",
        "sources": [
            {"name": "RTP Play", "kind": "tv", "url": "https://www.rtp.pt/play/",
             "note": "Televisión pública portuguesa", "note_en": "Portuguese public television"},
            {"name": "RTP Arquivos", "kind": "archive",
             "url": "https://arquivos.rtp.pt/",
             "note": "Archivo histórico de la RTP", "note_en": "RTP's historical archive"},
            {"name": "Antena 1", "kind": "pod",
             "url": "https://www.rtp.pt/antena1/",
             "note": "Radio pública: programas y podcasts", "note_en": "Public radio: shows and podcasts"},
        ],
    },
    "it": {
        "name": "Italiano",
        "wordfreq": "it",
        "espeak": "it",
        "spacy": "it_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # mismo modelo romance multilingüe que el portugués (itc-itc), solo
        # cambia el token de destino; si ya lo bajaste para pt, se reaprovecha
        "translate_repo": None,
        "translate_zip": ("https://object.pouta.csc.fi/Tatoeba-MT-models/"
                          "itc-itc/opus-2020-07-07.zip"),
        "translate_token": ">>spa<<",
        "translate_eos": True,
        "translate_dir": "translate-ita-spa",
        "bidix_url": None,                    # sentidos vía Wikcionario (español)
        "bidix_file": "apertium-spa-ita.dix",
        "forms_url": None,                    # spaCy it_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Italiano/"
                        "kaikki.org-dictionary-Italiano.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Italian/kaikki.org-dictionary-Italian.jsonl",
        "piper_voice": "it/it_IT/paola/medium/it_IT-paola-medium.onnx",
        "sources": [
            {"name": "RaiPlay", "kind": "tv", "url": "https://www.raiplay.it/",
             "note": "Televisión pública italiana", "note_en": "Italian public television"},
            {"name": "RaiPlay Sound", "kind": "pod",
             "url": "https://www.raiplaysound.it/",
             "note": "Radio y podcasts de la RAI", "note_en": "RAI radio and podcasts"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-it-en-ctranslate2",
                   "dir": "translate-ita-eng", "eos": True},
        },
    },
    "ru": {
        "name": "Русский",
        "wordfreq": "ru",
        "espeak": "ru",
        "spacy": "ru_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # No hay OPUS-MT ru→es en CT2 ni zip Marian en Tatoeba (comprobado:
        # rus-spa/ da 404). Este idioma solo ofrece base inglesa; en cuanto
        # exista un ru→es se añade aquí y bases() lo recoge solo.
        "translate_repo": None,
        "translate_zip": None,
        "translate_dir": "translate-rus-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-rus.dix",
        "forms_url": None,                    # spaCy ru_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Ruso/"
                        "kaikki.org-dictionary-Ruso.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Russian/kaikki.org-dictionary-Russian.jsonl",
        "piper_voice": "ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx",
        "sources": [],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-ru-en-ctranslate2",
                   "dir": "translate-rus-eng", "eos": True},
        },
    },
    "nl": {
        "name": "Nederlands",
        "wordfreq": "nl",
        "espeak": "nl",
        "spacy": "nl_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # Solo base inglesa: no hay CT2 nl→es pre-hecho ni zip Marian en
        # Tatoeba (nld-spa/ da 404). El nl→en sí existe convertido.
        "translate_repo": None,
        "translate_zip": None,
        "translate_dir": "translate-nld-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-nld.dix",
        "forms_url": None,                    # spaCy nl_core_news_sm lematiza
        "wikdict_url": ("https://kaikki.org/eswiktionary/Neerland%C3%A9s/"
                        "kaikki.org-dictionary-Neerland%C3%A9s.jsonl"),
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Dutch/kaikki.org-dictionary-Dutch.jsonl",
        "piper_voice": "nl/nl_NL/mls/medium/nl_NL-mls-medium.onnx",
        "sources": [
            {"name": "NPO Start", "kind": "tv", "url": "https://npo.nl/start",
             "note": "Televisión pública neerlandesa",
             "note_en": "Dutch public television"},
            {"name": "VRT MAX", "kind": "tv", "url": "https://www.vrt.be/vrtmax/",
             "note": "Televisión pública flamenca (Bélgica)",
             "note_en": "Flemish public television (Belgium)"},
            {"name": "NPO Radio 1", "kind": "pod",
             "url": "https://www.nporadio1.nl/podcasts",
             "note": "Podcasts de la radio pública",
             "note_en": "Podcasts from Dutch public radio"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-nl-en-ctranslate2",
                   "dir": "translate-nld-eng", "eos": True},
        },
    },
    "zh": {
        "name": "中文",
        "wordfreq": "zh",
        "espeak": "cmn",
        # OBLIGATORIO, no opcional como en los demás: el chino no separa las
        # palabras con espacios, así que sin este modelo el tokenizador de
        # reserva devuelve la frase entera como un solo token y no hay nada
        # que minar. Ver docs/adding-a-language.md.
        "spacy": "zh_core_web_sm",
        "spacy_required": True,
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        # sin zh→es: Tatoeba no tiene zho-spa (404) ni hay CT2 pre-hecho
        "translate_repo": None,
        "translate_zip": None,
        "translate_dir": "translate-zho-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-zho.dix",
        "forms_url": None,
        "wikdict_url": None,                  # las glosas de kaikki son es→X
        # glosas en inglés (Wikcionario EN vía kaikki)
        "wikdict_url_en": "https://kaikki.org/dictionary/Chinese/kaikki.org-dictionary-Chinese.jsonl",
        "piper_voice": "zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx",
        "sources": [
            {"name": "CCTV 央视网", "kind": "tv", "url": "https://tv.cctv.com/",
             "note": "Televisión pública china", "note_en": "Chinese public television"},
            {"name": "Bilibili", "kind": "tv", "url": "https://www.bilibili.com/",
             "note": "Vídeos con subtítulos, muy usado para inmersión",
             "note_en": "Videos with subtitles, an immersion staple"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-zh-en-ctranslate2",
                   "dir": "translate-zho-eng", "eos": True},
        },
    },
    "ja": {
        "name": "日本語",
        # wordfreq necesita MeCab para el japonés; sin él devuelve 0 para todo
        # y la recomendación i+1 se apaga en silencio. De ahí wordfreq[cjk].
        "wordfreq": "ja",
        "espeak": "ja",
        # obligatorio: el japonés tampoco separa palabras con espacios
        "spacy": "ja_core_news_sm",
        "spacy_required": True,
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        "translate_repo": None,           # no hay ja→es en CT2
        "translate_zip": None,
        "translate_dir": "translate-jpn-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-jpn.dix",
        "forms_url": None,
        "wikdict_url": None,
        "wikdict_url_en": ("https://kaikki.org/dictionary/Japanese/"
                           "kaikki.org-dictionary-Japanese.jsonl"),
        "piper_voice": None,              # rhasspy/piper-voices no trae ja
        "sources": [
            {"name": "NHK", "kind": "tv", "url": "https://www.nhk.or.jp/",
             "note": "Televisión pública japonesa",
             "note_en": "Japanese public broadcaster"},
            {"name": "NHK ラジオ", "kind": "pod",
             "url": "https://www.nhk.or.jp/radio/",
             "note": "Radio y podcasts de la NHK",
             "note_en": "NHK radio and podcasts"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-ja-en-ctranslate2",
                   "dir": "translate-jpn-eng", "eos": True},
        },
    },
    "ko": {
        "name": "한국어",
        "wordfreq": "ko",                 # MeCab-ko, vía wordfreq[cjk]
        # ko_core_news_sm encadena morfemas en el lema (영화+를); el estado de
        # la palabra se guarda por lema, así que nos quedamos con el primero
        "lemma_split": "+",
        "espeak": "ko",
        "spacy": "ko_core_news_sm",
        "whisper_models": {"large-v3": "large-v3", "small": "small"},
        "default_whisper": "large-v3",
        "translate_repo": None,           # no hay ko→es en CT2
        "translate_zip": None,
        "translate_dir": "translate-kor-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-kor.dix",
        "forms_url": None,
        "wikdict_url": None,
        "wikdict_url_en": ("https://kaikki.org/dictionary/Korean/"
                           "kaikki.org-dictionary-Korean.jsonl"),
        "piper_voice": "ko/ko_KR/kss/medium/ko_KR-kss-medium.onnx",
        "sources": [
            {"name": "KBS", "kind": "tv", "url": "https://www.kbs.co.kr/",
             "note": "Televisión pública coreana",
             "note_en": "Korean public broadcaster"},
            {"name": "EBS", "kind": "tv", "url": "https://www.ebs.co.kr/",
             "note": "Cadena educativa pública",
             "note_en": "Public educational channel"},
        ],
        "translate_bases": {
            "en": {"repo": "gaudi/opus-mt-ko-en-ctranslate2",
                   "dir": "translate-kor-eng", "eos": True},
        },
    },
    "yue": {
        "name": "粵語",
        # No hay lista de frecuencias cantonesa: wordfreq solo trae "zh". Sirve
        # (el chino cubre el carácter tradicional y hasta palabras propias del
        # cantonés: 睇 3.38, 唔 4.10) pero son frecuencias de chino en general,
        # así que subestima lo que en cantonés hablado es cotidiano. La
        # recomendación funciona, con ese sesgo. Ver docs/adding-a-language.md.
        "wordfreq": "zh",
        "espeak": "yue",
        # zh_core_web_sm segmenta cantonés escrito de forma aproximada: está
        # entrenado en mandarín. Es lo mejor que hay y sin él no habría nada
        # que minar, porque el chino no separa palabras con espacios.
        "spacy": "zh_core_web_sm",
        "spacy_required": True,
        # Whisper genérico transcribe cantonés como si fuera mandarín; estos
        # están afinados para cantonés y ya vienen en CTranslate2.
        "whisper_models": {
            "yue-large": "JackyHoCL/whisper-large-v3-turbo-cantonese-yue-english-ct2",
            "yue-small": "JackyHoCL/whisper-small-cantonese-yue-english-ct2",
            "large-v3": "large-v3",
        },
        "default_whisper": "yue-large",
        # Ni OPUS-MT ni Tatoeba tienen cantonés (yue-eng/ da 404). NLLB-200 sí
        # lo cubre como yue_Hant, y hay conversión CTranslate2 hecha.
        "translate_repo": None,
        "translate_zip": None,
        "translate_dir": "translate-yue-spa",
        "bidix_url": None,
        "bidix_file": "apertium-spa-yue.dix",
        "forms_url": None,
        "wikdict_url": None,
        "wikdict_url_en": ("https://kaikki.org/dictionary/Cantonese/"
                           "kaikki.org-dictionary-Cantonese.jsonl"),
        "piper_voice": None,                  # rhasspy/piper-voices no trae yue
        "sources": [
            {"name": "RTHK 香港電台", "kind": "tv", "url": "https://www.rthk.hk/",
             "note": "Radiotelevisión pública de Hong Kong",
             "note_en": "Hong Kong public broadcaster"},
            {"name": "RTHK Podcasts", "kind": "pod",
             "url": "https://www.rthk.hk/podcast",
             "note": "Programas de radio en cantonés",
             "note_en": "Radio shows in Cantonese"},
        ],
        "translate_bases": {
            "en": {"repo": "JustFrederik/nllb-200-distilled-600M-ct2-int8",
                   "dir": "translate-nllb-600m",
                   "nllb": {"src": "yue_Hant", "tgt": "eng_Latn"}},
        },
    },
}

# nombres de los idiomas base para la UI
BASE_NAMES = {"es": "Español", "en": "English"}


def has_spanish_base(code: str) -> bool:
    """¿Existe traductor de este idioma al español? No todos lo tienen: para
    el ruso no hay ni CT2 pre-hecho ni zip Marian en Tatoeba."""
    p = PROFILES.get(code) or {}
    return bool(p.get("translate_repo") or p.get("translate_zip"))


def available(code: str) -> bool:
    """Activable si tiene traductor a CUALQUIER base, no solo al español."""
    p = PROFILES.get(code)
    return bool(p and (has_spanish_base(code) or p.get("translate_bases")))


def activable() -> list[str]:
    return [c for c in PROFILES if available(c)]


def active_code() -> str:
    try:
        s = json.loads(config.SETTINGS_PATH.read_text())
        code = s.get("language", "ca")
    except Exception:
        code = "ca"
    return code if available(code) else "ca"


def profile() -> dict:
    return PROFILES[active_code()]


def bases(code: str | None = None) -> list[str]:
    """Idiomas base disponibles para un idioma de estudio.

    El español ya no se da por hecho: un idioma sin traductor →es (el ruso)
    solo ofrece las bases que declare en translate_bases.
    """
    c = code or active_code()
    p = PROFILES.get(c) or {}
    out = ["es"] if has_spanish_base(c) else []
    out += [b for b in (p.get("translate_bases") or {}) if b not in out]
    return out or ["es"]


def base_code() -> str:
    """Idioma base activo (al que se traduce).

    "auto" (por defecto en instalaciones nuevas) sigue al idioma de interfaz:
    solo quien tenga la interfaz en español traduce a español, el resto a
    inglés. Antes el español era el valor por defecto para todo el mundo, lo
    que no tiene sentido para quien llega desde un README en inglés.

    Si el valor guardado no existe para el idioma de estudio actual, cae a la
    primera base que sí exista — que no siempre es el español.
    """
    try:
        s = json.loads(config.SETTINGS_PATH.read_text())
        b = s.get("base_language", "auto")
        if b == "auto":
            b = "es" if s.get("ui_lang") == "es" else "en"
    except Exception:
        b = "en"
    avail = bases(active_code())
    return b if b in avail else avail[0]


def translate_spec() -> dict:
    """repo/dir/eos del traductor del par (estudio, base) activo."""
    p = profile()
    b = base_code()
    alt = (p.get("translate_bases") or {}).get(b)
    if alt:
        return alt
    return {"repo": p.get("translate_repo"), "zip": p.get("translate_zip"),
            "token": p.get("translate_token"), "dir": p["translate_dir"],
            "eos": bool(p.get("translate_eos"))}


def spanish_sources_active() -> bool:
    """Las acepciones Apertium y las glosas del Wikcionario son fuentes en
    español: solo tienen sentido con base es."""
    return base_code() == "es"
