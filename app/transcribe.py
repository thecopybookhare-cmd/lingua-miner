"""faster-whisper transcription with word timestamps + spaCy tokens."""
from . import jobs, nlp

_MODELS: dict[str, object] = {}


def _model(key: str):
    from faster_whisper import WhisperModel

    from . import languages
    code = languages.active_code()
    models = languages.PROFILES[code]["whisper_models"]
    cache_key = (code, key)
    if cache_key not in _MODELS:
        _MODELS[cache_key] = WhisperModel(models.get(key) or key,
                                          device="cpu", compute_type="int8")
    return _MODELS[cache_key]


def transcribe(jid: str, media_path: str, model_key: str,
               duration: float) -> list[dict]:
    """Return segments: {start,end,text,logprob,words:[{w,start,end}],tokens:[...]}"""
    from . import languages
    jobs.set_progress(jid, 0.01, "Cargando modelo… (la primera vez se descarga)")
    model = _model(model_key)
    # el modelo ya está: lo que viene ahora (VAD sobre todo el audio) tarda
    # minutos en un capítulo largo, así que el mensaje debe reflejarlo — antes
    # se quedaba en «Cargando modelo…» y parecía que no avanzaba
    jobs.set_progress(jid, 0.02, "Analizando el audio… (puede tardar unos minutos)")
    segments, _info = model.transcribe(
        media_path, language=languages.active_code(), beam_size=5,
        word_timestamps=True, vad_filter=True)
    out = []
    for seg in segments:
        words = [{"w": w.word.strip(), "start": w.start, "end": w.end}
                 for w in (seg.words or [])]
        out.append({"start": seg.start, "end": seg.end,
                    "text": seg.text.strip(),
                    "logprob": seg.avg_logprob,
                    "words": words,
                    "tokens": nlp.tokenize(seg.text.strip())})
        if duration:
            jobs.set_progress(jid, min(0.99, seg.end / duration),
                              "Transcribiendo…")
    return out


def tokens_for_existing(segs: list[dict]) -> list[dict]:
    """Add tokens to segments parsed from an .srt (no word timestamps)."""
    for s in segs:
        s["words"] = []
        s["logprob"] = 0.0
        s["tokens"] = nlp.tokenize(s["text"])
    return segs
