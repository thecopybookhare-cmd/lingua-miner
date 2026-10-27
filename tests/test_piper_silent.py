"""Piper sin voz tiene que decirse, no devolver «» en silencio."""
import pytest

from app import failures, piper_tts


@pytest.fixture(autouse=True)
def _clean(monkeypatch, tmp_path):
    monkeypatch.setattr(piper_tts, "_VOICES", {})
    monkeypatch.setattr(failures, "_SEEN", {})
    monkeypatch.setattr(piper_tts.config, "MEDIA_DIR", tmp_path)


def test_voice_that_fails_to_load_is_reported(monkeypatch):
    import piper
    monkeypatch.setattr(piper_tts, "_sub", lambda code: "ca/ca_ES/x/low/ca_ES-x-low.onnx")
    monkeypatch.setattr(piper_tts, "download", lambda code=None: None)

    def broken(path):
        raise OSError("model file is corrupt")
    monkeypatch.setattr(piper.PiperVoice, "load", staticmethod(broken))
    assert piper_tts.speak("Bon dia") == ""
    assert any(k.startswith("piper-voice-") for k in failures._SEEN)


def test_language_without_a_voice_is_not_an_error(monkeypatch):
    # que un idioma no tenga voz de Piper es una decisión, no una avería
    monkeypatch.setattr(piper_tts, "_sub", lambda code: None)
    assert piper_tts.speak("こんにちは") == ""
    assert failures._SEEN == {}


def test_synthesis_failure_is_reported_and_leaves_no_half_file(monkeypatch, tmp_path):
    class Voice:
        def synthesize_wav(self, text, wf):
            wf.setnchannels(1)
            raise RuntimeError("phonemizer crashed")
    monkeypatch.setattr(piper_tts, "_voice", lambda code: Voice())
    assert piper_tts.speak("Bon dia") == ""
    assert any(k.startswith("piper-synth-") for k in failures._SEEN)
    assert list(tmp_path.glob("piper-*.wav")) == []
