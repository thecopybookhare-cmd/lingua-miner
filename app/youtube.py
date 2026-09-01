"""yt-dlp download: video (<=720p mp4) + subtitles in the language being studied."""
import glob
from pathlib import Path

from . import config, jobs


def progress_of(d: dict) -> tuple[float | None, str, tuple]:
    """(fracción 0-0.9 o None, clave de traducción, argumentos) desde yt-dlp.

    Los descargadores por fragmentos (DASH/HLS de 3cat, y mucho YouTube) no
    dan `total_bytes` — hay que usar fragment_index/count. Si no hay ninguna
    referencia de total, devolvemos None pero SIEMPRE un mensaje con los MB
    ya descargados, para que la barra nunca quede muda."""
    status = d.get("status")
    if status == "finished":
        return 0.9, "job.preparing", ()
    if status != "downloading":
        return None, "job.downloading", ()
    done = d.get("downloaded_bytes") or 0
    fi, fc = d.get("fragment_index"), d.get("fragment_count")
    if fc:
        frac = 0.9 * min(fi or 0, fc) / fc
        return frac, "job.dl_frag", (round(frac / 0.9 * 100), fi or 0, fc)
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    if total:
        frac = 0.9 * min(done, total) / total
        return frac, "job.dl_pct", (round(frac / 0.9 * 100),)
    return None, "job.dl_mb", (f"{done / 1e6:.1f}",)


def download(jid: str, url: str) -> dict:
    import yt_dlp

    def hook(d):
        frac, clave, args = progress_of(d)
        if frac is not None:
            jobs.set_progress(jid, frac, key=clave, args=args)
        else:
            # sin fracción fiable: mantener la barra donde está, pero
            # actualizar el mensaje (MB descargados) para que se vea vida
            jobs.set_message(jid, "", key=clave, args=args)

    # El idioma de los subtítulos venía fijado a "ca" desde que la app se
    # llamaba CatalàMiner: quien estudiaba otra cosa se descargaba el vídeo sin
    # subtítulos y acababa transcribiendo con Whisper sin necesidad. Se pide el
    # idioma activo, y también sus variantes regionales (pt-BR, zh-Hans…), que
    # es como YouTube etiqueta buena parte de su catálogo.
    from . import languages
    try:
        lang = languages.active_code() or "en"
    except Exception:                                  # noqa: BLE001
        lang = "en"
    opts = {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": str(config.DL_DIR / "%(title).80s-%(id)s.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,   # fallback: subs autogenerados de YouTube
        "subtitleslangs": [lang, f"{lang}-.*"],
        "subtitlesformat": "vtt",
        "noplaylist": True,
        "progress_hooks": [hook],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        media = Path(ydl.prepare_filename(info))
    # yt-dlp nombra el archivo con la etiqueta exacta que sirvió YouTube
    # ("ja", "pt-BR"…), así que se busca cualquiera que empiece por el idioma.
    stem = media.with_suffix("")
    vtt = next((q for q in stem.parent.glob(f"{glob.escape(stem.name)}.{lang}*.vtt")), None)
    manual = any(k == lang or k.startswith(lang + "-")
                 for k in (info.get("subtitles") or {}))
    return {"media_path": str(media),
            "title": info.get("title") or media.stem,
            "subtitles": str(vtt) if vtt else None,
            "subs_kind": "youtube_subs" if manual else "youtube_auto",
            "duration": float(info.get("duration") or 0)}
