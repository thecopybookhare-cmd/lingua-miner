import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main

SRT = """1
00:00:01,000 --> 00:00:02,500
Hola món

2
00:00:03,000 --> 00:00:04,000
Adeu amic
"""


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def _session(tmp_path, transcript="[]"):
    return main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x.mp4",
        srt_source="none", model_size="-", duration_secs=10,
        transcript_json=transcript)


@patch("app.main.translate.translate", side_effect=lambda t: "ES:" + t)
def test_lookup_returns_senses_and_translations(_tr, tmp_path):
    c = client(tmp_path)
    # las acepciones son español→catalán: hay que pedir base española (desde
    # v1.12 el valor por defecto es "auto", que sin interfaz en español da en)
    c.post("/api/settings", json={"base_language": "es"})
    main._DICT = main.dictionary.Dictionary({"gos": [("perro", "n")]})
    r = c.post("/api/lookup", json={"selection": "gos",
                                    "sentence": "El gos corre"}).json()
    assert r["senses"] == [{"es": "perro", "pos": "n"}]
    assert r["word_es"] == "ES:gos"
    assert r["sentence_es"] == "ES:El gos corre"
    assert r["lemma"] == "gos"
    assert "freq_rank" in r and "zipf" in r


def test_attach_subtitles_tokenizes_and_saves(tmp_path):
    c = client(tmp_path)
    sid = _session(tmp_path)
    r = c.post(f"/api/sessions/{sid}/subtitles",
               files={"file": ("v.srt", SRT.encode(), "text/plain")}).json()
    assert r["segments"] == 2
    s = main.db.get_session(main.CON, sid)
    segs = json.loads(s["transcript_json"])
    assert segs[0]["text"] == "Hola món"
    assert segs[0]["tokens"]  # tokenized
    assert s["srt_source"] == "srt"


@patch("app.main.anki.send_card")
@patch("app.main.anki.is_up", return_value=True)
def test_flush_skips_duplicates_and_continues(_up, send, tmp_path):
    from app import anki as anki_mod
    from app import db as db_mod
    c = client(tmp_path)
    sid = _session(tmp_path)
    for w in ("u", "dos"):
        db_mod.create_card(main.CON, session_id=sid, segment_index=0,
                           paraula=w, lema=w, pos="", paraula_es="",
                           frase="f", frase_es="", freq_rank="",
                           audio_file="", image_file="", font="")
    send.side_effect = [anki_mod.AnkiError("cannot create note because it is a duplicate"), 42]
    r = c.post("/api/anki/flush").json()
    assert r["sent"] == 1 and r["pending"] == 0
    statuses = {x["paraula"]: x["status"] for x in main.CON.execute(
        "SELECT paraula,status FROM cards").fetchall()}
    assert statuses == {"u": "duplicate", "dos": "sent"}


@patch("app.main.translate.translate", side_effect=lambda t: "ES:" + t)
def test_segment_translate_caches(_tr, tmp_path):
    c = client(tmp_path)
    segs = [{"start": 0, "end": 1, "text": "Hola món", "words": [],
             "logprob": 0.0, "tokens": []}]
    sid = _session(tmp_path, json.dumps(segs))
    r = c.post(f"/api/sessions/{sid}/segments/0/translate").json()
    assert r["text_es"] == "ES:Hola món"
    # cached in DB now
    s = main.db.get_session(main.CON, sid)
    assert json.loads(s["transcript_json"])[0]["text_es"] == "ES:Hola món"
    # second call served from cache (translate not called again)
    with patch("app.main.translate.translate") as tr2:
        r2 = c.post(f"/api/sessions/{sid}/segments/0/translate").json()
        assert r2["text_es"] == "ES:Hola món"
        tr2.assert_not_called()


def test_session_detail_retokenizes_old_transcripts(tmp_path):
    c = client(tmp_path)
    sid = main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x.mp4",
        srt_source="srt", model_size="-", duration_secs=10,
        transcript_json=json.dumps([{"start": 0.0, "end": 1.0,
                                     "text": "El gos corre", "words": [],
                                     "logprob": 0.0, "tokens": []}]))
    body = c.get("/api/sessions/" + sid).json()
    assert body["tok_version"] == main.nlp.TOK_VERSION
    words = [t["t"] for t in body["transcript"][0]["tokens"] if t["is_word"]]
    assert "gos" in words
