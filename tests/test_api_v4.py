import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


# ---------- sesiones por URL ----------

def _wait_job(jid, timeout=10):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = main.jobs.get(jid)
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise TimeoutError(jid)


@patch("app.main.media.duration", return_value=120.5)
def test_url_session_streams_directly(_dur, tmp_path):
    c = client(tmp_path)
    url = "https://cdn.example.com/videos/merli.mp4?token=abc"
    r = c.post("/api/sessions/url", json={"url": url}).json()
    j = _wait_job(r["job_id"])
    assert j["status"] == "done", j["message"]
    sid = j["result"]["session_id"]
    d = c.get("/api/sessions/" + sid).json()
    assert d["source_type"] == "url"
    assert d["media_url"] == url            # streaming directo, sin proxy
    assert d["title"] == "merli.mp4"
    assert d["duration_secs"] == 120.5


@patch("app.main.media.duration", return_value=0.0)
def test_url_session_rejects_unreadable(_dur, tmp_path):
    c = client(tmp_path)
    r = c.post("/api/sessions/url",
               json={"url": "https://example.com/nada.mp4"}).json()
    j = _wait_job(r["job_id"])
    assert j["status"] == "error"
    assert "no es un video directo" in j["message"]


def test_url_session_rejects_non_http(tmp_path):
    c = client(tmp_path)
    r = c.post("/api/sessions/url", json={"url": "file:///etc/passwd"})
    assert r.status_code == 400


# ---------- configuración ----------

def test_settings_defaults_and_merge(tmp_path):
    c = client(tmp_path)
    s = c.get("/api/settings").json()
    assert s["deck"] == "LinguaMiner::Mining"
    assert s["keymap"]["next"] == "d"
    # POST parcial: cambia una clave y una tecla, el resto persiste
    r = c.post("/api/settings",
               json={"sub_scale": 1.3, "keymap": {"next": "l"}}).json()
    assert r["sub_scale"] == 1.3
    assert r["keymap"]["next"] == "l"
    assert r["keymap"]["prev"] == "a"      # intacta
    assert c.get("/api/settings").json()["sub_scale"] == 1.3


def test_settings_expose_whisper_models_of_active_language(tmp_path):
    c = client(tmp_path)
    s = c.get("/api/settings").json()
    # catalán activo por defecto: su perfil incluye el modelo AINA
    assert "catala-large" in s["whisper_models"]
    assert s["default_whisper"] == "catala-large"
    # con alemán activo el modelo catalán ya no se ofrece
    c.post("/api/settings", json={"language": "de"})
    s = c.get("/api/settings").json()
    assert "catala-large" not in s["whisper_models"]
    assert s["default_whisper"] == "large-v3"
    c.post("/api/settings", json={"language": "ca"})


def test_transcribe_rejects_model_of_other_language(tmp_path, monkeypatch):
    c = client(tmp_path)
    sid = main.db.create_session(main.CON, title="x", source_type="upload",
                                 media_path="/nope.mp4", srt_source="none",
                                 model_size="-", duration_secs=0,
                                 transcript_json="[]")
    c.post("/api/settings", json={"language": "de"})
    r = c.post(f"/api/sessions/{sid}/transcribe", json={"model": "catala-large"})
    assert r.status_code == 400
    c.post("/api/settings", json={"language": "ca"})


def test_base_language_selectable_and_gated(tmp_path):
    c = client(tmp_path)
    from app import languages, translate
    # catalán ofrece base español + inglés
    s = c.get("/api/settings").json()
    assert {b["code"] for b in s["bases"]} == {"es", "en"}
    assert s["base_language_effective"] == "es"
    # cambiar a base inglés: el traductor apunta al par ca→en y se ocultan
    # las fuentes en español (acepciones/glosas)
    c.post("/api/settings", json={"base_language": "en"})
    assert languages.base_code() == "en"
    assert languages.translate_spec()["repo"] == "gaudi/opus-mt-ca-en-ctranslate2"
    assert translate.model_dir().name == "translate-cat-eng"
    assert languages.spanish_sources_active() is False
    # base desconocida → 400
    assert c.post("/api/settings", json={"base_language": "zz"}).status_code == 400
    c.post("/api/settings", json={"base_language": "es"})


def test_base_language_falls_back_when_unavailable(tmp_path):
    c = client(tmp_path)
    from app import languages
    # elegir base inglés con catalán, luego cambiar a un idioma sin esa base
    c.post("/api/settings", json={"base_language": "en", "language": "ca"})
    assert languages.base_code() == "en"
    # (si algún idioma no tuviera la base en, base_code caería a es; ca sí la tiene)
    assert "en" in languages.bases("ca")
    c.post("/api/settings", json={"base_language": "es", "language": "ca"})


def test_sources_follow_study_language(tmp_path):
    """Cada idioma ofrece sus fuentes públicas (descubrir sin saberse URLs)."""
    c = client(tmp_path)
    seen = {}
    for code in ("ca", "pt", "de"):
        c.post("/api/settings", json={"language": code})
        seen[code] = [x["name"] for x in c.get("/api/settings").json()["sources"]]
    c.post("/api/settings", json={"language": "ca"})
    assert "3Cat" in seen["ca"] and "RTP Play" in seen["pt"]
    assert seen["ca"] != seen["pt"] != seen["de"]
    # todas con url https y tipo conocido
    from app import languages
    for prof in languages.PROFILES.values():
        for src in prof.get("sources", []):
            assert src["url"].startswith("https://"), src
            assert src["kind"] in ("tv", "pod", "archive"), src


def test_rec_min_zipf_setting(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/settings").json()["rec_min_zipf"] == 3.5
    assert c.post("/api/settings", json={"rec_min_zipf": 4.5}).status_code == 200
    assert c.get("/api/settings").json()["rec_min_zipf"] == 4.5
    # fuera de rango [0,7] → 400
    assert c.post("/api/settings", json={"rec_min_zipf": 9}).status_code == 400
    assert c.post("/api/settings", json={"rec_min_zipf": "x"}).status_code == 400


def test_settings_rejects_bad_keymap_and_unknown(tmp_path):
    c = client(tmp_path)
    # tecla duplicada con otra acción
    assert c.post("/api/settings",
                  json={"keymap": {"next": "a"}}).status_code == 400
    assert c.post("/api/settings", json={"invent": 1}).status_code == 400


# ---------- ejemplos / tts / define ----------

def _mk_session(title, text, lemma):
    return main.db.create_session(
        main.CON, title=title, source_type="local", media_path="/x.mp4",
        srt_source="srt", model_size="-", duration_secs=10,
        transcript_json=json.dumps([{
            "start": 1.0, "end": 2.0, "text": text, "text_es": "",
            "words": [], "logprob": 0.0,
            "tokens": [{"t": text.split()[0], "lemma": lemma, "pos": "NOUN",
                        "is_word": True, "zipf": 4.0}]}]))


def test_examples_from_own_content_excludes_current(tmp_path):
    c = client(tmp_path)
    sid_a = _mk_session("A", "El gos corre", "gos")
    _mk_session("B", "Un gos petit", "gos")
    r = c.get(f"/api/examples?lemma=gos&session_id={sid_a}&index=0").json()
    texts = [e["text"] for e in r["examples"]]
    assert "Un gos petit" in texts
    assert "El gos corre" not in texts          # frase actual excluida


@patch("app.piper_tts.speak", return_value="")      # sin voz neural
@patch("app.tts.shutil.which", return_value=None)   # sin espeak
def test_tts_degrades_without_any_voice(_which, _piper, tmp_path):
    c = client(tmp_path)
    assert c.get("/api/tts?text=gos").json() == {"file": ""}


def test_define_gated_by_online_setting(tmp_path):
    c = client(tmp_path)
    # online_enabled False por defecto -> ni siquiera hace la peticion
    assert c.get("/api/define?word=gos").json() == {"text": ""}


@patch("requests.get")
def test_define_extracts_catalan_section(mock_get, tmp_path):
    c = client(tmp_path)
    c.post("/api/settings", json={"online_enabled": True})
    mock_get.return_value.json.return_value = {
        "query": {"pages": {"1": {"extract":
            "== Català ==\nNom. Animal domèstic.\n== Espanyol ==\notro"}}}}
    r = c.get("/api/define?word=gos").json()
    assert "Animal domèstic" in r["text"]
    assert "otro" not in r["text"]


# ---------- export / import ----------

def test_export_import_roundtrip(tmp_path):
    c = client(tmp_path)
    main.db.set_word_status(main.CON, "gos", "known")
    main.db.set_word_status(main.CON, "casa", "learning")
    exp = c.get("/api/words/export")
    assert "attachment" in exp.headers["content-disposition"]
    data = exp.json()
    assert data["statuses"] == {"gos": "known", "casa": "learning"}

    # DB nueva: importar restaura
    main.CON = main.db.connect(tmp_path / "t2.db")
    r = c.post("/api/words/import",
               json={"statuses": data["statuses"]}).json()
    assert r["imported"] == 2 and r["skipped"] == 0
    assert main.db.word_statuses(main.CON) == data["statuses"]


def test_import_respects_local_without_overwrite(tmp_path):
    c = client(tmp_path)
    main.db.set_word_status(main.CON, "gos", "known")
    r = c.post("/api/words/import",
               json={"statuses": {"gos": "ignored", "nou": "learning",
                                  "malo": "invent"}}).json()
    assert r["imported"] == 1                      # solo "nou"
    assert r["skipped"] == 2                       # gos (local) + malo (inválido)
    assert main.db.word_statuses(main.CON)["gos"] == "known"


# ---------- vocabulario (Language Reactor) ----------

def test_vocab_ranks_lemmatizes_and_caches(monkeypatch):
    from app import forms, vocab
    monkeypatch.setattr(vocab, "_RANKS", {})
    monkeypatch.setattr(forms, "lookup",
                        lambda w: [("ser", "VERB")] if w in ("és", "sóc") else [])
    monkeypatch.setattr("wordfreq.top_n_list",
                        lambda lang, n: ["és", "sóc", "casa"])
    r = vocab.ranks()
    assert r["ser"] == 1          # primera aparición gana ("sóc" no lo pisa)
    assert r["casa"] == 3
    assert "sóc" not in r


def test_bulk_known_respects_existing(tmp_path, monkeypatch):
    from app import vocab
    monkeypatch.setattr(vocab, "_RANKS", {"ca": {"ser": 1, "casa": 2, "gos": 3}})
    c = client(tmp_path)
    main.db.set_word_status(main.CON, "casa", "learning")
    r = c.post("/api/words/bulk-known", json={"top_n": 2}).json()
    assert r["marked"] == 1                       # solo "ser"
    st = main.db.word_statuses(main.CON)
    assert st["ser"] == "known"
    assert st["casa"] == "learning"               # intacta
    assert "gos" not in st                        # rango 3 > top_n 2


# ---------- biblioteca instantanea + backup ----------

def test_session_meta_cache_invalidates_on_status_change(tmp_path):
    c = client(tmp_path)
    _mk_session("V", "El gos corre", "gos")
    r1 = c.get("/api/sessions").json()[0]
    assert r1["new_words"] == 1 and r1["comp_pct"] == 0
    # segunda carga: viene de cache (mismo resultado)
    assert c.get("/api/sessions").json()[0]["new_words"] == 1
    # cambiar estado invalida la cache
    main.db.set_word_status(main.CON, "gos", "known")
    r2 = c.get("/api/sessions").json()[0]
    assert r2["comp_pct"] == 100 and r2["new_words"] == 0


def test_backup_daily_creates_and_prunes(tmp_path):
    from app import db as adb
    con = adb.connect(tmp_path / "app.db")
    adb.set_word_status(con, "gos", "known")
    # 9 backups falsos antiguos
    bdir = tmp_path / "backups"
    bdir.mkdir()
    for i in range(9):
        (bdir / f"app-2026010{i}.db").write_bytes(b"x")
    adb.backup_daily(con, tmp_path)
    files = sorted(p.name for p in bdir.glob("app-*.db"))
    assert len(files) == 7                        # podado a 7
    assert files[-1].startswith("app-2026")       # incluye el de hoy
    # el backup es una DB valida con los datos
    import sqlite3 as s3
    bcon = s3.connect(str(bdir / files[-1]))
    assert bcon.execute("SELECT status FROM word_status").fetchone()[0] == "known"


# ---------- wikdict (glosas Wikcionario offline) ----------

def test_wikdict_build_and_lookup(tmp_path, monkeypatch):
    import sqlite3

    from app import wikdict
    sample = "\n".join([
        '{"word": "gos", "pos": "noun", "senses": [{"glosses": ["Perro, animal doméstico."]}]}',
        '{"word": "gos", "pos": "noun", "senses": [{"glosses": ["Perro, animal doméstico."]}]}',
        '{"word": "casa", "pos": "noun", "senses": [{"glosses": ["Casa, vivienda."]}]}',
        'linea rota no json',
    ])
    dbp = tmp_path / "wik.sqlite"
    wikdict.build(sample, dbp)
    monkeypatch.setattr(wikdict, "_CON",
                        sqlite3.connect(str(dbp), check_same_thread=False))
    monkeypatch.setattr(wikdict, "_TRIED", True)
    monkeypatch.setattr(wikdict, "_LANG", "ca")
    assert wikdict.lookup("gos") == [("Perro, animal doméstico.", "noun")]  # dedupe
    assert wikdict.lookup("GOS")[0][0].startswith("Perro")
    assert wikdict.lookup("zzz") == []


@patch("app.main.ipa.ipa", return_value="")
@patch("app.main.translate.sentence", side_effect=lambda t: "ES:" + t)
@patch("app.main.translate.translate", side_effect=lambda t: "ES:" + t)
def test_lookup_includes_glosses(_tr, _sen, _ipa, tmp_path, monkeypatch):
    from app import wikdict
    monkeypatch.setattr(wikdict, "lookup",
                        lambda t: [("Perro.", "noun")] if t == "gos" else [])
    c = client(tmp_path)
    r = c.post("/api/lookup",
               json={"selection": "gos", "sentence": "El gos corre"}).json()
    assert r["glosses"] == [{"es": "Perro.", "pos": "noun"}]


# ---------- multi-idioma ----------

def test_word_status_migration_preserves_data(tmp_path):
    import sqlite3

    from app import db as adb
    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.executescript("""
    CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL,
      source_type TEXT NOT NULL, media_path TEXT NOT NULL,
      srt_source TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'ca',
      model_size TEXT NOT NULL, duration_secs REAL,
      transcript_json TEXT NOT NULL, created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL);
    CREATE TABLE cards (id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
      segment_index INTEGER NOT NULL, paraula TEXT NOT NULL,
      lema TEXT NOT NULL, pos TEXT, paraula_es TEXT, frase TEXT NOT NULL,
      frase_es TEXT, freq_rank TEXT, audio_file TEXT, image_file TEXT,
      font TEXT, anki_note_id INTEGER, status TEXT NOT NULL DEFAULT 'pending',
      created_at TEXT NOT NULL);
    CREATE TABLE word_status (lemma TEXT PRIMARY KEY, status TEXT NOT NULL,
      updated_at TEXT NOT NULL);
    INSERT INTO word_status VALUES ('gos', 'known', '2026-07-01T00:00:00');
    INSERT INTO word_status VALUES ('casa', 'learning', '2026-07-01T00:00:00');
    """)
    old.commit()
    old.close()
    con = adb.connect(path)                       # migra al conectar
    assert adb.word_statuses(con) == {"gos": "known", "casa": "learning"}
    # la PK compuesta permite el mismo lema en otro idioma
    adb.set_word_status(con, "gos", "learning", "fr")
    assert adb.word_statuses(con, "fr") == {"gos": "learning"}
    assert adb.word_statuses(con)["gos"] == "known"   # ca intacto


def test_language_fr_selectable(tmp_path):
    c = client(tmp_path)
    s = c.get("/api/settings").json()
    frs = [lang for lang in s["languages"] if lang["code"] == "fr"]
    assert frs and frs[0]["available"] is True
    assert c.post("/api/settings", json={"language": "fr"}).status_code == 200
    assert c.get("/api/settings").json()["language"] == "fr"
    assert c.post("/api/settings", json={"language": "ca"}).status_code == 200
    # un idioma sin perfil configurado sigue rechazándose
    assert c.post("/api/settings", json={"language": "zz"}).status_code == 400


# ---------- asistente de primer arranque ----------

def test_setup_status_shape(tmp_path):
    c = client(tmp_path)
    r = c.get("/api/setup-status").json()
    assert set(r) == {"checks", "ready", "has_sessions"}
    assert "ffmpeg" in r["checks"] and "anki" in r["checks"]
    assert r["has_sessions"] is False       # DB nueva, sin sesiones


# ---------- modo compartir ----------

def test_share_status_and_qr(tmp_path):
    c = client(tmp_path)
    r = c.get("/api/share/status").json()
    assert r["running"] is False and r["port"] == 8978
    qr = c.get("/api/share/qr", params={"url": "http://192.168.1.5:8978"})
    assert qr.status_code == 200
    assert "svg" in qr.headers["content-type"]
    assert b"<svg" in qr.content


@patch("app.main.wikdict.lookup", return_value=[])
@patch("app.main.forms.lookup", return_value=[])
@patch("app.main._dict")
@patch("app.main.translate.download")
@patch("app.main.translate.is_downloaded", return_value=False)
def test_setup_download_runs_job(_isdl, _dl, _d, _f, _w, tmp_path):
    c = client(tmp_path)
    r = c.post("/api/setup/download").json()
    j = _wait_job(r["job_id"])
    assert j["status"] == "done", j.get("message")
    assert j["result"] == {"ok": True}
    _dl.assert_called_once()                # descargó el traductor (no estaba)


# ---------- desfase de subtítulos (offset) en el audio de tarjeta ----------

def test_offset_shifts_card_audio(tmp_path, monkeypatch):
    main.CON = main.db.connect(tmp_path / "t.db")
    segs = [{"start": 10.0, "end": 12.0, "text": "hola"}]
    sid = main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x/v.mp4",
        srt_source="whisper", model_size="small", duration_secs=20,
        transcript_json=json.dumps(segs))
    cap = {}
    monkeypatch.setattr(main.media, "cut_audio",
                        lambda *a, **k: cap.__setitem__("audio", (a, k)))
    monkeypatch.setattr(main.media, "snapshot",
                        lambda *a, **k: cap.__setitem__("snap", a))
    monkeypatch.setattr(main.media, "animated_clip", lambda *a, **k: None)
    monkeypatch.setattr(main.nlp, "analyze_selection", lambda *a: ("hola", "INTJ"))
    monkeypatch.setattr(main.nlp, "zipf", lambda w: 5.0)
    monkeypatch.setattr(main.nlp, "freq_badge", lambda z: "common")
    monkeypatch.setattr(main, "_senses", lambda *a: [])
    monkeypatch.setattr(main, "_active_sense", lambda *a: 0)
    monkeypatch.setattr(main.translate, "sentence", lambda t: "hola-es")
    monkeypatch.setattr(main, "_word_es", lambda *a: "hola-es")
    s = main.db.get_session(main.CON, sid)
    main._build_preview(s, 0, "hola", offset=1.5)
    args, _ = cap["audio"]                 # (src, start, end, out)
    assert abs(args[1] - 11.5) < 1e-6      # 10 + 1.5
    assert abs(args[2] - 13.5) < 1e-6      # 12 + 1.5
    assert abs(cap["snap"][1] - 12.5) < 1e-6   # punto medio 11 + 1.5


# ---------- revisión Fable: gate de invitados y robustez ----------

def test_guest_gate_helpers():
    from types import SimpleNamespace as NS
    local = NS(client=NS(host="127.0.0.1"), headers={})
    guest = NS(client=NS(host="192.168.1.77"), headers={})
    assert main._is_local_client(local) is True
    assert main._is_local_client(guest) is False

    def mk(h):
        return NS(headers={"host": h})
    assert main._host_allowed(mk("localhost:8977"))
    assert main._host_allowed(mk("127.0.0.1:8977"))
    assert main._host_allowed(mk("192.168.1.20:8978"))       # LAN
    assert main._host_allowed(mk("100.101.1.2:8978"))        # tailnet CGNAT
    assert main._host_allowed(mk("mimac.tail1234.ts.net"))   # MagicDNS
    assert not main._host_allowed(mk("evil.example.com"))    # DNS rebinding
    assert not main._host_allowed(mk("8.8.8.8"))


# ---------- borrado de sesiones ----------

def _mk_local_session(media_path="/x.mp4"):
    return main.db.create_session(
        main.CON, title="V", source_type="local", media_path=media_path,
        srt_source="none", model_size="-", duration_secs=1,
        transcript_json="[]")


def test_delete_session_removes_session_and_cards(tmp_path):
    c = client(tmp_path)
    sid = _mk_local_session()
    main.db.create_card(
        main.CON, session_id=sid, segment_index=0, paraula="gos", lema="gos",
        pos="NOUN", paraula_es="perro", frase="El gos", frase_es="El perro",
        freq_rank="common", audio_file="a.mp3", image_file="i.jpg",
        font="V @ 0:01")
    assert c.delete("/api/sessions/" + sid).json()["ok"]
    assert main.db.get_session(main.CON, sid) is None
    assert main.CON.execute("SELECT COUNT(*) FROM cards WHERE session_id=?",
                            (sid,)).fetchone()[0] == 0
    # segunda vez: ya no existe
    assert c.delete("/api/sessions/" + sid).status_code == 404


def test_delete_session_guest_forbidden(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    sid = _mk_local_session()
    guest = TestClient(main.app, client=("192.168.1.77", 5000))
    assert guest.delete("/api/sessions/" + sid).status_code == 403
    assert main.db.get_session(main.CON, sid) is not None   # no se borró


def test_delete_session_cleans_media(tmp_path, monkeypatch):
    c = client(tmp_path)
    dl, md = tmp_path / "dl", tmp_path / "media"
    dl.mkdir()
    md.mkdir()
    monkeypatch.setattr(main.config, "DL_DIR", dl)
    monkeypatch.setattr(main.config, "MEDIA_DIR", md)
    vid = dl / "clip.mp4"
    vid.write_bytes(b"x")
    sid = _mk_local_session(str(vid))
    thumb = md / f"thumb-{sid}.jpg"
    thumb.write_bytes(b"x")
    failed = md / f"thumb-{sid}.failed"
    failed.write_bytes(b"")
    assert c.delete("/api/sessions/" + sid).json()["ok"]
    assert not vid.exists()          # descargado en DL_DIR -> se borra
    assert not thumb.exists()
    assert not failed.exists()


def test_delete_session_keeps_external_media(tmp_path, monkeypatch):
    c = client(tmp_path)
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(main.config, "DL_DIR", dl)
    ext = tmp_path / "outside.mp4"
    ext.write_bytes(b"x")
    sid = _mk_local_session(str(ext))
    assert c.delete("/api/sessions/" + sid).json()["ok"]
    assert ext.exists()              # fuera de DL_DIR: no se toca


def test_delete_session_keeps_url_media(tmp_path, monkeypatch):
    c = client(tmp_path)
    dl = tmp_path / "dl"
    dl.mkdir()
    monkeypatch.setattr(main.config, "DL_DIR", dl)
    sid = main.db.create_session(
        main.CON, title="U", source_type="url",
        media_path="https://cdn.example.com/v.mp4", srt_source="none",
        model_size="-", duration_secs=1, transcript_json="[]")
    assert c.delete("/api/sessions/" + sid).json()["ok"]   # URL: nada que borrar


def test_mine_rejects_bad_segment_index(tmp_path):
    c = client(tmp_path)
    sid = main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x/v.mp4",
        srt_source="whisper", model_size="small", duration_secs=10,
        transcript_json=json.dumps([{"start": 0, "end": 2, "text": "hola"}]))
    for idx in (-1, 1, 99):
        r = c.post("/api/cards/mine", json={
            "session_id": sid, "segment_index": idx, "selection": "hola"})
        assert r.status_code == 400, idx
    r = c.post("/api/cards/preview", json={
        "session_id": sid, "segment_index": -1, "selection": "hola"})
    assert r.status_code == 400


def test_settings_type_validation(tmp_path):
    c = client(tmp_path)
    assert c.post("/api/settings", json={"sub_scale": "grande"}).status_code == 400
    assert c.post("/api/settings", json={"speed_default": 99}).status_code == 400
    assert c.post("/api/settings", json={"dual_default": 1}).status_code == 400
    assert c.post("/api/settings", json={"deck": 42}).status_code == 400
    assert c.post("/api/settings", json={"ui_lang": "de"}).status_code == 400
    assert c.post("/api/settings", json={"sub_scale": 1.2}).status_code == 200


def test_sessions_filtered_by_language(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    kw = dict(source_type="local", media_path="/x.mp4", srt_source="none",
              model_size="-", duration_secs=1, transcript_json="[]")
    main.db.create_session(main.CON, title="CA", language="ca", **kw)
    main.db.create_session(main.CON, title="FR", language="fr", **kw)
    assert {s["title"] for s in main.db.list_sessions(main.CON, "ca")} == {"CA"}
    assert {s["title"] for s in main.db.list_sessions(main.CON, "fr")} == {"FR"}
    assert len(main.db.list_sessions(main.CON)) == 2


# ---------- reanudar + búsqueda en subtítulos ----------

def test_resume_position_roundtrip(tmp_path):
    c = client(tmp_path)
    sid = main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x.mp4",
        srt_source="none", model_size="-", duration_secs=200,
        transcript_json="[]")
    assert c.get("/api/sessions/" + sid).json()["resume_pos"] == 0
    assert c.post(f"/api/sessions/{sid}/position", json={"pos": 87.5}).json()["ok"]
    assert c.get("/api/sessions/" + sid).json()["resume_pos"] == 87.5
    # aparece en la lista de la biblioteca (para la barra de progreso)
    assert any(s["resume_pos"] == 87.5 for s in c.get("/api/sessions").json())


def test_subtitle_search(tmp_path):
    c = client(tmp_path)
    tj = json.dumps([{"start": 3.0, "end": 5.0, "text": "Bon dia a tothom"},
                     {"start": 9.0, "end": 11.0, "text": "El camí és llarg"}])
    main.db.create_session(
        main.CON, title="Cap1", source_type="local", media_path="/x.mp4",
        srt_source="srt", model_size="-", duration_secs=20, transcript_json=tj)
    r = c.get("/api/search?q=bon dia").json()["results"]
    assert len(r) == 1 and r[0]["hits"][0]["index"] == 0
    # acento-insensible: 'cami' encuentra 'camí'
    r2 = c.get("/api/search?q=cami").json()["results"]
    assert r2 and r2[0]["hits"][0]["index"] == 1
    # consulta corta -> vacío
    assert c.get("/api/search?q=a").json()["results"] == []


def test_languages_available_en_de(tmp_path):
    c = client(tmp_path)
    langs = {lang["code"]: lang["available"] for lang in
             c.get("/api/settings").json()["languages"]}
    for code in ("ca", "fr", "en", "de", "pt"):
        assert langs.get(code) is True, code
    # cambiar a inglés y a alemán es válido
    assert c.post("/api/settings", json={"language": "en"}).status_code == 200
    assert c.post("/api/settings", json={"language": "de"}).status_code == 200


def test_portuguese_profile_and_translator_spec(tmp_path):
    c = client(tmp_path)
    from app import languages
    # portugués es activable pese a no tener CT2 pre-hecho (se convierte del zip)
    assert "pt" in languages.activable()
    c.post("/api/settings", json={"language": "pt"})
    assert languages.active_code() == "pt"
    # solo base español (el modelo romance itc-itc no hace pt→en)
    assert languages.bases("pt") == ["es"]
    spec = languages.translate_spec()
    assert spec["zip"].endswith(".zip") and spec["token"] == ">>spa<<"
    assert spec["dir"] == "translate-por-spa"
    c.post("/api/settings", json={"language": "ca"})


def test_translate_download_routes_zip_to_converter(tmp_path, monkeypatch):
    """Para un idioma con translate_zip, download() convierte (no snapshot)."""
    from app import languages, translate
    monkeypatch.setattr(languages, "active_code", lambda: "pt")
    monkeypatch.setattr(languages, "base_code", lambda: "es")
    calls = {}
    monkeypatch.setattr(translate, "_download_and_convert",
                        lambda url, dest: calls.setdefault("zip", url))
    translate.download()
    assert "zip" in calls and calls["zip"].endswith(".zip")
