"""Transcribir por defecto tiene que acabar en minutos, no en horas."""
from app import languages as L
from app import transcribe


def test_every_language_defaults_to_a_fast_model():
    # large-v3 en CPU: ~4 h 30 por episodio de 45 min (issue #3)
    for code, p in L.PROFILES.items():
        default = p["default_whisper"]
        assert "small" in default, f"{code}: {default}"
        assert default in p["whisper_models"], code
        assert next(iter(p["whisper_models"])) == default, f"{code}: el rápido va primero"


def test_best_quality_models_are_still_offered():
    assert "catala-large" in L.PROFILES["ca"]["whisper_models"]
    assert "large-v3" in L.PROFILES["de"]["whisper_models"]
    assert "yue-large" in L.PROFILES["yue"]["whisper_models"]


def test_beam_size_by_model():
    assert transcribe.beam_size("small") == 1
    assert transcribe.beam_size("yue-small") == 1
    assert transcribe.beam_size("large-v3") == 5
    assert transcribe.beam_size("catala-large") == 5


def test_transcribe_passes_the_beam_to_whisper(monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, *a, **k):
            seen.update(k)
            return iter([]), None

    monkeypatch.setattr(transcribe, "_model", lambda key: FakeModel())
    transcribe.transcribe("job", "/x.mp4", "small", 60.0)
    assert seen["beam_size"] == 1 and seen["vad_filter"] and seen["word_timestamps"]
