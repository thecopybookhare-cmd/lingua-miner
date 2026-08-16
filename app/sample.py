"""Vídeo de ejemplo generado en local, para probar el bucle el primer minuto.

Un usuario nuevo tiene que buscar contenido, pegarlo y esperar varios minutos a
Whisper antes de ver una sola tarjeta. Esto le da un vídeo corto con
subtítulos ya hechos: abre, hace clic en una palabra, ve la tarjeta. Treinta
segundos en vez de diez minutos.

Se genera aquí y no se descarga: la voz es Piper (que la app ya usa para la
pronunciación) y la imagen sale de ffmpeg. Cero peso en el repo, cero
licencias de terceros, y sale en el idioma que estudia cada uno.

**Solo los idiomas cuyas frases puedo dar por correctas.** Escribir japonés o
coreano de muestra sin poder juzgar el resultado sería colar texto dudoso en
la primera impresión del producto. Añadir un idioma es añadir su entrada aquí
abajo — y `tests/test_sample.py` comprueba que las palabras existan de verdad
en las listas de frecuencia.
"""
import subprocess
from pathlib import Path

from . import config, failures

# Frases cortas y cotidianas, con vocabulario mezclado a propósito: casi todo
# frecuente (para que salga en gris/conocido) y alguna palabra menos común que
# dispare el resaltado de recomendación, que es lo que hay que enseñar.
SENTENCES: dict[str, list[str]] = {
    "ca": [
        "Ahir a la nit vaig veure una pel·lícula molt bona.",
        "No trobo les claus de casa.",
        "Què vols fer demà al matí?",
        "Aquest llibre me'l van regalar quan feia divuit anys.",
        "Fa molt de fred, agafa la jaqueta.",
    ],
    "es": [
        "Anoche vi una película muy buena.",
        "No encuentro las llaves de casa.",
        "¿Qué quieres hacer mañana por la mañana?",
        "Este libro me lo regalaron cuando cumplí dieciocho años.",
        "Hace mucho frío, coge la chaqueta.",
    ],
    "en": [
        "Last night I watched a really good film.",
        "I can't find the keys to the house.",
        "What do you want to do tomorrow morning?",
        "Someone gave me this book when I turned eighteen.",
        "It's freezing outside, take your jacket.",
    ],
    "fr": [
        "Hier soir j'ai vu un très bon film.",
        "Je ne trouve pas les clés de la maison.",
        "Qu'est-ce que tu veux faire demain matin ?",
        "On m'a offert ce livre quand j'ai eu dix-huit ans.",
        "Il fait très froid, prends ta veste.",
    ],
    "it": [
        "Ieri sera ho visto un film molto bello.",
        "Non trovo le chiavi di casa.",
        "Cosa vuoi fare domani mattina?",
        "Mi hanno regalato questo libro quando ho compiuto diciotto anni.",
        "Fa molto freddo, prendi la giacca.",
    ],
    "pt": [
        "Ontem à noite vi um filme muito bom.",
        "Não encontro as chaves de casa.",
        "O que queres fazer amanhã de manhã?",
        "Deram-me este livro quando fiz dezoito anos.",
        "Está muito frio, leva o casaco.",
    ],
    "de": [
        "Gestern Abend habe ich einen sehr guten Film gesehen.",
        "Ich finde die Schlüssel nicht.",
        "Was willst du morgen früh machen?",
        "Dieses Buch habe ich bekommen, als ich achtzehn wurde.",
        "Es ist sehr kalt, nimm deine Jacke mit.",
    ],
    "nl": [
        "Gisteravond heb ik een hele goede film gezien.",
        "Ik kan de sleutels niet vinden.",
        "Wat wil je morgenochtend doen?",
        "Ik heb dit boek gekregen toen ik achttien werd.",
        "Het is heel koud, neem je jas mee.",
    ],
}

GAP = 0.45          # silencio entre frases, para que se separen al leerlas
W, H = 960, 540


def available(code: str) -> bool:
    return code in SENTENCES


def _voice_wav(text: str, dest: Path) -> float:
    """Sintetiza una frase con Piper. Devuelve su duración en segundos."""
    from . import piper_tts
    name = piper_tts.speak(text)
    if not name:
        raise RuntimeError("sin voz Piper para este idioma")
    src = config.MEDIA_DIR / name.rsplit("/", 1)[-1]
    dest.write_bytes(src.read_bytes())
    import wave
    with wave.open(str(dest)) as w:
        return w.getnframes() / float(w.getframerate())


def _build_video(audio: Path, out: Path, total: float):
    """Un fondo con el degradado de la app y el audio encima.

    No lleva texto: el subtítulo ya se dibuja sobre el vídeo, y duplicarlo
    haría que la captura de la tarjeta saliera con la frase repetida.
    """
    from . import media
    ff = media._exe("ffmpeg")
    fondo = (f"color=c=0x151827:s={W}x{H}:d={total:.2f},"
             f"geq=r='24+30*(Y/{H})':g='22+26*(Y/{H})':b='45+70*(Y/{H})'")
    icono = Path(__file__).resolve().parent.parent / "static" / "favicon.png"
    cmd = [ff, "-y", "-f", "lavfi", "-i", fondo]
    if icono.exists():
        # la marca centrada y tenue: sin ella la captura de la tarjeta sale
        # siendo un degradado liso, que es una mala carta de presentación
        cmd += ["-i", str(icono), "-i", str(audio),
                "-filter_complex",
                "[1:v]scale=190:-1,format=rgba,colorchannelmixer=aa=0.20[m];"
                "[0:v][m]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]",
                "-map", "[v]", "-map", "2:a"]
    else:
        cmd += ["-i", str(audio), "-vf", "format=yuv420p"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)


def build(code: str) -> dict:
    """Genera el vídeo y devuelve {path, duration, segments}.

    Los segmentos van con sus tiempos ya calculados, así que la sesión nace
    transcrita: nada de esperar a Whisper para probar la app.
    """
    frases = SENTENCES.get(code)
    if not frases:
        raise ValueError(f"no hay ejemplo para «{code}»")
    out_dir = config.MEDIA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"sample-{code}.mp4"

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        trozos, segs, t = [], [], 0.0
        for i, frase in enumerate(frases):
            w = tdp / f"{i}.wav"
            dur = _voice_wav(frase, w)
            trozos.append(w)
            segs.append({"start": round(t, 2), "end": round(t + dur, 2),
                         "text": frase, "text_es": "", "words": [],
                         "logprob": 0.0})
            t += dur + GAP
        # concatenar con el silencio entre medias
        lista = tdp / "lista.txt"
        silencio = tdp / "gap.wav"
        from . import media
        ff = media._exe("ffmpeg")
        subprocess.run([ff, "-y", "-f", "lavfi", "-i",
                        f"anullsrc=r=22050:cl=mono:d={GAP}", str(silencio)],
                       check=True, capture_output=True, timeout=60)
        partes = []
        for w in trozos:
            partes += [w, silencio]
        lista.write_text("".join(f"file '{p}'\n" for p in partes), encoding="utf-8")
        juntos = tdp / "voz.wav"
        subprocess.run([ff, "-y", "-f", "concat", "-safe", "0", "-i", str(lista),
                        "-c", "copy", str(juntos)],
                       check=True, capture_output=True, timeout=120)
        _build_video(juntos, dest, t)

    return {"path": str(dest), "duration": round(t, 2), "segments": segs}


def build_safe(code: str) -> dict | None:
    """Como build(), pero deja rastro en vez de romper el primer arranque."""
    try:
        return build(code)
    except Exception as e:                            # noqa: BLE001
        failures.warn_once("sample-build",
                           "no pude generar el vídeo de ejemplo", e)
        return None
