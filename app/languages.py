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
        # voz neural Piper (ONNX) para la pronunciación; ruta en rhasspy/piper-voices
        "piper_voice": "ca/ca_ES/upc_ona/x_low/ca_ES-upc_ona-x_low.onnx",
        "sources": [
            {"name": "3Cat", "kind": "tv", "url": "https://www.3cat.cat/3cat/",
             "note": "Series y programas de la TV pública catalana"},
            {"name": "3Cat Podcasts", "kind": "pod",
             "url": "https://www.3cat.cat/3cat/podcasts/",
             "note": "Podcasts de Catalunya Ràdio"},
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
        "piper_voice": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx",
        "sources": [
            {"name": "france.tv", "kind": "tv", "url": "https://www.france.tv/",
             "note": "Televisión pública francesa"},
            {"name": "Radio France", "kind": "pod",
             "url": "https://www.radiofrance.fr/podcasts",
             "note": "Podcasts de France Inter, Culture…"},
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
             "note": "Charlas con subtítulos y transcripción"},
            {"name": "Archive.org", "kind": "archive",
             "url": "https://archive.org/details/feature_films",
             "note": "Películas de dominio público"},
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
        "piper_voice": "de/de_DE/thorsten/low/de_DE-thorsten-low.onnx",
        "sources": [
            {"name": "ARD Mediathek", "kind": "tv",
             "url": "https://www.ardmediathek.de/",
             "note": "Televisión pública alemana"},
            {"name": "ZDF", "kind": "tv", "url": "https://www.zdf.de/",
             "note": "Segunda cadena pública"},
            {"name": "Deutschlandfunk", "kind": "pod",
             "url": "https://www.deutschlandfunk.de/podcasts-100.html",
             "note": "Podcasts de la radio pública"},
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
        "piper_voice": "pt/pt_PT/tug%C3%A3o/medium/pt_PT-tug%C3%A3o-medium.onnx",
        "sources": [
            {"name": "RTP Play", "kind": "tv", "url": "https://www.rtp.pt/play/",
             "note": "Televisión pública portuguesa"},
            {"name": "RTP Arquivos", "kind": "archive",
             "url": "https://arquivos.rtp.pt/",
             "note": "Archivo histórico de la RTP"},
            {"name": "Antena 1", "kind": "pod",
             "url": "https://www.rtp.pt/antena1/",
             "note": "Radio pública: programas y podcasts"},
        ],
    },
}

# nombres de los idiomas base para la UI
BASE_NAMES = {"es": "Español", "en": "English"}


def available(code: str) -> bool:
    p = PROFILES.get(code)
    return bool(p and (p.get("translate_repo") or p.get("translate_zip")))


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
    """Idiomas base disponibles para un idioma de estudio (es siempre)."""
    p = PROFILES.get(code or active_code()) or {}
    return ["es", *(p.get("translate_bases") or {})]


def base_code() -> str:
    """Idioma base activo (al que se traduce). Si el guardado no está
    disponible para el idioma de estudio actual, cae a español."""
    try:
        s = json.loads(config.SETTINGS_PATH.read_text())
        b = s.get("base_language", "es")
    except Exception:
        b = "es"
    return b if b in bases(active_code()) else "es"


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
