"""faster-whisper tiene que poder leer audio con la PyAV que se instala de verdad.

Ningún test pasaba audio por faster-whisper, así que cuando PyAV 19 rompió
decode_audio() (issue #8) el CI siguió en verde: instalaba PyAV 19 y nadie
la usaba. Este decodifica un WAV real con lo que haya instalado el CI.
"""
import math
import struct
import wave

from faster_whisper import decode_audio


def test_decode_audio_works_with_installed_pyav(tmp_path):
    wav = tmp_path / "tono.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 16000)))
                               for i in range(16000)))
    audio = decode_audio(str(wav))
    assert len(audio) == 16000            # 1 s a 16 kHz, lo que espera Whisper
