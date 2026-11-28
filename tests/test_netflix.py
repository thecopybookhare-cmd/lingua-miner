"""Netflix desde LinguaMiner: asbplayer conectado por WebSocket hace de grabadora.

- El episodio llega como sesión (get-subtitles) y tocar una línea hace saltar
  Netflix (seek-timestamp).
- Ctrl+Shift+Z en Netflix (exportar sin palabra) no va a Anki: la línea, con
  su audio y su imagen, se marca en la sesión y la interfaz salta a ella.
- Una tarjeta de una línea sin capturar pide a asbplayer que grabe esa línea
  y la añada a la nota (mine-subtitle, postMineAction 2, noteId).
"""
import base64
import json
import threading

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as main
from app import anki, asbws, config

EXT = "chrome-extension://hkledmpjpaehamkiehglnbelcpdflcab"
TRACK = "Génesis S01E01 Episodio 1 - ca - Catalán [CC].nfimsc"
CUES = [
    {"text": "Va.\nDigues-ne una.", "start": 477_000, "end": 479_500, "track": 0},
    {"text": "Que comenci amb Guérard.", "start": 544_000, "end": 546_000, "track": 0},
    {"text": "Saps qui és, no?", "start": 546_200, "end": 548_000, "track": 0},
]


class FakeHub:
    """asbplayer conectado, con un vídeo de Netflix y sus subtítulos."""

    def __init__(self, cues=CUES, published=True):
        self.connected = True
        self.cues = cues
        self.published = published
        self.calls = []

    def call(self, method, params=None, timeout=5.0):
        self.calls.append((method, params or {}))
        if method == "get-bound-media":
            return {"media": [{"id": "m1", "type": "streaming", "title": "Netflix",
                               "active": True,
                               "loadedSubtitles": [{"trackNumber": 0, "fileName": TRACK}]}]}
        if method == "get-subtitles":
            return {"subtitles": self.cues}
        if method == "mine-subtitle":
            return {"published": self.published}
        return {}

    def methods(self):
        return [m for m, _ in self.calls]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MEDIA_DIR", tmp_path / "media")
    config.MEDIA_DIR.mkdir()
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    c.post("/api/settings", json={"language": "ca"})
    monkeypatch.setattr(main.translate, "sentence", lambda t: "ES")
    monkeypatch.setattr(main, "_word_info", lambda sel, frase: {
        "lemma": sel.lower(), "pos": "VERB", "headword": "", "gloss_key": sel.lower(),
        "word_es": "es"})
    monkeypatch.setattr(main, "_definition_text", lambda *a: "")
    monkeypatch.setattr(main.nlp, "zipf", lambda w: 4.0)
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(main, "_ASB_EVENTS", [])
    monkeypatch.setattr(main, "_ASB_N", 0)
    # Anki cerrado salvo que el test diga otra cosa: la tecla no lo necesita
    monkeypatch.setattr(anki, "find_port", lambda p=None: (None, {}))
    return c


def _offline(monkeypatch):
    hub = FakeHub()
    hub.connected = False
    monkeypatch.setattr(asbws, "HUB", hub)
    return hub


def _online(monkeypatch, **kw):
    hub = FakeHub(**kw)
    monkeypatch.setattr(asbws, "HUB", hub)
    return hub


def _capture(c, frase="Que comenci amb Guérard.<br>Saps qui és, no?",
             source=f"{TRACK} (00h09m05.4s)"):
    """Lo que manda asbplayer con Ctrl+Shift+Z: sin palabra, con audio e imagen."""
    body = {"action": "addNote", "version": 6, "params": {"note": {
        "deckName": "Netflix", "modelName": config.NOTE_TYPE_LEGACY, "tags": [],
        "fields": {"Frase": frase, "Font": source},
        "options": {"allowDuplicate": True},
        "audio": {"filename": "asbp_x.mp3", "data": base64.b64encode(b"MP3").decode(),
                  "fields": ["Audio"]},
        "picture": {"filename": "asbp_x.jpeg", "data": base64.b64encode(b"JPG").decode(),
                    "fields": ["Imatge"]}}}}
    return c.post("/ankiconnect", content=json.dumps(body),
                  headers={"Origin": EXT, "Content-Type": "text/plain"})


def _session(sid):
    s = main.db.get_session(main.CON, sid)
    return s, json.loads(s["transcript_json"])


# ---------- piezas ----------

def test_source_and_title_from_asbplayer():
    assert main._asb_source(f"{TRACK} (00h09m05.4s)") == (TRACK, 545.4)
    assert main._asb_source("sin hora") == ("sin hora", None)
    assert main._asb_title(TRACK) == "Génesis S01E01 Episodio 1"
    assert main._asb_title("Dark S01E01.srt") == "Dark S01E01"
    assert main._asb_track_lang(TRACK) == "ca"


# ---------- la tecla en Netflix ----------

def test_the_key_sends_the_line_to_linguaminer_not_to_anki(env, monkeypatch):
    _offline(monkeypatch)
    forwarded = []
    monkeypatch.setattr(anki, "forward", lambda *a: forwarded.append(a))
    r = _capture(env)
    assert r.json() == {"result": "→ LinguaMiner", "error": None}
    assert forwarded == [], "ni hace falta Anki abierto"
    ev = env.get("/api/asbplayer/events?after=0").json()["events"]
    (e,) = ev
    s, segs = _session(e["session_id"])
    assert s["title"] == "Génesis S01E01 Episodio 1" and s["source_type"] == "asbplayer"
    seg = segs[e["segment_index"]]
    assert seg["text"] == "Que comenci amb Guérard. Saps qui és, no?"
    assert (config.MEDIA_DIR / seg["audio_file"]).read_bytes() == b"MP3"
    assert (config.MEDIA_DIR / seg["image_file"]).read_bytes() == b"JPG"
    assert seg["audio_file"].startswith("asb-"), "la limpieza de previews no lo toca"
    assert e["track_lang"] == "", "subtítulos en catalán y estudias catalán"


def test_a_typed_word_still_goes_straight_to_anki(env, monkeypatch):
    _offline(monkeypatch)
    sent = []
    monkeypatch.setattr(anki, "find_port", lambda p=None: (8765, {}))
    monkeypatch.setattr(anki, "forward", lambda payload, pref=None: sent.append(payload)
                        or {"result": 1, "error": None})
    body = {"action": "addNote", "version": 6, "params": {"note": {
        "deckName": "N", "modelName": config.NOTE_TYPE,
        "fields": {"Paraula": "comenci", "Frase": "Que comenci."}}}}
    env.post("/ankiconnect", content=json.dumps(body), headers={"Origin": EXT})
    assert len(sent) == 1
    assert env.get("/api/asbplayer/events?after=0").json()["events"] == []


def test_with_asbplayer_connected_the_whole_episode_comes(env, monkeypatch):
    _online(monkeypatch)
    _capture(env)
    (e,) = env.get("/api/asbplayer/events?after=0").json()["events"]
    s, segs = _session(e["session_id"])
    assert [x["text"] for x in segs] == ["Va. Digues-ne una.", "Que comenci amb Guérard.",
                                         "Saps qui és, no?"]
    assert e["segment_index"] == 1, "la línea que sonaba en 9:05"
    assert segs[1]["audio_file"] and "audio_file" not in segs[0]
    assert all(x["tokens"] for x in segs)


def test_capturing_the_same_line_twice_does_not_duplicate_it(env, monkeypatch):
    _offline(monkeypatch)
    _capture(env)
    _capture(env)
    evs = env.get("/api/asbplayer/events?after=0").json()["events"]
    assert len(evs) == 2 and evs[0]["session_id"] == evs[1]["session_id"]
    _, segs = _session(evs[0]["session_id"])
    assert len(segs) == 1


def test_subtitles_in_another_language_are_flagged(env, monkeypatch):
    _offline(monkeypatch)
    env.post("/api/settings", json={"language": "fr"})
    _capture(env)
    (e,) = env.get("/api/asbplayer/events?after=0").json()["events"]
    assert e["track_lang"] == "ca"


def test_events_start_from_now_and_survive_a_restart(env, monkeypatch):
    _offline(monkeypatch)
    _capture(env)
    assert env.get("/api/asbplayer/events").json()["last"] == 1
    assert env.get("/api/asbplayer/events?after=1").json()["events"] == []
    assert len(env.get("/api/asbplayer/events?after=99").json()["events"]) == 1


# ---------- el episodio en LinguaMiner ----------

def test_open_the_episode_and_seek(env, monkeypatch):
    hub = _online(monkeypatch)
    sid = env.post("/api/asbplayer/open", json={}).json()["session_id"]
    s, segs = _session(sid)
    assert len(segs) == 3 and [x["para"] for x in segs] == [0, 1, 2]
    assert env.post("/api/asbplayer/seek", json={"session_id": sid,
                                                 "segment_index": 2}).json() == {"ok": True}
    assert hub.calls[-1] == ("seek-timestamp", {"timestamp": 546.2, "mediaId": "m1"})


def test_reopening_keeps_the_captured_lines(env, monkeypatch):
    _online(monkeypatch)
    _capture(env)
    sid = env.post("/api/asbplayer/open", json={}).json()["session_id"]
    _, segs = _session(sid)
    assert segs[1]["audio_file"]


def test_open_without_asbplayer_says_so(env, monkeypatch):
    _offline(monkeypatch)
    r = env.post("/api/asbplayer/open", json={})
    assert r.status_code == 409 and r.json()["error_key"] == "err.asb_offline"
    hub = _online(monkeypatch, cues=[])
    assert env.post("/api/asbplayer/open", json={}).json()["error_key"] == "err.asb_no_media"
    assert hub.methods()[-1] == "get-subtitles"


# ---------- tarjetas ----------

def _sent_with_note_id(monkeypatch, note_id=777):
    def flush():
        for card in main.db.pending_cards(main.CON):
            main.db.mark_card_sent(main.CON, card["id"], note_id)
        return 1
    monkeypatch.setattr(main, "_flush", flush)


def test_card_of_a_captured_line_carries_its_audio_and_image(env, monkeypatch):
    hub = _online(monkeypatch)
    _sent_with_note_id(monkeypatch)
    _capture(env)
    (e,) = env.get("/api/asbplayer/events?after=0").json()["events"]
    sid, idx = e["session_id"], e["segment_index"]
    p = env.post("/api/cards/preview", json={"session_id": sid, "segment_index": idx,
                                             "selection": "comenci"}).json()
    _, segs = _session(sid)
    assert p["audio_file"] == segs[idx]["audio_file"]
    assert p["image_file"] == segs[idx]["image_file"]
    assert p["font"] == "Génesis S01E01 Episodio 1 @ 9:04"
    r = env.post("/api/cards", json={**{k: p[k] for k in (
        "paraula", "lema", "pos", "paraula_es", "frase", "frase_es", "audio_file",
        "image_file", "font")}, "session_id": sid, "segment_index": idx}).json()
    assert r["netflix"] == "captured"
    assert "mine-subtitle" not in hub.methods(), "ya tiene su audio"


def test_card_of_another_line_asks_asbplayer_to_record_it(env, monkeypatch):
    hub = _online(monkeypatch)
    _sent_with_note_id(monkeypatch, 777)
    sid = env.post("/api/asbplayer/open", json={}).json()["session_id"]
    r = env.post("/api/cards/mine", json={"session_id": sid, "segment_index": 0,
                                          "selection": "Digues"}).json()
    assert r["netflix"] == "requested"
    seek, mine = hub.calls[-2], hub.calls[-1]
    assert seek == ("seek-timestamp", {"timestamp": 477.05, "mediaId": "m1"})
    assert mine[0] == "mine-subtitle"
    assert mine[1]["postMineAction"] == 2 and mine[1]["noteId"] == 777
    assert mine[1]["mediaId"] == "m1" and mine[1]["fields"]["Frase"]


def test_without_anki_or_asbplayer_the_card_still_saves(env, monkeypatch):
    _online(monkeypatch)
    sid = env.post("/api/asbplayer/open", json={}).json()["session_id"]
    monkeypatch.setattr(main, "_flush", lambda: 0)          # Anki cerrado
    r = env.post("/api/cards/mine", json={"session_id": sid, "segment_index": 0,
                                          "selection": "Digues"}).json()
    assert r["netflix"] == "pending" and r["pending"] == 1
    _sent_with_note_id(monkeypatch)
    asbws.HUB.connected = False
    r = env.post("/api/cards/mine", json={"session_id": sid, "segment_index": 2,
                                          "selection": "Saps"}).json()
    assert r["netflix"] == "offline"


def test_other_sessions_do_not_talk_to_asbplayer(env, monkeypatch):
    hub = _online(monkeypatch)
    sid = main.db.create_session(main.CON, title="t", source_type="text", media_path="x",
                                 srt_source="text", model_size="-", duration_secs=1,
                                 transcript_json=json.dumps([{"start": 0, "end": 1,
                                                              "text": "Hola", "tokens": []}]),
                                 language="ca")
    cid = main.db.create_card(main.CON, session_id=sid, segment_index=0, paraula="Hola",
                              lema="hola", pos="", paraula_es="", frase="Hola", frase_es="",
                              freq_rank="", audio_file="", image_file="", font="")
    assert main._asb_after_card(sid, 0, cid, False, "Hola") == ""
    assert hub.calls == []


# ---------- la conexión ----------

def test_web_pages_cannot_pose_as_asbplayer(env):
    with pytest.raises(WebSocketDisconnect):
        with env.websocket_connect("/ws", headers={"Origin": "https://evil.example"}) as ws:
            ws.receive_text()


def test_guests_cannot_open_or_seek():
    assert {"/api/asbplayer/open", "/api/asbplayer/seek"} <= main._ADMIN_POSTS


def test_real_hub_ping_and_a_call(env, monkeypatch):
    """El hub de verdad, con asbplayer simulado al otro lado del WebSocket."""
    hub = asbws.Hub()
    monkeypatch.setattr(asbws, "HUB", hub)
    with env.websocket_connect("/ws", headers={"Origin": EXT}) as ws:
        ws.send_text("PING")
        assert ws.receive_text() == "PONG"
        assert hub.connected
        out = {}

        def server_side():
            out["r"] = hub.call("get-bound-media", timeout=3)
        t = threading.Thread(target=server_side)
        t.start()
        req = json.loads(ws.receive_text())
        assert req["jsonrpc"] == "2.0" and req["method"] == "get-bound-media"
        ws.send_text(json.dumps({"jsonrpc": "2.0", "id": req["id"],
                                 "result": {"media": []}}))
        t.join(5)
        assert out["r"] == {"media": []}
    for _ in range(50):
        if not hub.connected:
            break
        threading.Event().wait(0.05)
    assert not hub.connected
    with pytest.raises(asbws.NotConnected):
        hub.call("get-bound-media")
