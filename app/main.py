"""LinguaMiner — FastAPI backend + static frontend."""
import json
import logging
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    anki,
    config,
    db,
    dictionary,
    examples,
    failures,
    forms,
    ipa,
    jobs,
    languages,
    media,
    nlp,
    piper_tts,
    sample,
    share,
    stream,
    subs,
    textimport,
    translate,
    tts,
    userdict,
    vocab,
    wikdict,
    wordlist,
)


def _gc_media():
    """Cada preview deja cm-*.mp3/.jpg/.gif aunque se cancele la tarjeta, y
    cada pronunciación un wav; sin esto MEDIA_DIR crece para siempre. Se
    borran los cm-* de más de 1 día que ninguna tarjeta referencia y los wav
    de voz de más de 30 días (cacheados por hash: se regeneran solos)."""
    import time
    now = time.time()
    try:
        used = {r[0] for r in CON.execute(
            "SELECT audio_file FROM cards UNION SELECT image_file FROM cards")}
    except Exception:
        return
    for f in config.MEDIA_DIR.glob("cm-*"):
        try:
            if f.name not in used and now - f.stat().st_mtime > 86400:
                f.unlink()
        except OSError:
            pass
    for pat in ("piper-*.wav", "tts-*.wav"):
        for f in config.MEDIA_DIR.glob(pat):
            try:
                if now - f.stat().st_mtime > 30 * 86400:
                    f.unlink()
            except OSError:
                pass


def _warm_models():
    """Precarga en background lo ya descargado para que el primer popup no
    espere a cargar el motor de traducción / el bidix. Nunca dispara
    descargas nuevas: solo toca recursos ya presentes en disco."""
    prof = languages.profile()
    try:
        if translate.is_downloaded():
            translate.translate("hola")            # carga el motor CT2
    except Exception:
        pass
    try:
        if (config.MODELS_DIR / prof["bidix_file"]).exists():
            _dict()                                # carga el bidix en memoria
    except Exception:
        pass
    try:
        _gc_media()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_warm_models, daemon=True).start()
    yield


_log = logging.getLogger("cards")

app = FastAPI(title="LinguaMiner", lifespan=lifespan)


@app.middleware("http")
async def no_stale_ui(request, call_next):
    """Sin esto el navegador cachea index.html/app.js heurísticamente y
    puede servir UI vieja días después de una actualización. no-cache =
    revalidar siempre (ETag -> 304, gratis en localhost)."""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


# Endpoints de administración: con el modo compartir activo, los invitados de
# la red solo estudian (ver, minar, diccionario). Importar rutas del disco,
# tocar settings, disparar descargas o parar el compartir queda reservado al
# equipo anfitrión.
_ADMIN_POSTS = {
    "/api/userdict/import", "/api/userdict/remove",
    "/api/share/start", "/api/share/stop",
    "/api/settings", "/api/anki/deck", "/api/anki/port",
    "/api/setup/download", "/api/words/import", "/api/words/import-list",
    "/api/sessions/upload", "/api/sessions/youtube", "/api/sessions/stream",
    "/api/sessions/text",
    "/api/sessions/sample",
    "/api/update/apply", "/api/words/seed-anki",
}


def _is_local_client(request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "testclient")


def _host_allowed(request) -> bool:
    """Anti DNS-rebinding: el Host debe ser localhost, una IP privada/tailnet
    o un nombre MagicDNS de Tailscale — nunca un dominio de terceros."""
    import ipaddress
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    if not host or host in ("localhost", "testserver"):
        return True
    if host.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


@app.middleware("http")
async def guest_gate(request, call_next):
    if not _host_allowed(request):
        return JSONResponse({"error": "host no permitido"}, status_code=421)
    if not _is_local_client(request):
        p = request.url.path
        # borrar sesiones es una acción de administración: el único DELETE de
        # la API. Los invitados de la red solo estudian, no tocan la biblioteca.
        gated = ((request.method == "POST"
                  and (p in _ADMIN_POSTS or p.endswith("/transcribe")))
                 or request.method == "DELETE")
        if gated:
            return JSONResponse(
                {"error": "solo disponible desde el equipo anfitrión"},
                status_code=403)
    return await call_next(request)


CON = db.connect(config.DB_PATH)
try:
    db.backup_daily(CON, config.APP_DIR)
except Exception:
    pass
STATIC = Path(__file__).resolve().parent.parent / "static"
_DICTS: dict = {}   # bidix por idioma



def _dict():
    code = languages.active_code()
    if code not in _DICTS:
        try:
            _DICTS[code] = dictionary.load()
        except Exception:
            _DICTS[code] = dictionary.Dictionary({})
    return _DICTS[code]


def _senses(selection: str, lemma: str, d=None) -> list[tuple[str, str]]:
    """Acepciones del bidix: lema primero (palabra única) para que un
    homógrafo superficial (p. ej. el acrónimo ETS) no tape al lema."""
    d = d or _dict()
    if " " in selection.strip():
        return d.lookup(selection) or d.lookup(lemma)
    return d.lookup(lemma) or d.lookup(selection)


def _active_sense(senses, sentence_es: str, word_es: str) -> int:
    """WSD ligero: la acepción cuya 1.ª palabra aparece en la traducción
    de la frase (o coincide con word_es) se preselecciona en el popup."""
    if not senses:
        return -1
    import re
    words = set(re.findall(r"[^\W\d_]+", sentence_es.lower(), re.UNICODE))
    for i, (es, _p) in enumerate(senses):
        head = (es.lower().split() or [""])[0]
        if head and (head in words or
                     (len(head) >= 5 and
                      any(w.startswith(head[:-1]) for w in words))):
            return i
    wl = word_es.strip().lower()
    if wl:
        for i, (es, _p) in enumerate(senses):
            if es.strip().lower() == wl:
                return i
    return 0


def _word_es(selection: str, lemma: str) -> str:
    """Traducción de la palabra conservando conjugación: si 'Ets' no es
    nombre propio se traduce 'ets' -> 'eres'; si aun así no cambia, cae
    al lema."""
    w = selection
    if not forms.known_exact(w) and forms.knows_lower(w):
        w = w.lower()
    out = translate.translate(w)
    if (out.strip().lower() == selection.strip().lower()
            and lemma and lemma != w.lower()):
        alt = translate.translate(lemma)
        if alt:
            out = alt
    return out


def _segment_es(sid: str, idx: int) -> str:
    """text_es cacheado del segmento (lo crea si falta).

    La traducción (lenta) corre fuera del lock; la escritura relee el
    transcript dentro para no pisar traducciones concurrentes ni resucitar
    un transcript viejo si una retranscripción se cruzó por medio."""
    s = db.get_session(CON, sid)
    if not s:
        return ""
    segs = json.loads(s["transcript_json"])
    if not 0 <= idx < len(segs):
        return ""
    base = languages.base_code()
    # el caché guarda en qué idioma base se tradujo ("es" si no está marcado,
    # que es lo que eran las traducciones históricas); otra base lo invalida
    if segs[idx].get("text_es") and segs[idx].get("es_b", "es") == base:
        return segs[idx]["text_es"]
    es = translate.sentence(segs[idx]["text"])
    with db.LOCK:
        s2 = db.get_session(CON, sid)
        if not s2:
            return es
        segs2 = json.loads(s2["transcript_json"])
        if (not 0 <= idx < len(segs2)
                or segs2[idx].get("text") != segs[idx]["text"]):
            return es                      # retranscrito entre medias: no pisar
        if not segs2[idx].get("text_es") or segs2[idx].get("es_b", "es") != base:
            segs2[idx]["text_es"] = es
            segs2[idx]["es_b"] = base
            db.update_transcript(CON, sid, json.dumps(segs2), s2["model_size"],
                                 s2["srt_source"], s2.get("tok_version") or 0)
    return es


DEFAULT_SETTINGS = {
    "deck": "LinguaMiner::Mining", "anki_port": None, "language": "ca",
    "sub_scale": 1.0, "dual_default": False, "autopause_default": False,
    "speed_default": 1.0, "ipa_enabled": True, "online_enabled": False,
    # "auto" = el navegador decide (i18n.js); quien ya tenga un idioma guardado
    # lo conserva, esto solo afecta a instalaciones nuevas
    # "auto" = el navegador decide (i18n.js); quien ya tenga un idioma guardado
    # lo conserva, esto solo afecta a instalaciones nuevas
    "audio_trim": False, "ui_lang": "auto", "base_language": "auto",
    # zipf mínimo para recomendar una palabra (0-7). Solo se recomiendan
    # palabras frecuentes y que no sean nombres propios (nivel de vocabulario).
    "rec_min_zipf": 3.5,
    # al pasar de página en el lector, ¿las palabras que quedaron sin tocar
    # pasan a conocidas? Apagado: se activa a mano y siempre se puede deshacer.
    "reader_mark_known": False,
    "keymap": {"prev": "a", "next": "d", "replay": "s", "mine": "q",
               "subs": "w", "browser": "g", "copy": "c", "dual": "e",
               "autopause": "p", "fullscreen": "f", "recommended": "r"},
}


def _settings() -> dict:
    s = {k: (dict(v) if isinstance(v, dict) else v)
         for k, v in DEFAULT_SETTINGS.items()}
    if config.SETTINGS_PATH.exists():
        saved = json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
        for k, v in saved.items():
            if k == "keymap" and isinstance(v, dict):
                s["keymap"].update(v)
            else:
                s[k] = v
    return s


def _save_settings(s: dict):
    config.SETTINGS_PATH.write_text(json.dumps(s), encoding="utf-8")


def _lang() -> str:
    return languages.active_code()


def _fmt_ts(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ---------- health / setup ----------

@app.get("/api/health")
def health():
    return {"ok": True, "anki": anki.is_up(),
            "translator": translate.is_downloaded(),
            # lo que está degradado ahora mismo: el frontend lo enseña para
            # que el usuario sepa que no es normal y pueda reportarlo
            "degraded": failures.active()}


def _setup_checks() -> dict:
    """Estado de preparación para el asistente de primer arranque."""
    import importlib.util
    import shutil
    prof = languages.profile()
    dl = config.MODELS_DIR
    return {
        "ffmpeg": media.ffmpeg_available(),   # PATH o binario estático descargable
        "espeak": bool(shutil.which("espeak-ng") or shutil.which("espeak")),
        "spacy": importlib.util.find_spec(prof["spacy"]) is not None,
        "translator": translate.is_downloaded(),
        "forms": (dl / "forms.sqlite").exists()
                 or (dl / f"forms-{_lang()}.sqlite").exists(),
        "dictionary": (dl / prof["bidix_file"]).exists(),
        "tts": piper_tts.is_downloaded(),
        "anki": anki.is_up(_settings().get("anki_port")),
    }


@app.get("/api/diagnostics")
def diagnostics_report(request: Request, extra: str = ""):
    """Informe para reportar un problema. NO se envía nada: devuelve el texto
    y la URL de GitHub con el issue redactado, para que el usuario lo lea,
    lo edite si quiere y decida él si lo manda."""
    if not _is_local_client(request):
        return JSONResponse({"error": "solo desde el equipo anfitrión"},
                            status_code=403)
    from . import diagnostics
    return {"report": diagnostics.report(extra),
            "issue_url": diagnostics.issue_url(extra)}


@app.get("/api/setup-status")
def setup_status():
    c = _setup_checks()
    # "listo para minar" = lo esencial (media + traducción); Anki y espeak
    # son deseables pero la app funciona en cola / sin IPA.
    ready = c["ffmpeg"] and c["translator"] and c["dictionary"]
    return {"checks": c, "ready": ready,
            "has_sessions": len(db.list_sessions(CON)) > 0}


@app.post("/api/setup/download")
def setup_download():
    """Pre-descarga traductor + diccionarios (evita la sorpresa del primer uso)."""
    def work(jid):
        import importlib.util
        prof = languages.profile()
        if importlib.util.find_spec(prof["spacy"]) is None:
            jobs.set_progress(jid, 0.05, f"Modelo lingüístico {prof['name']}…")
            try:
                import spacy.cli
                spacy.cli.download(prof["spacy"])
            except (Exception, SystemExit) as e:
                # spacy.cli.download acaba en sys.exit(1) cuando falla la
                # descarga, y SystemExit no es Exception: sin atraparlo, un
                # modelo que no baja se llevaba por delante TODO el job de
                # setup (traductor y diccionarios incluidos)
                _log.warning("modelo spaCy %s no disponible: %s — sigo con el "
                             "tokenizador regex", prof["spacy"], e)
        jobs.set_progress(jid, 0.1, "Descargando el traductor (~1.5 GB)…")
        if not translate.is_downloaded():
            translate.download()
        jobs.set_progress(jid, 0.6, "Diccionario de acepciones…")
        _dict()
        jobs.set_progress(jid, 0.75, "Diccionario de formas (~66 MB)…")
        forms.lookup("hola")          # dispara descarga+build
        jobs.set_progress(jid, 0.9, "Glosas del Wikcionario (~4 MB)…")
        wikdict.lookup("hola")
        jobs.set_progress(jid, 0.95, "Voz neural (Piper, ~20 MB)…")
        try:
            if not piper_tts.is_downloaded():
                piper_tts.download()
        except Exception:
            pass                          # degrada a espeak
        return {"ok": True}

    return {"job_id": jobs.start(work, label="setup")}


# ---------- modo compartir (red local / tailnet) ----------

@app.get("/api/share/status")
def share_status():
    return share.status()


@app.post("/api/share/start")
def share_start():
    return share.start()


@app.post("/api/share/stop")
def share_stop():
    return share.stop()


@app.get("/api/share/qr")
def share_qr(url: str):
    return Response(share.qr_svg(url), media_type="image/svg+xml")


# caché de stats de la home: releer todas las transcripciones en cada
# carga hacía la biblioteca cada vez más lenta. Se invalida al cambiar
# la transcripción (updated_at) o cualquier estado de palabra (ws_version).
_META_CACHE: dict = {}


def _ws_version() -> str:
    r = CON.execute(
        "SELECT MAX(updated_at), COUNT(*) FROM word_status").fetchone()
    return f"{r[0] or ''}|{r[1]}"


def _session_meta(row: dict, statuses: dict, wsv: str) -> dict:
    """Thumbnail (lazy) + comprehension stats for the home cards."""
    sid = row["id"]
    thumb = config.MEDIA_DIR / f"thumb-{sid}.jpg"
    failed = config.MEDIA_DIR / f"thumb-{sid}.failed"
    if not thumb.exists() and not failed.exists():
        full = db.get_session(CON, sid)
        try:
            media.snapshot(full["media_path"],
                           max(1.0, (full["duration_secs"] or 10) * 0.12),
                           str(thumb))
        except Exception:
            # URL muerta/lenta: marcar para no reintentar en cada carga
            failed.touch()
    row["thumb"] = f"/media/thumb-{sid}.jpg" if thumb.exists() else None
    key = (id(CON), sid, row.get("updated_at"), wsv)
    cached = _META_CACHE.get(key)
    if cached is None:
        full = db.get_session(CON, sid)
        try:
            segs = json.loads(full["transcript_json"])
        except Exception:
            segs = []
        total = known = 0
        new_lemmas = set()
        for seg in segs:
            for t in seg.get("tokens", []):
                if t.get("is_word") and t.get("lemma"):
                    st = statuses.get(t["lemma"], "unknown")
                    if st == "ignored":
                        continue
                    total += 1
                    if st == "known":
                        known += 1
                    elif st == "unknown":
                        new_lemmas.add(t["lemma"])
        cached = {"comp_pct": round(known / total * 100) if total else None,
                  "new_words": len(new_lemmas) if total else None}
        if len(_META_CACHE) > 500:
            _META_CACHE.clear()
        _META_CACHE[key] = cached
    row.update(cached)
    return row


@app.get("/api/sessions")
def sessions():
    statuses = db.word_statuses(CON, _lang())
    wsv = _ws_version()
    return [_session_meta(r, statuses, wsv)
            for r in db.list_sessions(CON, languages.active_code())]


@app.get("/api/sessions/{sid}")
def session_detail(sid: str):
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    s["transcript"] = json.loads(s.pop("transcript_json"))
    if s["transcript"] and (s.get("tok_version") or 0) < nlp.TOK_VERSION:
        for seg in s["transcript"]:
            seg["tokens"] = nlp.tokenize(seg["text"])
        db.update_transcript(CON, sid, json.dumps(s["transcript"]),
                             s["model_size"], s["srt_source"],
                             nlp.TOK_VERSION)
        s["tok_version"] = nlp.TOK_VERSION
    s["word_statuses"] = db.word_statuses(CON, _lang())
    if s["source_type"] == "url":
        s["media_url"] = s["media_path"]
        s["is_hls"] = ".m3u8" in s["media_path"].lower()   # enlace HLS directo
    elif s["source_type"] == "stream":
        s["media_url"] = ""            # el frontend pide /stream-url (URL fresca)
    else:
        s["media_url"] = "/media-file/" + sid
    return s


@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    """Borra una sesión de la biblioteca: fila + tarjetas + media asociada
    (miniatura y, en local/youtube, el archivo descargado). Acción de
    administración (ver guest_gate): los invitados no pueden borrar."""
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.delete_session(CON, sid)
    # miniatura + su marca de "no reintentar"
    for name in (f"thumb-{sid}.jpg", f"thumb-{sid}.failed"):
        try:
            (config.MEDIA_DIR / name).unlink(missing_ok=True)
        except OSError:
            pass
    # el archivo descargado solo se borra si vive dentro de DL_DIR: nunca
    # tocamos rutas externas (url/stream son URLs; un local podría, en teoría,
    # apuntar fuera). Comparamos rutas resueltas para evitar sorpresas.
    if s["source_type"] in ("local", "youtube"):
        try:
            mp = Path(s["media_path"]).resolve()
            if config.DL_DIR.resolve() in mp.parents and mp.is_file():
                mp.unlink()
        except OSError:
            pass
    return {"ok": True}


@app.get("/media-file/{sid}")
def media_file(sid: str):
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(s["media_path"])


class PosReq(BaseModel):
    pos: float


@app.post("/api/sessions/{sid}/position")
def save_position(sid: str, req: PosReq):
    """Guarda dónde se dejó el video para reanudar la próxima vez."""
    db.set_resume_pos(CON, sid, req.pos)
    return {"ok": True}


def _norm(s: str) -> str:
    """minúsculas sin acentos, para buscar 'cami' y encontrar 'camí'."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                   if unicodedata.category(c) != "Mn")


@app.get("/api/search")
def search(q: str):
    """Busca `q` en los subtítulos de toda la biblioteca del idioma activo.
    Devuelve, por sesión, las líneas que coinciden (con índice y tiempo)."""
    needle = _norm(q).strip()
    if len(needle) < 2:
        return {"results": []}
    results = []
    for s in db.list_sessions(CON, languages.active_code()):
        full = db.get_session(CON, s["id"])
        try:
            segs = json.loads(full["transcript_json"])
        except Exception:
            continue
        hits = []
        for i, seg in enumerate(segs):
            if needle in _norm(seg.get("text", "")):
                hits.append({"index": i, "start": seg.get("start", 0),
                             "text": seg.get("text", "")})
            if len(hits) >= 6:
                break
        if hits:
            results.append({"session_id": s["id"], "title": s["title"],
                            "source_type": s["source_type"], "hits": hits})
        if len(results) >= 40:
            break
    return {"results": results}


@app.post("/api/sessions/text")
async def upload_text(file: UploadFile = File(...)):
    """Importa un libro o artículo (.txt, .epub) como sesión de lectura.

    Reutiliza toda la maquinaria de subtítulos: las frases van al mismo formato
    de segmentos, así que el tokenizado, los estados de palabra, la
    recomendación i+1 y las tarjetas funcionan sin una segunda ruta.
    """
    nombre = Path(file.filename or "texto").name or "texto"
    if not nombre.lower().endswith((".txt", ".epub")):
        return JSONResponse({"error": "solo .txt o .epub"}, status_code=400)
    dest = config.DL_DIR / (uuid.uuid4().hex[:6] + "-" + nombre)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    def work(jid):
        from .transcribe import tokens_for_existing
        jobs.set_progress(jid, 0.2, "Leyendo el texto…")
        crudo = textimport.read_text(dest)
        jobs.set_progress(jid, 0.45, "Partiendo en frases…")
        segs = textimport.to_segments(crudo)
        if not segs:
            raise ValueError("el archivo no tiene texto legible")
        jobs.set_progress(jid, 0.7, f"Analizando {len(segs)} frases…")
        sid = db.create_session(
            CON, language=languages.active_code(),
            # el nombre real, no el del temporal: dest lleva un prefijo
            # aleatorio para no pisar archivos y salía en la biblioteca
            title=textimport.title_from(dest, crudo, nombre),
            source_type="text", media_path=str(dest), srt_source="text",
            model_size="-", duration_secs=float(len(segs)),
            transcript_json=json.dumps(tokens_for_existing(segs)))
        return {"session_id": sid, "sentences": len(segs)}

    return {"job_id": jobs.start(work, label="text")}


@app.post("/api/sessions/upload")
async def upload(file: UploadFile = File(...)):
    """Guarda el archivo y delega remux+análisis a un job con progreso
    (los .mkv grandes tardan minutos: sin job parecía colgado)."""
    safe_name = Path(file.filename or "video").name or "video"
    dest = config.DL_DIR / (uuid.uuid4().hex[:6] + "-" + safe_name)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    fname = safe_name

    def work(jid):
        jobs.set_progress(jid, 0.3, "Convirtiendo el video si hace falta…")
        playable = media.ensure_browser_playable(dest, config.DL_DIR)
        jobs.set_progress(jid, 0.8, "Analizando el video…")
        sid = db.create_session(
            CON, language=languages.active_code(), title=fname, source_type="local",
            media_path=str(playable), srt_source="none", model_size="-",
            duration_secs=media.duration(str(playable)),
            transcript_json="[]")
        sidecar = _find_sidecar_subs(dest)
        return {"session_id": sid, "has_sidecar_subs": bool(sidecar)}

    return {"job_id": jobs.start(work, label="upload")}


class UrlReq(BaseModel):
    url: str


@app.post("/api/sessions/url")
def url_session(req: UrlReq):
    """Video online por enlace directo (.mp4/.m3u8): streaming sin descarga.
    ffmpeg corta audio/fotograma de las tarjetas leyendo la misma URL."""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "la URL debe empezar por http(s)://"},
                            status_code=400)

    def work(jid):
        jobs.set_progress(jid, 0.3, "Comprobando el enlace…")
        dur = media.duration(url)
        if dur <= 0:
            raise ValueError(
                "Ese enlace no es un video directo (parece una página web). "
                "«Ver online» solo sirve para enlaces .mp4/.m3u8. Para sitios "
                "como YouTube o 3cat, usa el botón ⬇️ Importar.")
        title = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or url
        sid = db.create_session(
            CON, language=languages.active_code(),
            title=title, source_type="url", media_path=url,
            srt_source="none", model_size="-", duration_secs=dur,
            transcript_json="[]")
        return {"session_id": sid}

    return {"job_id": jobs.start(work, label="url")}


def _stream_subs_transcript(r: dict) -> tuple[str, str]:
    """Descarga y tokeniza los subtítulos catalanes de un stream resuelto.
    Devuelve (transcript_json, srt_source). '' si no hay."""
    if not r.get("subs_url"):
        return "[]", "none"
    try:
        import requests

        from .transcribe import tokens_for_existing
        vtt = requests.get(r["subs_url"], timeout=20).text
        segs = subs.parse_subtitles(vtt)
        if r.get("subs_auto"):
            segs = subs.clean_auto(segs)
        if not segs:
            return "[]", "none"
        kind = "youtube_auto" if r.get("subs_auto") else "youtube_subs"
        return json.dumps(tokens_for_existing(segs)), kind
    except Exception as e:
        failures.warn_once("stream-subs",
                           "no pude traer los subtítulos del propio vídeo; "
                           "habrá que transcribir con Whisper", e)
        return "[]", "none"


@app.post("/api/sessions/stream")
def stream_session(req: UrlReq):
    """«Ver online» inteligente: YouTube/3cat/directo → streaming sin descarga.
    Resuelve la URL reproducible con yt-dlp y crea la sesión."""
    url = req.url.strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "la URL debe empezar por http(s)://"},
                            status_code=400)

    def work(jid):
        jobs.set_progress(jid, 0.3, "Resolviendo el enlace…")
        # enlace directo a un archivo → sesión url normal (streaming directo)
        if stream.is_direct(url):
            dur = media.duration(url)
            if dur <= 0:
                raise ValueError("no se pudo leer ese enlace directo de video")
            title = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or url
            sid = db.create_session(
                CON, language=languages.active_code(),
                title=title, source_type="url", media_path=url,
                srt_source="none", model_size="-", duration_secs=dur,
                transcript_json="[]")
            return {"session_id": sid}
        # sitio soportado (YouTube, 3cat…) → resolver stream progresivo
        r = stream.resolve(url)
        if not r:
            raise ValueError(
                "No pude extraer un vídeo de esa página. yt-dlp no soporta ese "
                "sitio (o el vídeo está protegido). Prueba con YouTube/3cat, o "
                "pega el enlace directo al archivo (.mp4) o al manifiesto (.m3u8).")
        jobs.set_progress(jid, 0.7, "Cargando subtítulos…")
        transcript, srt_source = _stream_subs_transcript(r)
        sid = db.create_session(
            CON, language=languages.active_code(), title=r["title"], source_type="stream",
            media_path=r["best_url"], srt_source=srt_source, model_size="-",
            duration_secs=r["duration"], transcript_json=transcript,
            page_url=url, stream_height=r["best_height"])
        return {"session_id": sid}

    return {"job_id": jobs.start(work, label="stream")}


@app.get("/api/sessions/{sid}/stream-url")
def session_stream_url(sid: str, height: int = 0):
    """URL fresca de stream (las de yt-dlp caducan) + alturas disponibles."""
    s = db.get_session(CON, sid)
    if not s or s["source_type"] != "stream":
        return JSONResponse({"error": "no es una sesión de streaming"},
                            status_code=400)
    url, heights, is_hls = stream.stream_url(s["page_url"],
                                             height or s["stream_height"])
    if not url:
        return JSONResponse(
            {"error": "el enlace ya no está disponible o cambió"},
            status_code=502)
    if height and height != s["stream_height"]:
        db.set_stream_height(CON, sid, height)
    return {"url": url, "height": height or s["stream_height"],
            "heights": heights, "is_hls": is_hls}


def _find_sidecar_subs(path: Path) -> Path | None:
    for ext in (".srt", ".vtt", ".ca.srt", ".ca.vtt"):
        p = path.with_suffix(ext)
        if p.exists():
            return p
    return None


class YoutubeReq(BaseModel):
    url: str


@app.post("/api/sessions/youtube")
def youtube_import(req: YoutubeReq):
    from . import youtube

    def work(jid):
        info = youtube.download(jid, req.url)
        playable = media.ensure_browser_playable(
            Path(info["media_path"]), config.DL_DIR)
        sid = db.create_session(
            CON, language=languages.active_code(), title=info["title"], source_type="youtube",
            media_path=str(playable), srt_source="none", model_size="-",
            duration_secs=info["duration"], transcript_json="[]")
        if info["subtitles"]:
            from .transcribe import tokens_for_existing
            segs = subs.parse_subtitles(
                Path(info["subtitles"]).read_text(encoding="utf-8",
                                                  errors="replace"))
            kind = info.get("subs_kind", "youtube_subs")
            if kind == "youtube_auto":
                segs = subs.clean_auto(segs)
            db.update_transcript(CON, sid,
                                 json.dumps(tokens_for_existing(segs)),
                                 "-", kind, nlp.TOK_VERSION)
        return {"session_id": sid}

    return {"job_id": jobs.start(work, label="youtube")}


class TranscribeReq(BaseModel):
    model: str = config.DEFAULT_WHISPER
    use_sidecar: bool = False


@app.post("/api/sessions/{sid}/transcribe")
def do_transcribe(sid: str, req: TranscribeReq):
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not req.use_sidecar and req.model not in languages.profile()["whisper_models"]:
        return JSONResponse(
            {"error": f"modelo «{req.model}» no disponible para este idioma"},
            status_code=400)

    # ya hay una transcripción en curso para esta sesión: devolver esa misma en
    # vez de lanzar otro Whisper (dos modelos a la vez se pelean por la CPU y
    # todo parece colgado — pasaba al pulsar el botón varias veces)
    label = f"transcribe:{sid}"
    running = jobs.running_with_label(label)
    if running:
        return {"job_id": running, "already_running": True}

    def work(jid):
        from . import transcribe as T
        sidecar = _find_sidecar_subs(Path(s["media_path"]))
        if req.use_sidecar and sidecar:
            segs = T.tokens_for_existing(
                subs.parse_subtitles(
                    sidecar.read_text(encoding="utf-8", errors="replace")))
            db.update_transcript(CON, sid, json.dumps(segs), "-", "srt",
                                 nlp.TOK_VERSION)
        else:
            segs = T.transcribe(jid, s["media_path"], req.model,
                                s["duration_secs"] or 0)
            db.update_transcript(CON, sid, json.dumps(segs), req.model,
                                 "whisper", nlp.TOK_VERSION)
        return {"segments": len(segs)}

    return {"job_id": jobs.start(work, label=label)}


@app.post("/api/sessions/{sid}/condensed")
def do_condensed(sid: str):
    """Audio condensado (solo diálogo) para escucha pasiva — el mp3 queda en
    la biblioteca de medios y se descarga desde el navegador."""
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    segs = json.loads(s["transcript_json"] or "[]")
    if not segs:
        return JSONResponse({"error": "transcribe primero esta sesión"},
                            status_code=400)

    def work(jid):
        jobs.set_progress(jid, 0.05, "Preparando audio condensado…")
        src = s["media_path"]
        if s.get("source_type") == "stream" and s.get("page_url"):
            fresh, _, _ = stream.stream_url(s["page_url"],
                                            s.get("stream_height") or 0)
            if fresh:
                src = fresh
        ranges = [(g["start"], g["end"]) for g in segs
                  if g.get("end", 0) > g.get("start", 0)]
        name = f"condensed-{sid}.mp3"
        jobs.set_progress(jid, 0.15, "Extrayendo el diálogo (puede tardar)…")
        dur = media.condensed_audio(src, ranges,
                                    str(config.MEDIA_DIR / name))
        jobs.set_progress(jid, 1.0, "Listo")
        return {"file": f"/media/{name}", "name": name,
                "seconds": round(dur), "total": round(s["duration_secs"] or 0)}

    return {"job_id": jobs.start(work, label="condensed")}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    j = jobs.get(jid)
    if j is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return j


@app.post("/api/sessions/{sid}/subtitles")
async def attach_subtitles(sid: str, file: UploadFile = File(...)):
    """User-provided .srt/.vtt — replaces the transcript, no Whisper needed."""
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    from .transcribe import tokens_for_existing
    text = (await file.read()).decode("utf-8", errors="replace")
    segs = tokens_for_existing(subs.parse_subtitles(text))
    if not segs:
        return JSONResponse({"error": "no s'han trobat subtítols al fitxer"},
                            status_code=400)
    db.update_transcript(CON, sid, json.dumps(segs), "-", "srt",
                         nlp.TOK_VERSION)
    return {"segments": len(segs)}


# ---------- word statuses (Migaku-style) ----------

class WordStatusReq(BaseModel):
    lemma: str
    status: str


@app.post("/api/words/status")
def set_word_status(req: WordStatusReq):
    if req.status not in db.WORD_STATUSES:
        return JSONResponse({"error": "bad status"}, status_code=400)
    db.set_word_status(CON, req.lemma, req.status, _lang())
    return {"ok": True, "lemma": req.lemma.strip().lower(),
            "status": req.status}


@app.post("/api/anki/sync-statuses")
def sync_statuses():
    """Migaku-style: Anki interval >= 21 days -> known, else learning."""
    if not anki.is_up(_settings().get("anki_port")):
        return {"synced": 0}
    try:
        anki.ensure_note_type()  # keeps card template in sync with app version
    except Exception:
        pass
    pairs = db.cards_with_notes(CON, _lang())
    intervals = anki.note_intervals([p["anki_note_id"] for p in pairs])
    statuses = db.word_statuses(CON, _lang())
    n = 0
    for p in pairs:
        iv = intervals.get(p["anki_note_id"])
        if iv is None:
            continue
        target = "known" if iv >= 21 else "learning"
        current = statuses.get(p["lema"])
        if current in ("ignored",):
            continue
        if current != target:
            db.set_word_status(CON, p["lema"], target, _lang())
            n += 1
    return {"synced": n}


# ---------- dictionary popup ----------

class LookupReq(BaseModel):
    selection: str
    sentence: str = ""
    session_id: str = ""
    segment_index: int = -1


@app.post("/api/lookup")
def lookup(req: LookupReq):
    """Instant word info for the Migaku-style popup (no media generated)."""
    lemma, pos = nlp.analyze_selection(req.selection, req.sentence)
    z = nlp.zipf(req.selection)
    es_src = languages.spanish_sources_active()   # bidix/glosas son fuentes es
    senses = _senses(req.selection, lemma) if es_src else []
    word_es = _word_es(req.selection, lemma)
    sentence_es = ""
    if req.session_id and req.segment_index >= 0:
        sentence_es = _segment_es(req.session_id, req.segment_index)
    if not sentence_es and req.sentence:
        sentence_es = translate.sentence(req.sentence)
    # las glosas ya no dependen del español: wikdict elige el extracto del
    # Wikcionario que toque según la base activa (es o en)
    glosses = wikdict.lookup(lemma) or wikdict.lookup(req.selection)
    userdefs = userdict.lookup(lemma) or userdict.lookup(req.selection)
    return {
        "selection": req.selection,
        "lemma": lemma, "pos": pos,
        "zipf": z, "freq_rank": nlp.freq_badge(z),
        "senses": [{"es": es, "pos": p} for es, p in senses[:8]],
        "active": _active_sense(senses[:8], sentence_es, word_es),
        "glosses": [{"es": g, "pos": p} for g, p in glosses[:4]],
        "userdefs": [{"text": d, "source": s} for d, s in userdefs[:4]],
        "word_es": word_es,
        "sentence_es": sentence_es,
        "ipa": ipa.ipa(req.selection),
        "tts": piper_tts.available(),
    }


class UserDictReq(BaseModel):
    path: str = ""
    slug: str = ""


@app.get("/api/userdict/list")
def userdict_list():
    return {"dicts": userdict.list_dicts()}


@app.post("/api/userdict/import")
def userdict_import(req: UserDictReq):
    p = Path(req.path.strip()).expanduser()
    if not p.exists():
        return JSONResponse({"error": "no encuentro ese archivo"}, status_code=400)
    try:
        info = userdict.import_file(str(p))
    except Exception as e:
        return JSONResponse({"error": f"no se pudo importar: {e}"}, status_code=400)
    return {"ok": True, **info, "dicts": userdict.list_dicts()}


@app.post("/api/userdict/remove")
def userdict_remove(req: UserDictReq):
    userdict.remove(req.slug)
    return {"ok": True, "dicts": userdict.list_dicts()}


@app.get("/api/conjugation")
def conjugation_table(lemma: str):
    """Tabla de conjugación del verbo (del diccionario de formas, offline).
    {} si no hay formas (idioma sin diccionario o no es verbo conocido)."""
    from . import conjugation
    return conjugation.table(lemma)


@app.post("/api/sessions/{sid}/segments/{idx}/translate")
def translate_segment(sid: str, idx: int):
    """Dual-subtitle line (Language Reactor style), cached in the transcript."""
    s = db.get_session(CON, sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    segs = json.loads(s["transcript_json"])
    if not 0 <= idx < len(segs):
        return JSONResponse({"error": "bad index"}, status_code=400)
    return {"index": idx, "text_es": _segment_es(sid, idx)}


# ---------- cards ----------

class PreviewReq(BaseModel):
    session_id: str
    segment_index: int
    selection: str
    pad_before: int = 0   # extend audio N segments back
    pad_after: int = 0
    offset: float = 0.0   # desfase subtítulo↔media en segundos (srt desajustado)


def _build_preview(s: dict, segment_index: int, selection: str,
                   pad_before: int = 0, pad_after: int = 0,
                   offset: float = 0.0) -> dict:
    segs = json.loads(s["transcript_json"])
    seg = segs[segment_index]

    # Un libro no tiene de dónde cortar audio ni sacar un fotograma: sin esta
    # rama se lanzaban tres ffmpeg contra un .txt, fallaban los tres y la
    # tarjeta salía muda. La voz la pone Piper, que ya está para pronunciar.
    if s.get("source_type") == "text":
        return _text_preview(s, segs, segment_index, selection, pad_before, pad_after)

    start = max(0.0, segs[max(0, segment_index - pad_before)]["start"] + offset)
    end = max(0.0, segs[min(len(segs) - 1, segment_index + pad_after)]["end"] + offset)
    mid = max(0.0, (seg["start"] + seg["end"]) / 2 + offset)

    # los streams tienen URL caducable: re-resolver una fresca para ffmpeg
    src = s["media_path"]
    if s.get("source_type") == "stream" and s.get("page_url"):
        fresh, _, _ = stream.stream_url(s["page_url"], s.get("stream_height") or 0)
        if fresh:
            src = fresh

    base = uuid.uuid4().hex[:10]
    audio_name, image_name = f"cm-{base}.mp3", f"cm-{base}.jpg"
    clip_name = f"cm-{base}.gif"
    MAX_GIF = 6.0

    # Streams: descargar UNA ventana local y sacar de ahí captura + GIF. Sin
    # esto el GIF decodificaba varios segundos de HD desde el stream (minutos)
    # y agotaba el timeout → la tarjeta caía a solo-imagen «en algunos momentos».
    win_path = None
    if s.get("source_type") == "stream":
        win_dur = min(max(0.1, end - start), MAX_GIF) + 0.5
        wp = config.MEDIA_DIR / f"cm-{base}-win.mp4"
        try:
            media.download_window(src, start, win_dur, str(wp))
            win_path = str(wp)
        except Exception as e:
            _log.warning("ventana de stream falló (%s); intento directo", e)

    video_src = win_path or src
    # en la ventana los tiempos son relativos (empieza en 0); directo usa originales
    win_content = min(max(0.1, end - start), MAX_GIF)
    snap_ts = min(max(0.0, mid - start), win_content - 0.1) if win_path else mid
    gif_start, gif_end = (0.0, win_content) if win_path else (start, end)

    audio_ok = image_ok = clip_ok = True
    try:
        media.cut_audio(src, start, end,
                        str(config.MEDIA_DIR / audio_name),
                        trim=bool(_settings().get("audio_trim")))
    except Exception as e:
        _log.warning("audio de tarjeta falló: %s", e)
        audio_ok = False
    try:
        media.snapshot(video_src, snap_ts, str(config.MEDIA_DIR / image_name))
    except Exception as e:
        _log.warning("captura de tarjeta falló: %s", e)
        image_ok = False
    try:
        # animated clip only makes sense for video sources
        if image_ok:
            media.animated_clip(video_src, gif_start, gif_end,
                                str(config.MEDIA_DIR / clip_name),
                                timeout=(60 if win_path else 90))
        else:
            clip_ok = False
    except Exception as e:
        _log.warning("GIF de tarjeta falló: %s", e)
        clip_ok = False
    finally:
        if win_path:
            try:
                Path(win_path).unlink(missing_ok=True)
            except OSError:
                pass

    lemma, pos = nlp.analyze_selection(selection, seg["text"])
    z = nlp.zipf(selection)
    senses = _senses(selection, lemma) if languages.spanish_sources_active() else []
    frase_es = translate.sentence(seg["text"])
    word_es = _word_es(selection, lemma)
    return {
        "paraula": selection,
        "lema": lemma, "pos": pos,
        "paraula_es": word_es,
        "senses": [{"es": es, "pos": p} for es, p in senses[:8]],
        "active": _active_sense(senses[:8], frase_es, word_es),
        "frase": seg["text"],
        "frase_es": frase_es,
        "freq_zipf": z, "freq_rank": nlp.freq_badge(z),
        "audio_file": audio_name if audio_ok else "",
        "image_file": image_name if image_ok else "",
        "clip_file": clip_name if clip_ok else "",
        "font": f"{s['title']} @ {_fmt_ts(seg['start'])}",
    }


def _text_preview(s: dict, segs: list, idx: int, selection: str,
                  pad_before: int = 0, pad_after: int = 0) -> dict:
    """Tarjeta desde un libro: frase, traducción y voz neural. Sin imagen.

    Los ⏪+ / +⏩ del editor siguen valiendo — amplían la frase con la anterior
    o la siguiente, que es lo mismo que hacen en vídeo con el audio.
    """
    desde = max(0, idx - pad_before)
    hasta = min(len(segs) - 1, idx + pad_after)
    frase = " ".join(x["text"] for x in segs[desde:hasta + 1])

    audio_name = ""
    try:
        audio_name = piper_tts.speak(frase)
    except Exception as e:                              # noqa: BLE001
        failures.warn_once("text-tts", "sin voz para las tarjetas de texto", e)

    lemma, pos = nlp.analyze_selection(selection, frase)
    z = nlp.zipf(selection)
    senses = _senses(selection, lemma) if languages.spanish_sources_active() else []
    frase_es = translate.sentence(frase)
    word_es = _word_es(selection, lemma)
    return {
        "paraula": selection,
        "lema": lemma, "pos": pos,
        "paraula_es": word_es,
        "senses": [{"es": es, "pos": p} for es, p in senses[:8]],
        "active": _active_sense(senses[:8], frase_es, word_es),
        "frase": frase,
        "frase_es": frase_es,
        "freq_zipf": z, "freq_rank": nlp.freq_badge(z),
        "audio_file": audio_name,
        "image_file": "",
        "clip_file": "",
        # en un libro el "@ 07:16" no significa nada: va el número de frase
        "font": f"{s['title']} · {idx + 1}/{len(segs)}",
    }


def _bad_index(s: dict, idx: int):
    n = len(json.loads(s["transcript_json"]))
    if not 0 <= idx < n:
        return JSONResponse({"error": f"segment_index fuera de rango (0-{n-1})"},
                            status_code=400)
    return None


@app.post("/api/cards/preview")
def card_preview(req: PreviewReq):
    s = db.get_session(CON, req.session_id)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    bad = _bad_index(s, req.segment_index)
    if bad:
        return bad
    return _build_preview(s, req.segment_index, req.selection,
                          req.pad_before, req.pad_after, req.offset)


class MineReq(BaseModel):
    session_id: str
    segment_index: int
    selection: str
    paraula_es: str = ""
    offset: float = 0.0


@app.post("/api/cards/mine")
def card_mine(req: MineReq):
    """Minado one-shot: preview + alta + envío a Anki, sin panel."""
    s = db.get_session(CON, req.session_id)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    bad = _bad_index(s, req.segment_index)
    if bad:
        return bad
    p = _build_preview(s, req.segment_index, req.selection, offset=req.offset)
    active_es = (p["senses"][p["active"]]["es"]
                 if p["senses"] and p["active"] >= 0 else "")
    paraula_es = req.paraula_es or p["paraula_es"] or active_es
    cid = db.create_card(
        CON, session_id=req.session_id, segment_index=req.segment_index,
        paraula=p["paraula"], lema=p["lema"], pos=p["pos"],
        paraula_es=paraula_es, frase=p["frase"], frase_es=p["frase_es"],
        freq_rank=p["freq_rank"], audio_file=p["audio_file"],
        image_file=p["clip_file"] or p["image_file"], font=p["font"],
        language=_lang())
    if p["lema"]:
        db.mark_learning_if_new(CON, p["lema"], _lang())
    sent = _flush()
    return {"card_id": cid, "sent_now": sent > 0,
            "pending": len(db.pending_cards(CON)),
            "word_status": db.word_statuses(CON, _lang()).get(p["lema"]),
            "lema": p["lema"], "paraula": p["paraula"]}


class CardReq(BaseModel):
    session_id: str
    segment_index: int
    paraula: str
    lema: str
    pos: str = ""
    paraula_es: str = ""
    frase: str
    frase_es: str = ""
    freq_rank: str = ""
    audio_file: str = ""
    image_file: str = ""
    font: str = ""


@app.post("/api/cards")
def create_card(req: CardReq):
    cid = db.create_card(CON, session_id=req.session_id,
                         segment_index=req.segment_index, paraula=req.paraula,
                         lema=req.lema, pos=req.pos, paraula_es=req.paraula_es,
                         frase=req.frase, frase_es=req.frase_es,
                         freq_rank=req.freq_rank, audio_file=req.audio_file,
                         image_file=req.image_file, font=req.font,
                         language=_lang())
    if req.lema:
        db.mark_learning_if_new(CON, req.lema, _lang())
    sent = _flush()
    return {"card_id": cid, "sent_now": sent,
            "pending": len(db.pending_cards(CON)),
            "word_status": db.word_statuses(CON, _lang()).get(req.lema.strip().lower())}


_FLUSH_LOCK = threading.Lock()


def _flush() -> int:
    if not _FLUSH_LOCK.acquire(blocking=False):
        return 0                          # ya hay un flush en marcha
    try:
        return _flush_locked()
    finally:
        _FLUSH_LOCK.release()


def _flush_locked() -> int:
    if not anki.is_up(_settings().get("anki_port")):
        return 0
    deck = _settings()["deck"]
    n = 0
    for card in db.pending_cards(CON):
        try:
            note_id = anki.send_card(card, deck)
            db.mark_card_sent(CON, card["id"], note_id)
            n += 1
        except anki.AnkiError as e:
            if "duplicate" in str(e).lower():
                db.mark_card_duplicate(CON, card["id"])
                continue
            break
        except Exception:
            break
    return n


@app.post("/api/anki/flush")
def anki_flush():
    return {"sent": _flush(), "pending": len(db.pending_cards(CON))}


@app.get("/api/anki/status")
def anki_status():
    port, diag = anki.find_port(_settings().get("anki_port"))
    up = port is not None
    if up:
        reason = "ok"
    elif any(v == "squatted" for v in diag.values()):
        reason = "squatted"
    else:
        reason = "down"
    decks = anki.invoke("deckNames") if up else []
    return {"up": up, "port": port, "reason": reason, "diag": diag,
            "decks": decks, "deck": _settings()["deck"],
            "pending": len(db.pending_cards(CON))}


# ---------- vocabulario (Language Reactor) ----------

@app.get("/api/vocab/ranks")
def vocab_ranks():
    return {"ranks": vocab.ranks()}


class BulkKnownReq(BaseModel):
    top_n: int


@app.post("/api/words/bulk-known")
def words_bulk_known(req: BulkKnownReq):
    n = max(0, min(5000, req.top_n))
    return {"marked": vocab.bulk_known(CON, n, _lang())}


class PageKnownReq(BaseModel):
    lemmas: list[str]
    undo: bool = False


@app.post("/api/words/page-known")
def words_page_known(req: PageKnownReq):
    """Al pasar de página, lo que quedó sin tocar pasa a conocido.

    Es la mecánica central de LingQ, con dos diferencias: no toca ningún
    estado que hayas puesto tú, y devuelve la lista exacta de lo que cambió.
    Sin esa lista no hay deshacer, y sin deshacer el recuento deja de ser de
    fiar — que es la queja de siempre con el contador de LingQ.
    """
    actuales = db.word_statuses(CON, _lang())
    hechas = []
    for bruto in req.lemmas[:2000]:
        lm = str(bruto).strip().lower()
        if not lm:
            continue
        if req.undo:
            if actuales.get(lm) != "known":
                continue          # la cambiaste después: no es nuestra
            db.set_word_status(CON, lm, "unknown", _lang())
            actuales.pop(lm, None)
        else:
            if lm in actuales:
                continue          # ya tenía estado tuyo
            db.set_word_status(CON, lm, "known", _lang())
            actuales[lm] = "known"
        hechas.append(lm)
    return {"marked": len(hechas), "lemmas": hechas}


@app.get("/api/anki/decks")
def anki_decks():
    """Mazos disponibles, para sembrar vocabulario desde los que ya estudias."""
    try:
        return {"decks": anki.deck_names()}
    except Exception:
        return {"decks": [], "error": "Anki no está abierto"}


class SeedReq(BaseModel):
    deck: str


@app.post("/api/words/seed-anki")
def words_seed_anki(req: SeedReq):
    if not req.deck or req.deck not in (anki.deck_names() or []):
        return JSONResponse({"error": "mazo desconocido"}, status_code=400)

    def work(jid):
        jobs.set_progress(jid, 0.2, "Leyendo el mazo…")
        try:
            r = vocab.seed_from_anki(CON, req.deck, _lang())
        except Exception as e:          # Anki cerrado a mitad, mazo borrado…
            _log.warning("sembrado desde Anki falló: %s", e)
            raise RuntimeError("Anki dejó de responder; ábrelo e inténtalo de nuevo") from e
        jobs.set_progress(jid, 1.0, "Listo")
        return r

    return {"job_id": jobs.start(work, label="seed-anki")}


# ---------- export / import de progreso ----------

@app.get("/api/words/export")
def words_export():
    import time
    return JSONResponse(
        {"version": 1,
         "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "statuses": db.word_statuses(CON, _lang())},
        headers={"Content-Disposition":
                 "attachment; filename=linguaminer-paraules.json"})


@app.post("/api/sessions/sample")
def create_sample():
    """Sesión de ejemplo, generada al vuelo y ya transcrita.

    Un usuario nuevo tiene que buscar contenido y esperar minutos a Whisper
    antes de ver una tarjeta. Esto le da el bucle completo en treinta segundos.
    """
    code = _lang()
    if not sample.available(code):
        return JSONResponse(
            {"error": f"todavía no hay ejemplo para «{code}»"}, status_code=400)
    r = sample.build_safe(code)
    if not r:
        return JSONResponse(
            {"error": "no pude generar el ejemplo (¿falta la voz neural?)"},
            status_code=500)
    from .transcribe import tokens_for_existing
    sid = db.create_session(
        # sin language la sesión nace etiquetada "ca" por defecto y la
        # biblioteca, que filtra por idioma, no la enseña nunca
        CON, language=code,
        title=f"{languages.PROFILES[code]['name']} — sample",
        source_type="local", media_path=r["path"], srt_source="sample",
        model_size="-", duration_secs=r["duration"],
        transcript_json=json.dumps(tokens_for_existing(r["segments"])))
    return {"session_id": sid}


@app.post("/api/words/import-list")
async def words_import_list(file: UploadFile = File(...)):
    """Sembrar vocabulario desde la exportación de otra herramienta.

    Quien viene de Migaku, jpdb o LingQ ya sabe miles de palabras; sin esto el
    primer vídeo le sale rojo entero y la recomendación no le sirve. Acepta
    txt, csv, tsv y json — ver app/wordlist.py sobre por qué es un lector
    tolerante y no un soporte por formato.
    """
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        return JSONResponse({"error": "archivo demasiado grande (máx. 20 MB)"},
                            status_code=400)
    try:
        words = wordlist.parse(raw)
    except Exception as e:                            # noqa: BLE001
        return JSONResponse({"error": f"no pude leer el archivo: {e}"},
                            status_code=400)
    if not words:
        return JSONResponse(
            {"error": "no encontré ninguna palabra en el archivo"},
            status_code=400)
    return vocab.seed_words(CON, words, _lang())


class ImportReq(BaseModel):
    statuses: dict
    overwrite: bool = False


@app.post("/api/words/import")
def words_import(req: ImportReq):
    current = db.word_statuses(CON, _lang())
    imported = skipped = 0
    for lemma, st in req.statuses.items():
        lm = str(lemma).strip().lower()
        if not lm or st not in db.WORD_STATUSES:
            skipped += 1
            continue
        if not req.overwrite and lm in current:
            skipped += 1
            continue
        db.set_word_status(CON, lm, st, _lang())
        imported += 1
    return {"imported": imported, "skipped": skipped}


# ---------- diccionario enriquecido ----------

@app.get("/api/examples")
def get_examples(lemma: str, session_id: str = "", index: int = -1):
    """Frases del propio contenido del usuario donde aparece el lema."""
    return {"examples": examples.find(CON, lemma, limit=4,
                                      exclude_sid=session_id,
                                      exclude_idx=index)}


@app.get("/api/tts")
def get_tts(text: str):
    return {"file": tts.speak(text)}


@app.get("/api/define")
def define(word: str):
    """Extracto del Viccionari (online, opcional). Best-effort: '' si falla."""
    word = (word or "").strip()
    if not word or not _settings().get("online_enabled"):
        return {"text": ""}
    try:
        import requests
        r = requests.get(
            "https://ca.wiktionary.org/w/api.php",
            params={"action": "query", "prop": "extracts",
                    "explaintext": 1, "redirects": 1, "format": "json",
                    "titles": word},
            timeout=6, headers={"User-Agent": "LinguaMiner/0.7"})
        pages = r.json()["query"]["pages"]
        extract = next(iter(pages.values())).get("extract", "")
        # quedarnos con la sección catalana si existe
        if "== Català ==" in extract:
            extract = extract.split("== Català ==", 1)[1]
            for stop in ("\n== ", "\n=="):
                if stop in extract:
                    extract = extract.split(stop, 1)[0]
                    break
        return {"text": extract.strip()[:800]}
    except Exception:
        return {"text": ""}


# ---------- actualización ----------

@app.get("/api/update/check")
def update_check():
    from . import update
    return update.check()


@app.post("/api/update/apply")
def update_apply():
    from . import update
    r = update.apply()
    if "error" not in r:
        r["installer"] = update.installer_hint()
    return r


# ---------- configuración ----------

def _settings_payload() -> dict:
    s = _settings()
    s["languages"] = [{"code": c, "name": p["name"],
                       "available": languages.available(c)}
                      for c, p in languages.PROFILES.items()]
    # modelos Whisper del idioma activo, para que el selector de la UI no
    # ofrezca opciones de otro idioma (p. ej. el modelo catalán AINA en alemán)
    prof = languages.profile()
    s["whisper_models"] = list(prof["whisper_models"].keys())
    s["default_whisper"] = prof["default_whisper"]
    # idiomas base disponibles para el idioma de estudio activo
    s["bases"] = [{"code": b, "name": languages.BASE_NAMES.get(b, b)}
                  for b in languages.bases()]
    s["base_language_effective"] = languages.base_code()
    # fuentes públicas recomendadas del idioma activo (descubrir contenido sin
    # tener que saberse las URLs de memoria)
    s["sources"] = list(prof.get("sources") or [])
    # el botón de «probar con un ejemplo» solo donde hay frases validadas
    s["has_sample"] = sample.available(languages.active_code())
    return s


@app.get("/api/settings")
def get_settings():
    return _settings_payload()


# tipo esperado (y rango numérico) de cada ajuste — antes se aceptaba
# cualquier cosa y acababa interpolada en la query de Anki o en el CSS
_SETTING_TYPES = {
    "deck": str, "anki_port": (int, type(None)), "language": str,
    "sub_scale": (int, float), "dual_default": bool, "autopause_default": bool,
    "speed_default": (int, float), "ipa_enabled": bool, "online_enabled": bool,
    "audio_trim": bool, "ui_lang": str, "keymap": dict,
    "base_language": str, "rec_min_zipf": (int, float),
    "reader_mark_known": bool,
}
_SETTING_RANGES = {"sub_scale": (0.3, 3.0), "speed_default": (0.25, 3.0),
                   "anki_port": (1, 65535), "rec_min_zipf": (0, 7)}


@app.post("/api/settings")
def post_settings(body: dict):
    unknown = set(body) - set(DEFAULT_SETTINGS)
    if unknown:
        return JSONResponse({"error": f"claves desconocidas: {sorted(unknown)}"},
                            status_code=400)
    for k, v in body.items():
        want = _SETTING_TYPES[k]
        wants = want if isinstance(want, tuple) else (want,)
        # ojo: bool es subclase de int — un true donde va un número no cuela
        if (isinstance(v, bool) and bool not in wants) or not isinstance(v, wants):
            return JSONResponse({"error": f"tipo inválido para {k}"},
                                status_code=400)
        lo_hi = _SETTING_RANGES.get(k)
        if lo_hi and v is not None and not lo_hi[0] <= v <= lo_hi[1]:
            return JSONResponse({"error": f"{k} fuera de rango {lo_hi}"},
                                status_code=400)
    if "ui_lang" in body and body["ui_lang"] not in ("auto", "es", "ca", "en"):
        return JSONResponse({"error": "ui_lang no soportado"}, status_code=400)
    if ("base_language" in body and body["base_language"] != "auto"
            and body["base_language"] not in languages.BASE_NAMES):
        return JSONResponse({"error": "idioma base no soportado"}, status_code=400)
    if "language" in body and body["language"] not in languages.activable():
        return JSONResponse({"error": "idioma no disponible todavía"},
                            status_code=400)
    if "keymap" in body:
        km = {**_settings()["keymap"], **body["keymap"]}
        keys = list(km.values())
        if (set(km) - set(DEFAULT_SETTINGS["keymap"])
                or any(not (isinstance(k, str) and len(k) == 1
                            and k.isalpha()) for k in keys)
                or len(keys) != len(set(keys))):
            return JSONResponse(
                {"error": "atajos inválidos (letras a-z, sin repetir)"},
                status_code=400)
    saved = (json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
             if config.SETTINGS_PATH.exists() else {})
    for k, v in body.items():
        if k == "keymap":
            saved["keymap"] = {**saved.get("keymap", {}), **v}
        else:
            saved[k] = v
    _save_settings(saved)
    return _settings_payload()


class DeckReq(BaseModel):
    deck: str


@app.post("/api/anki/deck")
def set_deck(req: DeckReq):
    s = _settings()
    s["deck"] = req.deck
    _save_settings(s)
    return {"ok": True}


class PortReq(BaseModel):
    port: int | None = None


@app.post("/api/anki/port")
def set_anki_port(req: PortReq):
    s = _settings()
    s["anki_port"] = req.port
    _save_settings(s)
    port, diag = anki.find_port(req.port)
    return {"ok": True, "port": port, "diag": diag}


@app.get("/api/stats")
def stats():
    """Métricas transparentes: minado local + estado real en Anki."""
    rows = CON.execute(
        "SELECT created_at FROM cards ORDER BY created_at").fetchall()
    by_month: dict[str, int] = {}
    for r in rows:
        k = r["created_at"][:7]
        by_month[k] = by_month.get(k, 0) + 1
    status_counts: dict[str, int] = {}
    for v in db.word_statuses(CON, _lang()).values():
        status_counts[v] = status_counts.get(v, 0) + 1
    # crecimiento de palabras conocidas (acumulado por fecha, aprox. por updated_at)
    kdays = CON.execute(
        "SELECT substr(updated_at,1,10) d, COUNT(*) n FROM word_status "
        "WHERE language=? AND status='known' GROUP BY d ORDER BY d", (_lang(),)
    ).fetchall()
    known_over_time, acc = [], 0
    for r in kdays:
        acc += r["n"]
        known_over_time.append({"date": r["d"], "total": acc})
    # actividad de minado por día (últimos 30)
    mday = CON.execute(
        "SELECT substr(created_at,1,10) d, COUNT(*) n FROM cards "
        "GROUP BY d ORDER BY d DESC LIMIT 30").fetchall()
    mined_by_day = [{"date": r["d"], "n": r["n"]} for r in reversed(mday)]
    # racha: días seguidos minando (hoy cuenta; si hoy aún no, desde ayer)
    from datetime import date, timedelta
    days = {r["created_at"][:10] for r in rows}
    d = date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    streak = 0
    while d.isoformat() in days:
        streak += 1
        d -= timedelta(days=1)
    out = {"total_cards": len(rows), "by_month": by_month,
           "status_counts": status_counts, "streak_days": streak,
           "known_over_time": known_over_time, "mined_by_day": mined_by_day,
           "sessions": len(db.list_sessions(CON)), "anki": None}
    if anki.is_up(_settings().get("anki_port")):
        try:
            deck = _settings()["deck"]
            ids = anki.find_cards(f'deck:"{deck}"')
            info = anki.cards_info(ids[:5000])
            reps = sum(c.get("reps", 0) for c in info)
            lapses = sum(c.get("lapses", 0) for c in info)
            out["anki"] = {
                "total": len(ids),
                "mature": sum(1 for c in info
                              if (c.get("interval") or 0) >= 21),
                "retention": round((1 - lapses / reps) * 100, 1) if reps else None,
                "due_today": len(anki.find_cards(f'deck:"{deck}" is:due')),
                "due_7d": len(anki.find_cards(f'deck:"{deck}" prop:due<8')),
                "due_30d": len(anki.find_cards(f'deck:"{deck}" prop:due<31')),
            }
        except Exception:
            pass
    return out


# media (card audio previews) + frontend
app.mount("/media", StaticFiles(directory=str(config.MEDIA_DIR)), name="media")
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
