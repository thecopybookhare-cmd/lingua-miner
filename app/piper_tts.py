"""Voz neural offline con Piper (ONNX, sin torch): pronunciación natural en
catalán/francés. Se descarga una voz (~20-60 MB) por idioma bajo demanda y se
cachea el wav por hash. Todo degrada a '' si Piper o la voz no están, y tts.py
recae en espeak."""
import hashlib
import wave
from pathlib import Path

from . import config, failures

# voces de rhasspy/piper-voices (cada voz = un .onnx + su .onnx.json)
_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
_VOICES: dict = {}      # code -> PiperVoice | None


def _dir() -> Path:
    d = config.MODELS_DIR / "piper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sub(code: str) -> str | None:
    from . import languages
    return languages.PROFILES.get(code, {}).get("piper_voice")


def available(code: str | None = None) -> bool:
    """Hay una voz Piper configurada para este idioma (aunque aún no bajada)."""
    from . import languages
    return _sub(code or languages.active_code()) is not None


def is_downloaded(code: str | None = None) -> bool:
    from . import languages
    code = code or languages.active_code()
    sub = _sub(code)
    return bool(sub and (_dir() / sub.rsplit("/", 1)[-1]).exists())


def download(code: str | None = None):
    """Baja el .onnx y su .onnx.json de la voz del idioma (una vez)."""
    import requests

    from . import languages
    code = code or languages.active_code()
    sub = _sub(code)
    if not sub:
        return
    name = sub.rsplit("/", 1)[-1]
    for suffix in ("", ".json"):
        dest = _dir() / (name + suffix)
        if dest.exists():
            continue
        r = requests.get(_BASE + sub + suffix, timeout=180)
        r.raise_for_status()
        dest.write_bytes(r.content)


def _voice(code: str):
    if code not in _VOICES:
        try:
            from piper import PiperVoice
            sub = _sub(code)
            if not sub:
                _VOICES[code] = None
            else:
                path = _dir() / sub.rsplit("/", 1)[-1]
                if not path.exists():
                    download(code)
                _VOICES[code] = PiperVoice.load(str(path))
        except Exception as e:  # noqa: BLE001
            # El idioma TIENE voz pero no se pudo bajar o cargar. speak()
            # devolvía «» sin más y main.py esperaba una excepción que nunca
            # llegaba: las tarjetas de texto salían sin audio y nadie lo sabía.
            failures.warn_once(
                f"piper-voice-{code}",
                "no se pudo cargar la voz de Piper: las tarjetas de libros "
                "saldrán sin audio", e)
            _VOICES[code] = None
    return _VOICES[code]


def speak(text: str) -> str:
    """Sintetiza `text` a un wav en MEDIA_DIR (cacheado por hash). '' si no hay
    voz Piper para el idioma activo o falla la síntesis."""
    from . import languages
    text = (text or "").strip()
    if not text:
        return ""
    code = languages.active_code()
    v = _voice(code)
    if v is None:
        return ""
    name = ("piper-" + code + "-"
            + hashlib.md5(text.encode()).hexdigest()[:12] + ".wav")
    out = config.MEDIA_DIR / name
    if out.exists():
        return name
    try:
        with wave.open(str(out), "wb") as wf:
            v.synthesize_wav(text, wf)
        return name if out.exists() else ""
    except Exception as e:  # noqa: BLE001
        failures.warn_once(f"piper-synth-{code}",
                           "Piper no pudo sintetizar una frase: la tarjeta va sin audio", e)
        out.unlink(missing_ok=True)          # un wav a medias no es un audio
        return ""
