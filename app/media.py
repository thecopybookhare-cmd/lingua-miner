"""ffmpeg helpers: card audio cut, video frame, browser-safe remux."""
import shutil
import subprocess
from pathlib import Path

from . import jobs

FFMPEG = "ffmpeg"
BROWSER_OK = {".mp4", ".m4v", ".mov", ".webm", ".mp3", ".m4a", ".wav", ".aac", ".ogg"}

# Resolución multiplataforma de ffmpeg/ffprobe: primero el PATH (brew/apt/
# winget); si no está, static-ffmpeg descarga binarios estáticos una única vez
# (clave en Windows, donde instalar ffmpeg a mano era la mayor fricción).
_EXES: dict[str, str] = {}


def _exe(name: str) -> str:
    if name in _EXES:
        return _EXES[name]
    path = shutil.which(name)
    if not path:
        try:
            from static_ffmpeg import run as _sf
            ff, fp = _sf.get_or_fetch_platform_executables_else_raise()
            path = ff if name == "ffmpeg" else fp
        except Exception:
            path = name                   # que el error hable de "ffmpeg"
    _EXES[name] = path
    return path


def ffmpeg_available() -> bool:
    """Hay ffmpeg utilizable (del sistema o binario estático descargable)."""
    if shutil.which("ffmpeg"):
        return True
    try:
        from static_ffmpeg import run as _sf
        _sf.get_or_fetch_platform_executables_else_raise()
        return True
    except Exception:
        return False


# Recorta silencio de cabeza y cola dejando ~0.1 s de aire (VAD por umbral de
# ffmpeg, sin dependencias). areverse permite tratar el final como si fuera el
# principio. Umbral conservador (-40 dB) para no comerse habla suave.
_SILENCEREMOVE = (
    "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-40dB:"
    "detection=peak,areverse,"
    "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-40dB:"
    "detection=peak,areverse"
)


def audio_cmd(src: str, start: float, end: float, out: str,
              pad: float = 0.25, trim: bool = False) -> list[str]:
    s = max(0.0, start - pad)
    dur = round(end + pad - s, 3)
    cmd = [_exe("ffmpeg"), "-y", "-ss", str(round(s, 3)), "-i", src, "-t", str(dur)]
    if trim:
        cmd += ["-af", _SILENCEREMOVE]
    return cmd + ["-vn", "-c:a", "libmp3lame", "-q:a", "4", out]


def frame_cmd(src: str, ts: float, out: str) -> list[str]:
    return [_exe("ffmpeg"), "-y", "-ss", str(round(ts, 3)), "-i", src,
            "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", out]


def clip_cmd(src: str, start: float, end: float, out: str,
             max_dur: float = 6.0) -> list[str]:
    """Animated GIF clip of the segment for the flashcard (silent — the
    audio field carries sound). Palette pass keeps size/quality sane.
    GIF over WebP: Homebrew's ffmpeg ships without libwebp, and GIF
    plays everywhere Anki runs. Capped to max_dur seconds."""
    dur = round(min(end - start, max_dur), 3)
    vf = ("fps=8,scale=420:-2:flags=lanczos,split[s0][s1];"
          "[s0]palettegen=max_colors=128[p];"
          "[s1][p]paletteuse=dither=bayer:bayer_scale=4")
    return [_exe("ffmpeg"), "-y", "-ss", str(round(start, 3)), "-i", src,
            "-t", str(dur), "-an", "-filter_complex", vf,
            "-loop", "0", out]


def animated_clip(src, start, end, out, max_dur=6.0, timeout=90):
    _run(clip_cmd(src, start, end, out, max_dur), timeout=timeout)


def merge_ranges(ranges, gap: float = 0.6, pad: float = 0.15):
    """Une tramos de diálogo cercanos (y añade aire) para que el audio
    condensado suene natural y el comando de ffmpeg no sea kilométrico."""
    out: list[list[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in ranges):
        if b <= a:
            continue                       # tramo degenerado: no es diálogo
        a, b = max(0.0, a - pad), b + pad
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def condensed_audio(src: str, ranges, out: str, timeout: float = 1800) -> float:
    """Audio condensado: solo los tramos con diálogo, concatenados en un mp3.

    Es la escucha pasiva del método de inmersión: un capítulo de 50 min queda
    en ~20 min de puro diálogo para el móvil. `aselect` en una sola pasada
    (nada de miles de ficheros temporales). Devuelve la duración resultante.
    """
    rs = merge_ranges(ranges)
    if not rs:
        raise jobs.JobError("err.no_dialogue", "sin tramos de diálogo")
    sel = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in rs)
    _run([_exe("ffmpeg"), "-y", "-i", src,
          "-af", f"aselect='{sel}',asetpts=N/SR/TB",
          "-vn", "-c:a", "libmp3lame", "-q:a", "5", out], timeout=timeout)
    return sum(b - a for a, b in rs)


def download_window(src: str, start: float, dur: float, out: str,
                    timeout: float = 120) -> None:
    """Copia (sin recodificar) la ventana [start, start+dur] a un mp4 local.

    Para fuentes en streaming: hace UN solo seek de red y deja el material en
    disco. Sin esto, el GIF (que decodifica varios segundos de vídeo HD desde
    el stream) tardaba minutos y agotaba el timeout, cayendo a solo-imagen.
    -avoid_negative_ts make_zero: la ventana empieza en t=0 (offsets relativos).
    """
    _run([_exe("ffmpeg"), "-y", "-ss", str(round(max(0.0, start), 3)),
          "-i", src, "-t", str(round(dur, 3)), "-c", "copy",
          "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", out],
         timeout=timeout)


# Sin timeout, una URL de stream caducada deja a ffmpeg colgado minutos y
# bloquea la biblioteca (miniaturas) o el minado enteros.
def _run(cmd: list[str], timeout: float = 90):
    subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def cut_audio(src, start, end, out, pad=0.25, trim=False):
    _run(audio_cmd(src, start, end, out, pad, trim))


def snapshot(src, ts, out):
    _run(frame_cmd(src, ts, out), timeout=45)


def duration(src: str) -> float:
    try:
        p = subprocess.run(
            [_exe("ffprobe"), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", src],
            capture_output=True, text=True, timeout=30)
        return float(p.stdout.strip())
    except (ValueError, subprocess.TimeoutExpired):
        return 0.0


def ensure_browser_playable(src: Path, out_dir: Path) -> Path:
    """Remux (or transcode) into mp4 if the browser can't play `src`."""
    if src.suffix.lower() in BROWSER_OK:
        return src
    out = out_dir / (src.stem + ".mp4")
    if out.exists():
        return out
    # remux/transcode de archivos locales grandes: legítimamente lento
    try:
        _run([_exe("ffmpeg"), "-y", "-i", str(src), "-c", "copy",
              "-movflags", "+faststart", str(out)], timeout=1800)
    except subprocess.CalledProcessError:
        _run([_exe("ffmpeg"), "-y", "-i", str(src), "-c:v", "libx264", "-preset",
              "veryfast", "-crf", "23", "-c:a", "aac",
              "-movflags", "+faststart", str(out)], timeout=3600)
    return out
