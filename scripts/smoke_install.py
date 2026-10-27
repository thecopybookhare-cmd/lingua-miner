"""El primer minuto de un usuario nuevo, tras una instalación de verdad.

Lo usa install-test.yml justo después de ejecutar install.sh / install.ps1.
Lo primero que hace alguien nuevo es instalar, y ningún workflow lo probaba:
el CI corría los tests, no los instaladores. Por ahí se colaron el instalador
de Windows que cerraba la ventana (#2) y Transcribir roto en toda instalación
nueva (#8). Corre con el python que acaba de dejar el instalador.
"""
import importlib.util
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FAILS = []


def step(name, fn):
    t = time.time()
    try:
        detail = fn()
        print(f"OK    {name} ({time.time() - t:.0f}s) {detail or ''}", flush=True)
    except Exception as e:  # noqa: BLE001
        FAILS.append(name)
        print(f"FAIL  {name}: {type(e).__name__}: {e}", flush=True)


def server():
    # un puerto libre: el 8977 puede ser la app de verdad, ya abierta
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    # la salida de uvicorn va a un archivo, no a una tubería: una tubería que
    # nadie lee se llena y bloquea al proceso, y si falla hace falta el log
    log = Path(tempfile.gettempdir()) / f"smoke-uvicorn-{port}.log"
    with log.open("w", encoding="utf-8") as out:
        p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app",
                              "--host", "127.0.0.1", "--port", str(port)],
                             stdout=out, stderr=subprocess.STDOUT)
        t = time.time()
        try:
            while time.time() - t < 120:
                try:
                    with urllib.request.urlopen(f"{base}/api/health", timeout=2):
                        break
                except Exception:  # noqa: BLE001
                    if p.poll() is not None:
                        break
                    time.sleep(1)
            else:
                raise TimeoutError("no respondió en 120 s" + _tail(log))
            if p.poll() is not None:
                raise RuntimeError(f"uvicorn terminó con código {p.returncode}" + _tail(log))
            ready = time.time() - t
            with urllib.request.urlopen(f"{base}/", timeout=5) as r:
                assert r.status == 200
            return f"responde a los {ready:.0f}s y sirve la interfaz"
        finally:
            p.terminate()


def _tail(log: Path) -> str:
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    return "\n      " + "\n      ".join(lines) if lines else " (sin salida)"


SPEECH = {}


def voice():
    from app import config, piper_tts
    name = piper_tts.speak("Quan vivia a Girona volia aprendre català mirant sèries.")
    assert name, "Piper no sintetizó nada (speak() devolvió '')"
    SPEECH["path"] = str(config.MEDIA_DIR / name)
    return name


def transcription():
    from faster_whisper import decode_audio

    from app import transcribe
    path = SPEECH["path"]
    dur = len(decode_audio(path)) / 16000
    segs = transcribe.transcribe("smoke", path, "small", dur)
    text = " ".join(s["text"] for s in segs).lower()
    # la voz de Piper es de baja calidad y Whisper small no es perfecto: se
    # oyó «xirona» por «Girona». Lo que importa es que reconozca el habla.
    heard = [w for w in ("quan", "vivia", "girona", "aprendre", "català", "sèries") if w in text]
    assert len(heard) >= 3, f"solo reconoció {heard} en: {text!r}"
    return f"«{text[:60]}»"


def youtube():
    spec = importlib.util.spec_from_file_location(
        "canary", Path(__file__).resolve().parent / "youtube_canary.py")
    canary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canary)
    status, detail = canary.check(canary.VIDEOS[0])
    if status == "broken":
        raise RuntimeError(detail)
    return detail if status == "ok" else f"no concluyente: {detail}"


step("servidor", server)
step("voz (Piper)", voice)
if "path" in SPEECH:
    step("transcripción (Whisper small)", transcription)
step("YouTube (ver online)", youtube)
sys.exit(1 if FAILS else 0)
