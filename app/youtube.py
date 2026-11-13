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
    from . import ytdlp
    opts = {
        **ytdlp.base_opts(),
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": str(config.DL_DIR / "%(title).80s-%(id)s.%(ext)s"),
        "writesubtitles": True,
        "writeautomaticsub": True,   # fallback: subs autogenerados de YouTube
        "subtitleslangs": [x for t in languages.sub_tags(lang) for x in (t, f"{t}-.*")],
        "subtitlesformat": "vtt",
        "noplaylist": True,
        # Una página que es una lista (podcast de Deutschlandfunk) se bajaría
        # entera: 100 episodios. Solo el primero, el más reciente.
        "playlist_items": "1",
        "progress_hooks": [hook],
        "quiet": True,
        "noprogress": True,          # la barra ya va por el hook; en consola era ruido
    }
    # Juntar vídeo y audio (bv*+ba) necesita ffmpeg. Sin uno en el PATH, la app
    # usa el de static-ffmpeg, pero yt-dlp no lo encontraba solo: «requested
    # merging of multiple formats but ffmpeg is not installed».
    from . import media
    ff = media._exe("ffmpeg")
    if Path(ff).is_absolute():
        opts["ffmpeg_location"] = ff
    # En YouTube, el mismo vídeo se descarga o da 403 según el cliente con que
    # se pida (ver ytdlp.py): se prueban en orden, igual que en «Ver online».
    last = None
    for args in ytdlp.youtube_attempts(url):
        try:
            with yt_dlp.YoutubeDL({**opts, **({"extractor_args": args} if args else {})}) as ydl:
                info = ydl.extract_info(url, download=True)
                if info.get("entries") and not info.get("formats"):
                    info = next(iter(info["entries"]), None) or info
                media = Path(ydl.prepare_filename(info))
            ytdlp.youtube_worked(args)
            break
        except yt_dlp.utils.DownloadError as e:
            last = e
    else:
        # Sin esto llegaba «ERROR: unable to download video data: HTTP
        # Error 403: Forbidden», que no dice qué hacer.
        if ytdlp.is_blocked(last):
            raise jobs.JobError("err.geo_blocked", ytdlp.BLOCKED_MSG) from last
        raise last
    # yt-dlp nombra el archivo con la etiqueta exacta que sirvió YouTube
    # ("ja", "pt-BR"…), así que se busca cualquiera que empiece por el idioma.
    stem = media.with_suffix("")
    tags = languages.sub_tags(lang)          # ARD los etiqueta «deu», no «de»
    vtt = next((q for t in tags
                for q in stem.parent.glob(f"{glob.escape(stem.name)}.{t}*.vtt")), None)
    manual = any(k == t or k.startswith(t + "-")
                 for k in (info.get("subtitles") or {}) for t in tags)
    return {"media_path": str(media),
            "title": info.get("title") or media.stem,
            "subtitles": str(vtt) if vtt else None,
            "subs_kind": "youtube_subs" if manual else "youtube_auto",
            "duration": float(info.get("duration") or 0)}
