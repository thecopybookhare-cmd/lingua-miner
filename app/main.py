"""LinguaMiner — FastAPI backend + static frontend."""
import json
import logging
import re
import shutil
import tempfile
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote as url_unquote
from urllib.parse import urlparse

from fastapi import FastAPI, File, Request, UploadFile, WebSocket
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (
    anki,
    ankiproxy,
    asbws,
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
    nouns,
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
    ytdlp,
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

from . import diagnostics  # noqa: E402

diagnostics.install()          # capturar el log aunque no se arranque por el lanzador

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
    "/api/userdict/import", "/api/userdict/upload", "/api/userdict/remove",
    "/api/share/start", "/api/share/stop",
    "/api/settings", "/api/anki/deck", "/api/anki/port",
    "/api/setup/download", "/api/words/import", "/api/words/import-list",
    "/api/sessions/upload", "/api/sessions/youtube", "/api/sessions/stream",
    "/api/sessions/text",
    "/api/sessions/sample",
    "/api/update/apply", "/api/words/seed-anki",
    # el puente de asbplayer llega a tu colección de Anki entera
    "/ankiconnect",
    # crear sesiones y mover el Netflix del anfitrión
    "/api/asbplayer/open", "/api/asbplayer/seek",
}


def _err(key: str, msg: str, code: int = 400, args: tuple | list = ()):
    """Error con clave de traducción además del texto.

    `error` sigue siendo el castellano de siempre (respaldo y logs);
    `error_key`+`error_args` es lo que el navegador traduce. Sin esto, quien
    usa la app en inglés recibía los avisos en español justo cuando algo
    fallaba, que es cuando más falta hace entenderlos.
    """
    return JSONResponse(
        {"error": msg, "error_key": key, "error_args": list(args)},
        status_code=code)


def _is_local_client(request) -> bool:
    if config.TRUST_ALL_CLIENTS:      # Docker: ver config.TRUST_ALL_CLIENTS
        return True
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
        return _err("err.bad_host", "host no permitido", 421)
    if not _is_local_client(request):
        p = request.url.path
        # borrar sesiones es una acción de administración: el único DELETE de
        # la API. Los invitados de la red solo estudian, no tocan la biblioteca.
        gated = ((request.method == "POST"
                  and (p in _ADMIN_POSTS or p.endswith("/transcribe")))
                 or request.method == "DELETE")
        if gated:
            return _err("err.host_only",
                        "solo disponible desde el equipo anfitrión", 403)
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


def _word_info(selection: str, sentence: str) -> dict:
    """Lema (clave del estado), categoría, forma de diccionario y traducción.

    En alemán la forma de diccionario lleva artículo y singular («Handschuhe»
    → «der Handschuh») o es el infinitivo del verbo separable («fängt … an» →
    «anfangen»). Se traduce esa forma y no la palabra suelta: «fängt» a secas
    es «captura», y la tarjeta enseñaba eso."""
    si = nlp.selection_info(selection, sentence)
    lemma, pos = si["lemma"], si["pos"]
    headword, key, word_es = "", lemma, ""
    prof = languages.profile()
    if pos == "NOUN" and prof.get("noun_articles"):
        hw = nouns.headword(selection, lemma)
        if hw:
            headword, key, genus = hw
            word_es = _noun_es(key, genus)
    elif si["separable"] or (pos in ("VERB", "AUX") and prof.get("verb_purpose")):
        # El verbo suelto se traduce mal («weiß» → «Blancos», «diskutiere» →
        # «Discuta»): va en infinitivo, que es además la forma que se estudia
        if si["separable"] or lemma != selection.strip().lower():
            headword = lemma
        word_es = _verb_es(lemma, si["separable"])
    word_es = word_es or _word_es(selection, lemma)
    return {"lemma": lemma, "pos": pos, "headword": headword,
            "gloss_key": key, "word_es": word_es}


def _noun_es(lemma: str, genus: str) -> str:
    """Traducción de un sustantivo en forma de diccionario.

    Suelto, el traductor inventa («Imkerei» → «Apionabos», «Hund» →
    «Perros»); con «der» lo lee como genitivo («der Honig» → «de la miel»).
    Con el indefinido acierta («ein Schlüssel» → «una llave», no «la clave»),
    y se pasa al definido: así dice también el género en español."""
    ind = (languages.profile().get("noun_indefinite") or {}).get(genus)
    out = translate.translate(f"{ind} {lemma}" if ind else lemma).strip().rstrip(".:;,")
    if not ind:
        return _lower1(out)
    swaps = ((("un ", "el "), ("una ", "la ")) if languages.base_code() == "es"
             else (("a ", ""), ("an ", "")))
    for a, b in swaps:
        if out.lower().startswith(a):
            return b + out[len(a):]
    return _lower1(out)


def _strip_lead(out: str, leads: tuple[str, ...]) -> str:
    for a in leads:
        if out.lower().startswith(a):
            return out[len(a):]
    return out


def _verb_es(lemma: str, particle: str = "") -> str:
    """Traducción del infinitivo. Suelto, el traductor lo toma por imperativo
    o por sustantivo («aufstehen» → «Levántate», «fernsehen» → «Televisión»);
    en «um aufzustehen» / «um zu wissen» sale el infinitivo («para
    levantarse», «para saber») y se quita el «para»."""
    prof = languages.profile()
    if particle and lemma.startswith(particle) and prof.get("separable_purpose"):
        phrase = prof["separable_purpose"].format(p=particle, v=lemma[len(particle):])
    elif prof.get("verb_purpose"):
        phrase = prof["verb_purpose"].format(v=lemma)
    else:
        return _lower1(translate.translate(lemma))
    out = translate.translate(phrase).strip().rstrip(".:;,")
    return _lower1(_strip_lead(out, ("para ", "in order to ", "to ")))


def _lower1(s: str) -> str:
    """«Gente» → «gente»: el traductor pone mayúscula a lo que traduce suelto."""
    return s[:1].lower() + s[1:] if s[:1].isupper() and s[1:2].islower() else s


def _card_word(info: dict) -> str:
    """Traducción para la tarjeta: con la forma de diccionario delante si la
    hay («der Handschuh — el guante»), que es lo que hay que memorizar."""
    if info["headword"]:
        return f"{info['headword']} — {info['word_es']}"
    return info["word_es"]


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
    # mazo de cada idioma: «deck» es el del idioma activo, y al cambiar de
    # idioma se guarda aquí y se recupera el del nuevo
    "deck_by_lang": {},
    "sub_scale": 1.0, "dual_default": False, "autopause_default": False,
    "speed_default": 1.0, "ipa_enabled": True, "online_enabled": False,
    # "auto" = el navegador decide (i18n.js); quien ya tenga un idioma guardado
    # lo conserva, esto solo afecta a instalaciones nuevas
    # "auto" = el navegador decide (i18n.js); quien ya tenga un idioma guardado
    # lo conserva, esto solo afecta a instalaciones nuevas
    "audio_trim": False, "ui_lang": "auto", "base_language": "auto",
    # oraciones por tarjeta: 1 = la de la palabra; 2 = + la anterior; 3 = + la siguiente
    "card_sentences": 1,
    "card_examples": 2,
    # zipf mínimo para recomendar una palabra (0-7). Solo se recomiendan
    # palabras frecuentes y que no sean nombres propios (nivel de vocabulario).
    "rec_min_zipf": 3.5,
    # al pasar de página en el lector, ¿las palabras que quedaron sin tocar
    # pasan a conocidas? Apagado: se activa a mano y siempre se puede deshacer.
    "reader_mark_known": False,
    # plantilla de las tarjetas en Anki: "reading" (palabra y frase delante)
    # o "listening" (delante solo imagen y audio, para entrenar el oído)
    "card_layout": "reading",
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
    return {"ok": True, "anki": anki.is_up(_settings().get("anki_port")),
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
    # Un idioma sin diccionario Apertium ni tabla de formas que bajar (todos
    # menos el catalán y el francés) los tiene «listos» por definición. Antes
    # se miraba solo si existía el archivo, que nunca llega a existir: el
    # asistente se quedaba pidiendo una descarga que no descargaba nada.
    return {
        "ffmpeg": media.ffmpeg_available(),   # PATH o binario estático descargable
        "espeak": bool(shutil.which("espeak-ng") or shutil.which("espeak")),
        "spacy": importlib.util.find_spec(prof["spacy"]) is not None,
        "translator": translate.is_downloaded(),
        "forms": not prof.get("forms_url")
                 or (dl / "forms.sqlite").exists()
                 or (dl / f"forms-{_lang()}.sqlite").exists(),
        "dictionary": not prof.get("bidix_url")
                      or (dl / prof["bidix_file"]).exists(),
        "tts": piper_tts.is_downloaded(),
        "anki": anki.is_up(_settings().get("anki_port")),
    }


@app.get("/api/diagnostics")
def diagnostics_report(request: Request, extra: str = ""):
    """Informe para reportar un problema. NO se envía nada: devuelve el texto
    y la URL de GitHub con el issue redactado, para que el usuario lo lea,
    lo edite si quiere y decida él si lo manda."""
    if not _is_local_client(request):
        return _err("err.host_only", "solo desde el equipo anfitrión", 403)
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
            jobs.set_progress(jid, 0.05, f"Modelo lingüístico {prof['name']}…",
                              key="job.spacy", args=(prof["name"],))
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
        jobs.set_progress(jid, 0.1, "Descargando el traductor…",
                          key="job.translator")
        if not translate.is_downloaded():
            translate.download()
        if prof.get("bidix_url"):
            jobs.set_progress(jid, 0.6, "Diccionario de acepciones…",
                              key="job.bidix")
            _dict()
        if prof.get("forms_url"):
            jobs.set_progress(jid, 0.75, "Diccionario de formas (~66 MB)…",
                              key="job.forms")
            forms.lookup("hola")      # dispara descarga+build
        if prof.get("noun_lexicon"):
            jobs.set_progress(jid, 0.85, "Sustantivos: género y plurales…",
                              key="job.nouns")
            nouns.lookup("Hund")      # dispara descarga+build
        jobs.set_progress(jid, 0.9, "Glosas del Wikcionario…",
                          key="job.gloss")
        wikdict.lookup("hola")
        jobs.set_progress(jid, 0.95, "Voz neural (Piper)…",
                          key="job.voice")
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
        from_subs = s.get("srt_source") in ("youtube_subs", "youtube_auto", "srt")
        for seg in s["transcript"]:
            if from_subs:
                # Sesiones abiertas antes del arreglo: «… gegrillt!" sub9» y
                # «(Handy)». No se borra ningún segmento (las tarjetas apuntan
                # a su índice): si no queda nada, se deja como estaba.
                clean = subs.strip_annotations(re.sub(r"\s+sub\d+$", "", seg["text"]))
                seg["text"] = clean or seg["text"]
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
        return _err("err.text_only", "solo .txt o .epub")
    dest = config.DL_DIR / (uuid.uuid4().hex[:6] + "-" + nombre)
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    def work(jid):
        from .transcribe import tokens_for_existing
        jobs.set_progress(jid, 0.2, "Leyendo el texto…", key="job.reading")
        crudo = textimport.read_text(dest)
        jobs.set_progress(jid, 0.45, "Partiendo en frases…",
                          key="job.splitting")
        segs = textimport.to_segments(crudo)
        if not segs:
            raise jobs.JobError("err.no_readable_text",
                                "el archivo no tiene texto legible")
        jobs.set_progress(jid, 0.7, f"Analizando {len(segs)} frases…",
                          key="job.sentences", args=(len(segs),))
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
        jobs.set_progress(jid, 0.3, "Convirtiendo el video si hace falta…",
                          key="job.converting")
        playable = media.ensure_browser_playable(dest, config.DL_DIR)
        jobs.set_progress(jid, 0.8, "Analizando el video…", key="job.analysing")
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
        return _err("err.bad_url", "la URL debe empezar por http(s)://")

    def work(jid):
        jobs.set_progress(jid, 0.3, "Comprobando el enlace…",
                          key="job.checking")
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
    """Descarga y tokeniza los subtítulos (idioma de estudio) de un stream resuelto.
    Devuelve (transcript_json, srt_source). '' si no hay."""
    if not r.get("subs_url"):
        return "[]", "none"
    try:
        from .transcribe import tokens_for_existing
        segs = stream.subtitle_segments(r["subs_url"])
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
        return _err("err.bad_url", "la URL debe empezar por http(s)://")

    def work(jid):
        jobs.set_progress(jid, 0.3, "Resolviendo el enlace…",
                          key="job.resolving")
        # enlace directo a un archivo → sesión url normal (streaming directo)
        if stream.is_direct(url):
            dur = media.duration(url)
            if dur <= 0:
                raise jobs.JobError(
                    "err.bad_direct_link",
                    "no se pudo leer ese enlace directo de video")
            title = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] or url
            sid = db.create_session(
                CON, language=languages.active_code(),
                title=title, source_type="url", media_path=url,
                srt_source="none", model_size="-", duration_secs=dur,
                transcript_json="[]")
            return {"session_id": sid}
        # sitio soportado (YouTube, 3cat…) → resolver stream progresivo
        r = stream.resolve(url)
        if r.get("blocked"):
            raise jobs.JobError("err.geo_blocked", ytdlp.BLOCKED_MSG)
        if r.get("needs_download"):
            raise jobs.JobError(
                "err.no_direct_format",
                "Ese vídeo no tiene un formato reproducible directo. "
                "Descárgalo con «⬇️ Importar»: además te traerá sus subtítulos.")
        if not r:
            raise ValueError(
                "No pude extraer un vídeo de esa página. yt-dlp no soporta ese "
                "sitio (o el vídeo está protegido). Prueba con YouTube/3cat, o "
                "pega el enlace directo al archivo (.mp4) o al manifiesto (.m3u8).")
        jobs.set_progress(jid, 0.7, "Cargando subtítulos…", key="job.subs")
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
        return _err("err.not_stream", "no es una sesión de streaming")
    url, heights, is_hls = stream.stream_url(s["page_url"],
                                             height or s["stream_height"])
    if not url:
        return _err("err.link_gone",
                    "el enlace ya no está disponible o cambió", 502)
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
        return _err("err.model_lang",
                    f"modelo «{req.model}» no disponible para este idioma",
                    args=(req.model,))

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
        return _err("err.transcribe_first", "transcribe primero esta sesión")

    def work(jid):
        jobs.set_progress(jid, 0.05, "Preparando audio condensado…",
                          key="job.condensing")
        src = s["media_path"]
        if s.get("source_type") == "stream" and s.get("page_url"):
            fresh, _, _ = stream.stream_url(s["page_url"],
                                            s.get("stream_height") or 0)
            if fresh:
                src = fresh
        ranges = [(g["start"], g["end"]) for g in segs
                  if g.get("end", 0) > g.get("start", 0)]
        name = f"condensed-{sid}.mp3"
        jobs.set_progress(jid, 0.15, "Extrayendo el diálogo (puede tardar)…",
                          key="job.extracting")
        dur = media.condensed_audio(src, ranges,
                                    str(config.MEDIA_DIR / name))
        jobs.set_progress(jid, 1.0, "Listo", key="job.done")
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
        return _err("err.no_subs", "no se han encontrado subtítulos en el archivo")
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
        anki.ensure_note_type(_settings()["card_layout"])  # keeps card template in sync
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


# Categoría de spaCy (UD) → las de las glosas (kaikki y WikDict usan las mismas)
_GLOSS_POS = {
    "NOUN": {"noun"}, "PROPN": {"name", "noun"}, "VERB": {"verb"},
    "AUX": {"verb"}, "ADJ": {"adj", "participle"}, "ADV": {"adv"},
    "ADP": {"prep", "postp", "contraction"}, "CCONJ": {"conj"},
    "SCONJ": {"conj"}, "PRON": {"pron"}, "DET": {"det", "article"},
    "NUM": {"num"}, "INTJ": {"intj"}, "PART": {"particle"},
}
# Palabras gramaticales: una glosa de otra categoría es de un homógrafo
# («pero» conjunción frente a «pero», un tipo de manzana).
_CLOSED_POS = {"ADP", "CCONJ", "SCONJ", "PRON", "DET", "AUX", "PART"}


def _rank_glosses(glosses: list[tuple[str, str]], pos: str,
                  words: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Ordena las glosas por la categoría que spaCy le da a la palabra.

    El Wikcionario mezcla homógrafos y el orden no los distingue: «pero» salía
    como «apple» antes que nada, y «como» como «Como» (la ciudad). Las de la
    misma categoría van primero; en palabras gramaticales se quitan las de
    otra categoría conocida (la traducción de la palabra ya va arriba), y una
    glosa en mayúscula igual a la palabra en minúscula es un nombre propio."""
    low = {w.strip().lower() for w in words
           if w and w.strip() and w.strip() == w.strip().lower()}
    glosses = [(g, p) for g, p in glosses
               if not (g[:1].isupper() and g.strip().lower() in low)]
    want = _GLOSS_POS.get(pos or "")
    if not want:
        return glosses
    match = [x for x in glosses if x[1] in want]
    if pos in _CLOSED_POS:
        rest = [x for x in glosses if not x[1]]          # sin categoría: puede valer
    else:
        rest = [x for x in glosses if x[1] not in want]
    return match + rest


def _definition(selection: str, lemma: str, pos: str) -> str:
    """Todas las glosas del Wikcionario, para el reverso de la tarjeta.

    El popup las enseñaba («clipping of Trabant (East German make of car)»)
    pero no llegaban a Anki, y el traductor no sabe de palabras así: «Trabi»
    salía como «Trabi»."""
    return _html_lines(_definition_text(selection, lemma, pos))


def _definition_text(selection: str, lemma: str, pos: str) -> str:
    """Las glosas, una por línea: lo que se ve (y se puede editar) en el editor."""
    try:
        # En alemán el lema de spaCy falla con los plurales («handschuhe»);
        # la tabla de sustantivos da la entrada del diccionario («Handschuh»).
        hit = nouns.lookup(selection) or nouns.lookup(lemma)
        glosses = ((wikdict.lookup(hit[0], limit=12) if hit else [])
                   or wikdict.lookup(lemma, limit=12)
                   or wikdict.lookup(selection, limit=12))
    except Exception:                                  # noqa: BLE001
        return ""
    glosses = _rank_glosses(glosses, pos, (lemma, selection))
    return "\n".join(g.replace("\n", " ") for g, _ in glosses)


@app.post("/api/lookup")
def lookup(req: LookupReq):
    """Instant word info for the Migaku-style popup (no media generated)."""
    info = _word_info(req.selection, req.sentence)
    lemma, pos = info["lemma"], info["pos"]
    z = nlp.zipf(req.selection)
    es_src = languages.spanish_sources_active()   # bidix/glosas son fuentes es
    senses = _senses(req.selection, lemma) if es_src else []
    word_es = info["word_es"]
    sentence_es = ""
    if req.session_id and req.segment_index >= 0:
        sentence_es = _segment_es(req.session_id, req.segment_index)
    if not sentence_es and req.sentence:
        sentence_es = translate.sentence(req.sentence)
    # las glosas ya no dependen del español: wikdict elige el extracto del
    # Wikcionario que toque según la base activa (es o en)
    glosses = (wikdict.lookup(info["gloss_key"], limit=12)
               or wikdict.lookup(lemma, limit=12)
               or wikdict.lookup(req.selection, limit=12))
    glosses = _rank_glosses(glosses, pos, (lemma, req.selection))
    userdefs = userdict.lookup(lemma) or userdict.lookup(req.selection)
    return {
        "selection": req.selection,
        "lemma": lemma, "pos": pos, "headword": info["headword"],
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


def _as_path(raw: str) -> Path:
    """Ruta escrita a mano, y por tanto pegada de donde sea.

    Los gestores de archivos de Linux (Nautilus, Files de Zorin) copian
    `file:///home/…` en vez de la ruta; macOS y algunos terminales copian la
    ruta entre comillas. Las dos cosas llegaban tal cual a Path() y fallaban
    con «no encuentro ese archivo» teniendo el archivo delante."""
    t = (raw or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()                       # comillas de copiar-pegar
    if t.startswith("file://"):
        t = url_unquote(urlparse(t).path)         # URI → ruta, y %20 → espacio
    return Path(t).expanduser()


@app.post("/api/userdict/import")
def userdict_import(req: UserDictReq):
    p = _as_path(req.path)
    if not p.exists():
        return _err("err.no_file", "no encuentro ese archivo")
    try:
        info = userdict.import_file(str(p))
    except Exception as e:
        _log.exception("userdict import failed")
        return _err("err.import_failed", f"no se pudo importar: {e}",
                    args=(str(e),))
    return {"ok": True, **info, "dicts": userdict.list_dicts()}


@app.post("/api/userdict/upload")
async def userdict_upload(files: list[UploadFile] = File(...)):
    """Importar sin escribir rutas: el navegador manda el archivo.

    StarDict no es un archivo sino un conjunto (.ifo + .dict + .idx), así que
    se aceptan varios y se guardan juntos en un temporal — pyglossary lee el
    .ifo y encuentra sus hermanos al lado. Yomitan viene en un .zip y basta
    con uno. El temporal se borra siempre: lo que queda es el sqlite ya
    indexado."""
    tmp = Path(tempfile.mkdtemp(prefix="userdict-"))
    try:
        saved = []
        for f in files:
            dest = tmp / (Path(f.filename or "dic").name or "dic")
            with dest.open("wb") as out:
                shutil.copyfileobj(f.file, out)
            saved.append(dest)
        if not saved:
            return _err("err.no_file", "no llegó ningún archivo")
        main = (next((q for q in saved if q.suffix.lower() == ".ifo"), None)
                or next((q for q in saved if q.suffix.lower() == ".zip"), None)
                or max(saved, key=lambda q: q.stat().st_size))
        try:
            info = userdict.import_file(str(main))
        except Exception as e:
            _log.exception("userdict upload failed")
            return _err("err.import_failed", f"no se pudo importar: {e}",
                        args=(str(e),))
        return {"ok": True, **info, "dicts": userdict.list_dicts()}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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

# Fin de oración: el signo final, con comillas o paréntesis detrás si los hay.
# «...» no cuenta: en subtítulos marca que la frase sigue en la línea siguiente.
_SENT_END = re.compile(r'[.!?。！？]["»”’)\]]*\s*$')
_MAX_LINES_PER_SENTENCE = 4     # subtítulos automáticos: no traen puntuación
_MAX_PAUSE = 2.0                # una pausa así ya es otra frase, diga lo que diga el punto
_MAX_CONTEXT_SECS = 30.0


def _ends_sentence(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(_SENT_END.search(t)) and not t.endswith(("...", "…"))


def _sentence_bounds(segs: list, idx: int) -> tuple[int, int]:
    """(primera, última) línea de la oración que contiene la línea idx.

    Una línea de subtítulo no es una oración: ZDF parte «Die Imkerei ist
    eine Kunst, die meist von Generation zu» / «Generation weitergegeben
    wird.», y la tarjeta se quedaba con media frase. Si en unas pocas líneas
    no aparece el final (subtítulos automáticos, sin puntuación), se queda
    con la línea sola."""
    def joined(a, b):        # ¿b sigue a a sin pausa?
        return segs[b]["start"] - segs[a]["end"] <= _MAX_PAUSE
    lo = idx
    while (lo > 0 and idx - lo < _MAX_LINES_PER_SENTENCE - 1 and joined(lo - 1, lo)
           and not _ends_sentence(segs[lo - 1]["text"])):
        lo -= 1
    if lo > 0 and joined(lo - 1, lo) and not _ends_sentence(segs[lo - 1]["text"]):
        lo = idx                                   # no se encontró el inicio
    hi = idx
    while (hi < len(segs) - 1 and hi - lo < _MAX_LINES_PER_SENTENCE - 1
           and joined(hi, hi + 1) and not _ends_sentence(segs[hi]["text"])):
        hi += 1
    if hi < len(segs) - 1 and joined(hi, hi + 1) and not _ends_sentence(segs[hi]["text"]):
        hi = idx                                   # no se encontró el final
    return lo, hi


def _context_range(segs: list, idx: int, sentences: int = 1,
                   pad_before: int = 0, pad_after: int = 0) -> tuple[int, int]:
    """Líneas que entran en la tarjeta: la oración de la palabra y, según el
    ajuste «card_sentences», la anterior (2) y la siguiente (3). Los ⏪+ / +⏩
    del editor añaden una línea más por cada pulsación.

    Hay quien estudia con dos oraciones por tarjeta para entender el
    contexto (lo pidieron en Reddit, así lo hacían en Yomitan)."""
    lo, hi = _sentence_bounds(segs, idx)
    if sentences >= 2 and lo > 0:
        lo = _sentence_bounds(segs, lo - 1)[0]
    if sentences >= 3 and hi < len(segs) - 1:
        hi = _sentence_bounds(segs, hi + 1)[1]
    # que el contexto automático no se coma medio episodio
    while segs[hi]["end"] - segs[lo]["start"] > _MAX_CONTEXT_SECS and (lo < idx or hi > idx):
        if hi > idx and (hi - idx >= idx - lo):
            hi -= 1
        else:
            lo += 1
    return max(0, lo - pad_before), min(len(segs) - 1, hi + pad_after)


def _card_sentences() -> int:
    return int(_settings().get("card_sentences") or 1)


def _html_lines(text: str) -> str:
    """Texto del editor (una cosa por línea) a HTML para Anki, escapado:
    lo que escribe el usuario no puede romper la plantilla."""
    import html
    return "<br>".join(html.escape(x.strip()) for x in (text or "").splitlines()
                       if x.strip())


def _examples_for(lemma: str, session_id: str, frase: str) -> list[str]:
    """Otras frases de tus vídeos y libros con la misma palabra («card_examples»
    como máximo). Las que ya están en la tarjeta no cuentan."""
    n = _settings().get("card_examples")
    n = 2 if n is None else int(n)
    if n <= 0 or not lemma:
        return []
    try:
        found = examples.find(CON, lemma, limit=n + 4, language=_lang())
    except Exception as e:                              # noqa: BLE001
        _log.warning("ejemplos para la tarjeta: %s", e)
        return []
    return [e["text"] for e in found if e["text"] not in frase][:n]


class PreviewReq(BaseModel):
    session_id: str
    segment_index: int
    selection: str
    pad_before: int = 0   # líneas de más antes del contexto (⏪+)
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
    # Netflix: el audio y la imagen los pone asbplayer (de la tecla, o al enviar)
    if s.get("source_type") == "asbplayer":
        return _text_preview(s, segs, segment_index, selection, pad_before, pad_after,
                             netflix=True)

    desde, hasta = _context_range(segs, segment_index, _card_sentences(),
                                  pad_before, pad_after)
    frase = " ".join(x["text"] for x in segs[desde:hasta + 1])
    # el audio cubre todo el contexto; la imagen y el GIF, la línea de la
    # palabra: si no, con la oración anterior delante la captura mostraba
    # otra escena
    start = max(0.0, segs[desde]["start"] + offset)
    end = max(0.0, segs[hasta]["end"] + offset)
    vstart = max(0.0, seg["start"] + offset)
    vend = max(vstart + 0.1, seg["end"] + offset)
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
        win_dur = min(max(0.1, vend - vstart), MAX_GIF) + 0.5
        wp = config.MEDIA_DIR / f"cm-{base}-win.mp4"
        try:
            media.download_window(src, vstart, win_dur, str(wp))
            win_path = str(wp)
        except Exception as e:
            _log.warning("ventana de stream falló (%s); intento directo", e)

    video_src = win_path or src
    # en la ventana los tiempos son relativos (empieza en 0); directo usa originales
    win_content = min(max(0.1, vend - vstart), MAX_GIF)
    snap_ts = min(max(0.0, mid - vstart), win_content - 0.1) if win_path else mid
    gif_start, gif_end = (0.0, win_content) if win_path else (vstart, vstart + win_content)

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

    info = _word_info(selection, seg["text"])
    lemma, pos = info["lemma"], info["pos"]
    z = nlp.zipf(selection)
    senses = _senses(selection, lemma) if languages.spanish_sources_active() else []
    frase_es = translate.sentence(frase)
    word_es = info["word_es"]
    return {
        "paraula": selection,
        "lema": lemma, "pos": pos, "headword": info["headword"],
        "paraula_es": _card_word(info),
        "senses": [{"es": es, "pos": p} for es, p in senses[:8]],
        "active": _active_sense(senses[:8], frase_es, word_es),
        "frase": frase,
        "frase_es": frase_es,
        "definicio": _definition_text(selection, lemma, pos),
        "exemples": "\n".join(_examples_for(lemma, s["id"], frase)),
        "freq_zipf": z, "freq_rank": nlp.freq_badge(z),
        "audio_file": audio_name if audio_ok else "",
        "image_file": image_name if image_ok else "",
        "clip_file": clip_name if clip_ok else "",
        "font": f"{s['title']} @ {_fmt_ts(seg['start'])}",
    }


def _text_preview(s: dict, segs: list, idx: int, selection: str,
                  pad_before: int = 0, pad_after: int = 0,
                  netflix: bool = False) -> dict:
    """Tarjeta desde un libro: frase, traducción y voz neural. Sin imagen.

    Las frases del contexto («card_sentences») y los ⏪+ / +⏩ del editor
    funcionan igual que en vídeo.

    netflix: sesión de asbplayer. Sin voz sintética: si la línea se capturó
    con la tecla trae su audio y su imagen; si no, asbplayer los graba al
    enviar la tarjeta (_asb_after_card).
    """
    desde, hasta = _context_range(segs, idx, _card_sentences(), pad_before, pad_after)
    frase = " ".join(x["text"] for x in segs[desde:hasta + 1])

    audio_name = image_name = ""
    if netflix:
        audio_name = segs[idx].get("audio_file", "")
        image_name = segs[idx].get("image_file", "")
    else:
        try:
            audio_name = piper_tts.speak(frase)
        except Exception as e:                          # noqa: BLE001
            failures.warn_once("text-tts", "sin voz para las tarjetas de texto", e)

    info = _word_info(selection, frase)
    lemma, pos = info["lemma"], info["pos"]
    z = nlp.zipf(selection)
    senses = _senses(selection, lemma) if languages.spanish_sources_active() else []
    frase_es = translate.sentence(frase)
    word_es = info["word_es"]
    return {
        "paraula": selection,
        "lema": lemma, "pos": pos, "headword": info["headword"],
        "paraula_es": _card_word(info),
        "senses": [{"es": es, "pos": p} for es, p in senses[:8]],
        "active": _active_sense(senses[:8], frase_es, word_es),
        "frase": frase,
        "frase_es": frase_es,
        "definicio": _definition_text(selection, lemma, pos),
        "exemples": "\n".join(_examples_for(lemma, s["id"], frase)),
        "freq_zipf": z, "freq_rank": nlp.freq_badge(z),
        "audio_file": audio_name,
        "image_file": image_name,
        "clip_file": "",
        # en un libro el "@ 07:16" no significa nada: va el número de frase
        "font": (f"{s['title']} @ {_fmt_ts(segs[idx]['start'])}" if netflix
                 else f"{s['title']} · {idx + 1}/{len(segs)}"),
    }


def _bad_index(s: dict, idx: int):
    n = len(json.loads(s["transcript_json"]))
    if not 0 <= idx < n:
        return _err("err.bad_segment",
                    f"segment_index fuera de rango (0-{n - 1})",
                    args=(n - 1,))
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
        language=_lang(),
        definicio=_html_lines(p["definicio"]),
        exemples=_html_lines(p["exemples"]))
    if p["lema"]:
        db.mark_learning_if_new(CON, p["lema"], _lang())
    _flush()
    st = db.card_status(CON, cid)
    netflix = _asb_after_card(req.session_id, req.segment_index, cid,
                              bool(p["audio_file"]), p["frase"])
    return {"card_id": cid, "sent_now": st == "sent", "duplicate": st == "duplicate",
            "pending": len(db.pending_cards(CON)),
            "word_status": db.word_statuses(CON, _lang()).get(p["lema"]),
            "lema": p["lema"], "paraula": p["paraula"], "netflix": netflix}


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
    # Del editor, una cosa por línea. definicio=None: la de siempre, sacada
    # del diccionario (clientes que no la mandan).
    definicio: str | None = None
    exemples: str = ""
    notes: str = ""


@app.post("/api/cards")
def create_card(req: CardReq):
    cid = db.create_card(CON, session_id=req.session_id,
                         segment_index=req.segment_index, paraula=req.paraula,
                         lema=req.lema, pos=req.pos, paraula_es=req.paraula_es,
                         frase=req.frase, frase_es=req.frase_es,
                         freq_rank=req.freq_rank, audio_file=req.audio_file,
                         image_file=req.image_file, font=req.font,
                         language=_lang(),
                         definicio=(_definition(req.paraula, req.lema, req.pos)
                                    if req.definicio is None
                                    else _html_lines(req.definicio)),
                         exemples=_html_lines(req.exemples),
                         notes=_html_lines(req.notes))
    if req.lema:
        db.mark_learning_if_new(CON, req.lema, _lang())
    _flush()
    # Se mira ESTA tarjeta: el recuento del envío mezcla las de la cola, y una
    # duplicada (la palabra ya está en Anki) se descarta. Antes se anunciaba
    # «en cola», como si fuera a llegar al abrir Anki, y no llegaba nunca.
    st = db.card_status(CON, cid)
    netflix = _asb_after_card(req.session_id, req.segment_index, cid,
                              bool(req.audio_file), req.frase)
    return {"card_id": cid, "sent_now": st == "sent", "duplicate": st == "duplicate",
            "pending": len(db.pending_cards(CON)),
            "word_status": db.word_statuses(CON, _lang()).get(req.lema.strip().lower()),
            "netflix": netflix}


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
    layout = _settings()["card_layout"]
    n = 0
    for card in db.pending_cards(CON):
        try:
            note_id = anki.send_card(card, _deck_for(card.get("language")), layout)
            db.mark_card_sent(CON, card["id"], note_id)
            n += 1
        except anki.AnkiError as e:
            if "duplicate" in str(e).lower():
                db.mark_card_duplicate(CON, card["id"])
                continue
            # Anki contestó, pero no quiere ESTA tarjeta. Antes se cortaba
            # aquí y todas las de detrás se quedaban sin mandar para siempre
            # («enviando 2…», PR #16). Se salta, se dice, y se sigue.
            failures.warn_once(
                "anki-card",
                f"Anki rechazó la tarjeta «{card.get('paraula') or card.get('frase', '')[:40]}»; "
                "se queda en la cola y las demás se envían igual.", e)
            continue
        except Exception:
            break                         # Anki dejó de contestar: no insistir
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
    # El tipo de nota que hay que elegir en asbplayer. Quien instaló antes del
    # cambio de nombre lo tiene como «CatalaMiner», y buscaba «LinguaMiner».
    model = _guarded(anki.model_in_use, default=config.NOTE_TYPE) if up else config.NOTE_TYPE
    return {"up": up, "port": port, "reason": reason, "diag": diag,
            "decks": decks, "deck": _settings()["deck"], "model": model,
            "pending": len(db.pending_cards(CON))}


# ---------- puente con asbplayer (Netflix y otras webs) ----------
# asbplayer apunta aquí en vez de a AnkiConnect. Ver app/ankiproxy.py.

_ASB_SESSION = "asbplayer"      # las tarjetas no vienen de una sesión tuya
_ANKI_DOWN = ("LinguaMiner no encuentra Anki: ábrelo (con AnkiConnect) y "
              "vuelve a probar · LinguaMiner can't find Anki: open it "
              "(with AnkiConnect) and try again")


def _guarded(fn, *args, default=""):
    """Un dato que no sale (traductor, diccionario) no puede tumbar la tarjeta:
    asbplayer ya grabó el audio y el clip, y se perderían."""
    try:
        return fn(*args)
    except Exception as e:                              # noqa: BLE001
        _log.warning("puente asbplayer, %s: %s", getattr(fn, "__name__", fn), e)
        return default


def _enrich_note(note: dict) -> dict | None:
    """Completa una nota LinguaMiner de asbplayer con lo que sabe LinguaMiner.

    Solo rellena lo que llega vacío: lo que escribiste en el diálogo de
    asbplayer manda. El audio y la imagen no se tocan (van aparte, en
    note.audio / note.picture). Devuelve lo que hay que apuntar en la base de
    datos, o None si la nota no es de LinguaMiner."""
    if note.get("modelName") not in (config.NOTE_TYPE, config.NOTE_TYPE_LEGACY):
        return None
    f = note.get("fields")
    if not isinstance(f, dict):
        return None
    plain, esc = ankiproxy.plain, ankiproxy.esc

    def empty(k):
        return not plain(f.get(k))

    frase_raw = f.get("Frase") or ""
    frase = plain(frase_raw)
    typed = plain(f.get("Paraula"))
    word = typed or ankiproxy.highlighted(frase_raw)
    if not word and not frase:
        return None                   # nada que completar: pasa tal cual

    frase_es = plain(f.get("FraseES"))
    if frase and not frase_es:
        frase_es = _guarded(translate.sentence, frase)
        if frase_es:
            f["FraseES"] = esc(frase_es)

    lemma = pos = freq = ""
    if word:
        if not typed:
            f["Paraula"] = esc(word)
        info = _guarded(_word_info, word, frase, default=None) or {
            "lemma": word.lower(), "pos": "", "headword": "", "word_es": ""}
        lemma, pos = info["lemma"], info["pos"]
        if empty("ParaulaES"):
            f["ParaulaES"] = esc(_card_word(info))
        if empty("Definicio"):
            f["Definicio"] = _guarded(_definition, word, lemma, pos)
        if empty("Exemples"):
            ex = _guarded(_examples_for, lemma, _ASB_SESSION, frase, default=[])
            f["Exemples"] = _html_lines("\n".join(ex))
        freq = _guarded(lambda w: nlp.freq_badge(nlp.zipf(w)), word)
        if empty("Freq"):
            f["Freq"] = esc(freq)
    else:
        # Tarjeta de frase. Paraula es el primer campo y no puede ir vacío
        # (Anki rechaza la nota); la frase pasa delante y no se repite.
        f["Paraula"] = esc(frase)
        f["Frase"] = ""

    tags = [t for t in (note.get("tags") or []) if isinstance(t, str)]
    if "lingua-miner" not in tags:
        tags.append("lingua-miner")
    note["tags"] = tags
    return {"paraula": plain(f.get("Paraula")), "lema": lemma, "pos": pos,
            "paraula_es": plain(f.get("ParaulaES")), "frase": frase,
            "frase_es": frase_es, "freq_rank": plain(f.get("Freq")) or freq,
            "font": plain(f.get("Font")) or "asbplayer",
            "definicio": f.get("Definicio") or "",
            "exemples": f.get("Exemples") or "", "notes": f.get("Notes") or ""}


def _record_card(card: dict, note_id: int):
    """La tarjeta de asbplayer también cuenta en LinguaMiner: la palabra pasa a
    «aprendiendo» y, cuando madura en Anki, a conocida (sync-statuses)."""
    try:
        db.create_card(CON, session_id=_ASB_SESSION, segment_index=-1,
                       audio_file="", image_file="", language=_lang(),
                       anki_note_id=note_id, **card)
        if card["lema"]:
            db.mark_learning_if_new(CON, card["lema"], _lang())
    except Exception as e:                              # noqa: BLE001
        _log.warning("puente asbplayer, guardar la tarjeta: %s", e)


def _ankiconnect(payload) -> dict:
    if not (isinstance(payload, dict) and isinstance(payload.get("action"), str)):
        return {"result": None, "error": "LinguaMiner: petición AnkiConnect no válida"}
    action = payload["action"]
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    note = params.get("note")
    if action == "addNote" and _asb_is_capture(note):
        # Ctrl+Shift+Z en Netflix: la línea va a LinguaMiner, no a Anki (ni
        # hace falta que Anki esté abierto); la palabra se elige allí
        return _asb_capture(note)
    pref = _settings().get("anki_port")
    if anki.find_port(pref)[0] is None:
        return {"result": None, "error": _ANKI_DOWN}
    if action == "modelNames":
        # Para que «LinguaMiner» salga en la lista de tipos de nota de
        # asbplayer aunque nunca hayas mandado una tarjeta desde la app
        _guarded(anki.ensure_note_type, _settings()["card_layout"])
    card = None
    if action in ("addNote", "guiAddCards") and isinstance(note, dict):
        card = _enrich_note(note)
    try:
        resp = anki.forward(payload, pref)
    except Exception as e:                              # noqa: BLE001
        _log.warning("puente asbplayer, %s: %s", action, e)
        return {"result": None, "error": _ANKI_DOWN}
    if (action == "addNote" and card and isinstance(resp, dict)
            and not resp.get("error") and isinstance(resp.get("result"), int)):
        _record_card(card, resp["result"])
    return resp


@app.options("/ankiconnect")
def ankiconnect_preflight(request: Request):
    origin = request.headers.get("origin")
    if not ankiproxy.origin_allowed(origin):
        return Response(status_code=403)
    return Response(status_code=204, headers=ankiproxy.cors_headers(origin))


@app.post("/ankiconnect")
async def ankiconnect(request: Request):
    """AnkiConnect para asbplayer: mismas peticiones, mismas respuestas, y las
    notas LinguaMiner llegan a Anki completas. asbplayer manda el JSON como
    text/plain, así que se lee el cuerpo a mano."""
    origin = request.headers.get("origin")
    if not ankiproxy.origin_allowed(origin):
        return JSONResponse({"result": None,
                             "error": "LinguaMiner: origen no permitido"},
                            status_code=403)
    try:
        payload = json.loads(await request.body() or b"null")
    except ValueError:
        payload = None
    out = await run_in_threadpool(_ankiconnect, payload)
    return JSONResponse(out, headers=ankiproxy.cors_headers(origin))


# ---------- Netflix desde LinguaMiner (asbplayer por WebSocket) ----------
# asbplayer se conecta a /ws y queda de grabadora: LinguaMiner trae los
# subtítulos del episodio, hace saltar el vídeo y le pide el audio y la imagen
# de la línea minada. Su API no da la posición de reproducción, así que la
# línea que acabas de oír llega con una tecla: Ctrl+Shift+Z en Netflix
# exporta sin palabra, el puente la captura (audio e imagen incluidos) y la
# interfaz salta a ella. Ver docs/plans/2026-11-28-netflix-desde-linguaminer.md.

_ASB_LOCK = threading.Lock()            # crear/actualizar la sesión del episodio
_ASB_EVENTS: list[dict] = []            # líneas capturadas, para que la UI salte
_ASB_N = 0
_SOURCE_RE = re.compile(
    r"^(?P<name>.*?)\s*\((?P<h>\d+)h(?P<m>\d+)m(?P<s>[\d.]+)s\)\s*$")
_TRACK_TAIL = re.compile(r"\s+-\s+[a-z]{2,3}(?:-[A-Za-z]{2,4})?\s+-\s+.*$")
_TRACK_LANG = re.compile(r"\s-\s([a-z]{2,3})(?:-[A-Za-z]{2,4})?\s-\s")


def _asb_source(font: str) -> tuple[str, float | None]:
    """Fuente de asbplayer → (archivo de subtítulos, segundo del vídeo).
    «Génesis S01E01 … [CC].nfimsc (00h09m05.4s)» → («Génesis … .nfimsc», 545.4)."""
    m = _SOURCE_RE.match(font or "")
    if not m:
        return (font or "").strip(), None
    return (m["name"].strip(),
            int(m["h"]) * 3600 + int(m["m"]) * 60 + float(m["s"]))


def _asb_title(name: str) -> str:
    """«Génesis S01E01 Episodio 1 - ca - Catalán [CC].nfimsc» → «Génesis S01E01 Episodio 1»."""
    base = re.sub(r"\.[A-Za-z0-9]{2,6}$", "", name or "")
    return _TRACK_TAIL.sub("", base).strip() or base.strip() or "Netflix"


def _asb_track_lang(name: str) -> str:
    m = _TRACK_LANG.search(name or "")
    return m.group(1) if m else ""


def _asb_key(name: str) -> str:
    return "asbplayer:" + (name or "Netflix")


def _asb_find(name: str) -> dict | None:
    return db.find_session_by_media(CON, _asb_key(name), "asbplayer", _lang())


def _asb_media(name: str | None = None) -> dict | None:
    """El vídeo de asbplayer con esos subtítulos (o, sin nombre, el de la
    pestaña activa). Los id cambian si recargas la pestaña: se piden cada vez."""
    res = asbws.HUB.call("get-bound-media", timeout=4) or {}
    media = [m for m in (res.get("media") or []) if m.get("loadedSubtitles")]
    if name:
        for m in media:
            if any(t.get("fileName") == name for t in m["loadedSubtitles"]):
                return m
        return None
    media.sort(key=lambda m: (not m.get("active"), m.get("type") != "streaming"))
    return media[0] if media else None


def _asb_cues_to_segs(cues: list) -> list[dict]:
    from .transcribe import tokens_for_existing
    segs = []
    for c in sorted((c for c in cues if isinstance(c, dict)),
                    key=lambda c: c.get("start") or 0):
        text = ankiproxy.plain(str(c.get("text") or ""))
        if not text:
            continue
        segs.append({"start": (c.get("start") or 0) / 1000,
                     "end": (c.get("end") or 0) / 1000, "text": text})
    segs = tokens_for_existing(segs)
    for i, seg in enumerate(segs):
        seg["para"] = i                  # una línea, un párrafo: son subtítulos
    return segs


def _asb_locate(segs: list, ts: float | None, frase: str) -> int | None:
    """La línea capturada en la sesión: la que suena en ese segundo (si hay
    varias, la que coincide con el texto); sin segundo, por el texto."""
    if ts is not None:
        near = [i for i, x in enumerate(segs)
                if x["start"] - 0.5 <= ts <= x["end"] + 0.5]
        for i in near:
            if segs[i]["text"] and (segs[i]["text"] in frase or frase in segs[i]["text"]):
                return i
        if near:
            return min(near, key=lambda i: abs(segs[i]["start"] - ts))
    for i, x in enumerate(segs):
        if x["text"] == frase:
            return i
    return None


def _asb_save_media(item, default_ext: str) -> str:
    """Audio o imagen que manda asbplayer (base64) a MEDIA_DIR. Nombre asb-*:
    la limpieza de _gc_media solo toca los cm-* de las previews."""
    import base64
    if isinstance(item, list):
        item = item[0] if item else None
    if not isinstance(item, dict) or not item.get("data"):
        return ""
    ext = Path(str(item.get("filename") or "")).suffix.lstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9]{2,5}", ext):
        ext = default_ext
    name = f"asb-{uuid.uuid4().hex[:12]}.{ext}"
    try:
        (config.MEDIA_DIR / name).write_bytes(base64.b64decode(item["data"]))
    except (ValueError, OSError) as e:
        _log.warning("asbplayer: no pude guardar %s: %s", name, e)
        return ""
    return name


def _asb_merge_media(old: list, new: list):
    """Al recargar los subtítulos, las líneas ya capturadas conservan su
    audio e imagen."""
    for x in old:
        if x.get("audio_file") or x.get("image_file"):
            i = _asb_locate(new, (x["start"] + x["end"]) / 2, x["text"])
            if i is not None:
                for k in ("audio_file", "image_file"):
                    if x.get(k):
                        new[i][k] = x[k]


def _asb_open(name: str | None = None) -> str:
    """Trae el episodio de asbplayer como sesión de LinguaMiner (o la
    actualiza) y devuelve su id."""
    m = _asb_media(name)
    if m is None:
        raise asbws.AsbError("no-media")
    track = next((t for t in m["loadedSubtitles"]
                  if not name or t.get("fileName") == name), m["loadedSubtitles"][0])
    fname = track.get("fileName") or m.get("title") or "Netflix"
    res = asbws.HUB.call("get-subtitles", {"mediaId": m["id"],
                                           "trackNumbers": [track.get("trackNumber", 0)]},
                         timeout=15) or {}
    segs = _asb_cues_to_segs(res.get("subtitles") or [])
    if not segs:
        raise asbws.AsbError("no-subtitles")
    with _ASB_LOCK:
        s = _asb_find(fname)
        if s:
            _asb_merge_media(json.loads(s["transcript_json"]), segs)
            db.update_transcript(CON, s["id"], json.dumps(segs), "-", "asbplayer",
                                 nlp.TOK_VERSION)
            return s["id"]
        return db.create_session(
            CON, title=_asb_title(fname), source_type="asbplayer",
            media_path=_asb_key(fname), srt_source="asbplayer", model_size="-",
            duration_secs=segs[-1]["end"], transcript_json=json.dumps(segs),
            language=_lang())


def _asb_is_capture(note) -> bool:
    """Una nota LinguaMiner de asbplayer sin palabra elegida: es la tecla de
    «esta línea», no una tarjeta."""
    if not (isinstance(note, dict)
            and note.get("modelName") in (config.NOTE_TYPE, config.NOTE_TYPE_LEGACY)
            and isinstance(note.get("fields"), dict)):
        return False
    f = note["fields"]
    return bool(ankiproxy.plain(f.get("Frase"))
                and not ankiproxy.plain(f.get("Paraula"))
                and not ankiproxy.highlighted(f.get("Frase")))


def _asb_capture(note: dict) -> dict:
    """La línea que suena en Netflix, con su audio y su imagen, a la sesión
    del episodio; la interfaz salta a ella para elegir la palabra."""
    global _ASB_N
    f = note["fields"]
    frase = ankiproxy.plain(f.get("Frase"))
    name, ts = _asb_source(ankiproxy.plain(f.get("Font")))
    audio = _asb_save_media(note.get("audio"), "mp3")
    image = _asb_save_media(note.get("picture"), "jpeg")
    if _asb_find(name) is None and asbws.HUB.connected:
        try:
            _asb_open(name)              # el episodio entero, si asbplayer está conectado
        except Exception as e:                          # noqa: BLE001
            _log.info("asbplayer: sin el episodio entero (%s); solo la línea", e)
    from .transcribe import tokens_for_existing
    with _ASB_LOCK:
        s = _asb_find(name)
        if s is None:
            sid = db.create_session(
                CON, title=_asb_title(name), source_type="asbplayer",
                media_path=_asb_key(name), srt_source="asbplayer-lines",
                model_size="-", duration_secs=0.0, transcript_json="[]",
                language=_lang())
            s = db.get_session(CON, sid)
        segs = json.loads(s["transcript_json"])
        idx = _asb_locate(segs, ts, frase)
        if idx is None:
            start = ts if ts is not None else (segs[-1]["end"] + 1 if segs else 0.0)
            seg = tokens_for_existing([{"start": start, "end": start + 2.0,
                                        "text": frase}])[0]
            segs.append(seg)
            segs.sort(key=lambda x: x["start"])
            for i, x in enumerate(segs):
                x["para"] = i
            idx = segs.index(seg)
        if audio:
            segs[idx]["audio_file"] = audio
        if image:
            segs[idx]["image_file"] = image
        db.update_transcript(CON, s["id"], json.dumps(segs), "-", s["srt_source"],
                             nlp.TOK_VERSION)
        thumb = config.MEDIA_DIR / f"thumb-{s['id']}.jpg"
        if image.endswith((".jpeg", ".jpg")) and not thumb.exists():
            try:
                shutil.copyfile(config.MEDIA_DIR / image, thumb)
            except OSError:
                pass
        _ASB_N += 1
        lang = _asb_track_lang(name)
        _ASB_EVENTS.append({"n": _ASB_N, "session_id": s["id"], "segment_index": idx,
                            "title": s["title"],
                            "track_lang": lang if lang and lang != _lang() else ""})
        del _ASB_EVENTS[:-50]
    # asbplayer enseña esto como nombre de la tarjeta exportada
    return {"result": "→ LinguaMiner", "error": None}


def _asb_record(s: dict, idx: int, note_id: int, frase: str):
    """La línea en Netflix → asbplayer graba audio e imagen y los añade a la
    nota que ya creó LinguaMiner (postMineAction 2 = actualizar esa nota)."""
    import time
    segs = json.loads(s["transcript_json"])
    m = _asb_media(s["media_path"].split(":", 1)[1] if ":" in s["media_path"] else None)
    target = {"mediaId": m["id"]} if m else {}
    asbws.HUB.call("seek-timestamp", {"timestamp": segs[idx]["start"] + 0.05, **target})
    time.sleep(0.6)                       # que el vídeo llegue antes de minar «la actual»
    r = asbws.HUB.call("mine-subtitle", {"postMineAction": 2, "noteId": note_id,
                                         "fields": {"Frase": ankiproxy.esc(frase)},
                                         **target}, timeout=8) or {}
    if not r.get("published"):
        raise asbws.AsbError("not-published")


def _asb_after_card(session_id: str, idx: int, cid: str, has_audio: bool,
                    frase: str) -> str:
    """Tras crear la tarjeta de una sesión de Netflix: «captured» (ya lleva el
    audio de la tecla), «requested» (asbplayer la está grabando), «pending»
    (Anki cerrado: no hay nota a la que añadirlo) u «offline»."""
    s = db.get_session(CON, session_id)
    if not s or s.get("source_type") != "asbplayer":
        return ""
    if has_audio:
        return "captured"
    note_id = db.card_note_id(CON, cid)
    if not note_id:
        return "pending"
    if not asbws.HUB.connected:
        return "offline"
    try:
        _asb_record(s, idx, note_id, frase)
        return "requested"
    except Exception as e:                              # noqa: BLE001
        _log.warning("asbplayer: grabar la línea %s: %s", idx, e)
        return "offline"


@app.websocket("/ws")
async def asbplayer_ws(ws: WebSocket):
    """Aquí se conecta asbplayer («Enable WebSocket client»). Solo desde este
    equipo y desde una extensión: una web cualquiera no puede hacerse pasar
    por asbplayer."""
    host = ws.client.host if ws.client else ""
    if (not ankiproxy.origin_allowed(ws.headers.get("origin"))
            or not (config.TRUST_ALL_CLIENTS or host in ("127.0.0.1", "::1", "testclient"))
            or not _host_allowed(ws)):
        await ws.close(code=1008)
        return
    await asbws.HUB.serve(ws)


@app.get("/api/asbplayer/status")
def asb_status():
    if not asbws.HUB.connected:
        return {"connected": False, "media": []}
    try:
        res = asbws.HUB.call("get-bound-media", timeout=3) or {}
    except asbws.AsbError:
        res = {}
    media = [{"id": m.get("id"), "title": m.get("title") or "",
              "active": bool(m.get("active")),
              "subtitles": [t.get("fileName") or "" for t in m.get("loadedSubtitles") or []]}
             for m in res.get("media") or []]
    return {"connected": True, "media": media}


class AsbOpenReq(BaseModel):
    name: str | None = None


@app.post("/api/asbplayer/open")
def asb_open(req: AsbOpenReq):
    if not asbws.HUB.connected:
        return _err("err.asb_offline", "asbplayer no está conectado", 409)
    try:
        return {"session_id": _asb_open(req.name)}
    except asbws.AsbError as e:
        if str(e) in ("no-media", "no-subtitles"):
            return _err("err.asb_no_media", "asbplayer no tiene un vídeo con subtítulos", 404)
        return _err("err.asb_offline", f"asbplayer: {e}", 502)


class AsbSeekReq(BaseModel):
    session_id: str
    segment_index: int


@app.post("/api/asbplayer/seek")
def asb_seek(req: AsbSeekReq):
    s = db.get_session(CON, req.session_id)
    if not s or s.get("source_type") != "asbplayer":
        return JSONResponse({"error": "not found"}, status_code=404)
    segs = json.loads(s["transcript_json"])
    if not 0 <= req.segment_index < len(segs):
        return _err("err.bad_segment", "línea fuera de rango", 400, (len(segs) - 1,))
    if not asbws.HUB.connected:
        return _err("err.asb_offline", "asbplayer no está conectado", 409)
    try:
        m = _asb_media(s["media_path"].split(":", 1)[1])
        asbws.HUB.call("seek-timestamp", {"timestamp": segs[req.segment_index]["start"],
                                          **({"mediaId": m["id"]} if m else {})})
    except asbws.AsbError as e:
        return _err("err.asb_offline", f"asbplayer: {e}", 502)
    return {"ok": True}


@app.get("/api/asbplayer/events")
def asb_events(after: int = -1):
    """Líneas capturadas con la tecla. after=-1: solo el contador actual (la
    interfaz empieza a escuchar desde ahí)."""
    n = _ASB_N
    if after < 0:
        return {"last": n, "events": [], "connected": asbws.HUB.connected}
    if after > n:                         # el servidor se reinició
        after = 0
    return {"last": n, "events": [e for e in list(_ASB_EVENTS) if e["n"] > after],
            "connected": asbws.HUB.connected}


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
        return {"decks": [], "error": "Anki no está abierto",
                "error_key": "err.anki_closed", "error_args": []}


class SeedReq(BaseModel):
    deck: str


@app.post("/api/words/seed-anki")
def words_seed_anki(req: SeedReq):
    if not req.deck or req.deck not in (anki.deck_names() or []):
        return _err("err.unknown_deck", "mazo desconocido")

    def work(jid):
        jobs.set_progress(jid, 0.2, "Leyendo el mazo…", key="seed.working")
        try:
            r = vocab.seed_from_anki(CON, req.deck, _lang())
        except Exception as e:          # Anki cerrado a mitad, mazo borrado…
            _log.warning("sembrado desde Anki falló: %s", e)
            raise RuntimeError("Anki dejó de responder; ábrelo e inténtalo de nuevo") from e
        jobs.set_progress(jid, 1.0, "Listo", key="job.done")
        return r

    return {"job_id": jobs.start(work, label="seed-anki")}


# ---------- export / import de progreso ----------

@app.get("/api/cards/counts")
def cards_counts():
    """Cuántas tarjetas exportaría cada opción, antes de bajar nada."""
    return {"pending": len(db.cards_for_export(CON, only_pending=True)),
            "all": len(db.cards_for_export(CON, only_pending=False))}


@app.get("/api/cards/export.apkg")
def cards_export_apkg(all: int = 0):
    """Las tarjetas en un .apkg: se importan sin AnkiConnect, también en
    AnkiDroid y AnkiMobile. Por defecto, solo las que aún no están en Anki."""
    import time

    from starlette.background import BackgroundTask

    from . import apkg
    cards = db.cards_for_export(CON, only_pending=not all)
    if not cards:
        return _err("err.no_cards", "no hay tarjetas para exportar", 404)
    tmp = Path(tempfile.mkdtemp())
    dest = tmp / f"linguaminer-{time.strftime('%Y-%m-%d')}.apkg"
    apkg.build(cards, _settings()["deck"], dest, _settings()["card_layout"],
               deck_for=lambda c: _deck_for(c.get("language")))
    return FileResponse(dest, media_type="application/octet-stream", filename=dest.name,
                        background=BackgroundTask(shutil.rmtree, tmp, True))


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
        return _err("err.no_sample", f"todavía no hay ejemplo para «{code}»",
                    args=(code,))
    r = sample.build_safe(code)
    if not r:
        return _err("err.sample_failed",
                    "no pude generar el ejemplo (¿falta la voz neural?)", 500)
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
        return _err("err.file_too_big", "archivo demasiado grande (máx. 20 MB)")
    try:
        words = wordlist.parse(raw)
    except Exception as e:                            # noqa: BLE001
        return _err("err.read_failed", f"no pude leer el archivo: {e}",
                    args=(str(e),))
    if not words:
        return _err("err.no_words", "no encontré ninguna palabra en el archivo")
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
                                      exclude_idx=index, language=_lang())}


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
    "audio_trim": bool, "ui_lang": str, "keymap": dict, "card_sentences": int,
    "card_examples": int,
    "base_language": str, "rec_min_zipf": (int, float),
    "reader_mark_known": bool, "card_layout": str, "deck_by_lang": dict,
}
_SETTING_RANGES = {"sub_scale": (0.3, 3.0), "speed_default": (0.25, 3.0),
                   "anki_port": (1, 65535), "rec_min_zipf": (0, 7),
                   "card_sentences": (1, 3), "card_examples": (0, 3)}


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
    if "card_layout" in body and body["card_layout"] not in anki.CARD_LAYOUTS:
        return JSONResponse({"error": "card_layout no soportado"}, status_code=400)
    if ("base_language" in body and body["base_language"] != "auto"
            and body["base_language"] not in languages.BASE_NAMES):
        return _err("err.base_lang", "idioma base no soportado")
    if "language" in body and body["language"] not in languages.activable():
        return _err("err.lang_unavailable", "idioma no disponible todavía")
    if "keymap" in body:
        km = {**_settings()["keymap"], **body["keymap"]}
        keys = list(km.values())
        if (set(km) - set(DEFAULT_SETTINGS["keymap"])
                or any(not (isinstance(k, str) and len(k) == 1
                            and k.isalpha()) for k in keys)
                or len(keys) != len(set(keys))):
            return _err("err.bad_keys",
                        "atajos inválidos (letras a-z, sin repetir)")
    if "deck_by_lang" in body and not all(
            isinstance(k, str) and isinstance(v, str) for k, v in body["deck_by_lang"].items()):
        return JSONResponse({"error": "tipo inválido para deck_by_lang"}, status_code=400)
    before = _settings()
    old_lang = _lang()
    saved = (json.loads(config.SETTINGS_PATH.read_text(encoding="utf-8"))
             if config.SETTINGS_PATH.exists() else {})
    for k, v in body.items():
        if k == "keymap":
            saved["keymap"] = {**saved.get("keymap", {}), **v}
        else:
            saved[k] = v
    new_lang = body.get("language", old_lang)
    by_lang = dict(saved.get("deck_by_lang") or before.get("deck_by_lang") or {})
    if new_lang != old_lang:
        # Con un solo mazo para todo, al pasar al alemán las tarjetas nuevas
        # caían en el mazo del catalán. El del idioma que se deja se guarda y
        # el nuevo recupera el suyo (o estrena uno con su nombre).
        by_lang[old_lang] = before["deck"]
        if "deck" in body:
            by_lang[new_lang] = body["deck"]
        saved["deck"] = by_lang.get(new_lang) or _default_deck(new_lang)
    if "deck" in body:
        by_lang[new_lang] = saved["deck"]
    if by_lang:
        saved["deck_by_lang"] = by_lang
    _save_settings(saved)
    if "card_layout" in body:
        # la plantilla es del tipo de nota: cambia también las tarjetas que
        # ya están en Anki. Si Anki está cerrado, se aplica al próximo envío.
        try:
            if anki.is_up(_settings().get("anki_port")):
                anki.ensure_note_type(body["card_layout"])
        except Exception:  # noqa: BLE001
            pass
    return _settings_payload()


def _default_deck(code: str) -> str:
    return f"LinguaMiner::{languages.PROFILES.get(code, {}).get('name', code)}"


def _deck_for(lang: str | None) -> str:
    """Mazo al que va una tarjeta según su idioma: las pendientes de antes de
    cambiar de idioma siguen yendo a su mazo, no al del idioma nuevo."""
    s = _settings()
    if not lang or lang == _lang():
        return s["deck"]
    return (s.get("deck_by_lang") or {}).get(lang) or s["deck"]


class DeckReq(BaseModel):
    deck: str


@app.post("/api/anki/deck")
def set_deck(req: DeckReq):
    s = _settings()
    s["deck"] = req.deck
    s["deck_by_lang"] = {**(s.get("deck_by_lang") or {}), _lang(): req.deck}
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
