import json
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def _seg_session(text="Ets molt intel·ligent, tu."):
    return main.db.create_session(
        main.CON, title="V", source_type="local", media_path="/x.mp4",
        srt_source="whisper", model_size="small", duration_secs=10,
        transcript_json=json.dumps([{"start": 1.0, "end": 2.0, "text": text,
                                     "words": [], "logprob": 0.0,
                                     "tokens": []}]))


def test_senses_prefer_lemma_over_surface():
    d = main.dictionary.Dictionary(
        {"ets": [("ETS", "n")], "ser": [("ser", "vbser"), ("estar", "vblex")]})
    assert main._senses("ets", "ser", d)[0][0] == "ser"
    # multi-palabra: superficie primero
    d2 = main.dictionary.Dictionary({"poc a poc": [("despacio", "adv")]})
    assert main._senses("poc a poc", "poc a poc", d2) == [("despacio", "adv")]


def test_active_sense_matches_sentence_translation():
    senses = [("estar", "vblex"), ("perro", "n")]
    assert main._active_sense(senses, "El perro corre por ahí.", "") == 1
    assert main._active_sense(senses, "nada que ver", "perro") == 1
    assert main._active_sense(senses, "nada", "nada") == 0
    assert main._active_sense([], "x", "x") == -1


@patch("app.main.ipa.ipa", return_value="/əts/")
@patch("app.main.translate.sentence", side_effect=lambda t: "ES:" + t)
@patch("app.main.translate.translate",
       side_effect=lambda t: "eres" if t == "ets" else "T:" + t)
def test_lookup_word_es_uses_lowercase_form(_tr, _sen, _ipa, tmp_path,
                                            monkeypatch):
    from app import forms
    c = client(tmp_path)
    monkeypatch.setattr(forms, "known_exact", lambda w: False)
    monkeypatch.setattr(forms, "knows_lower", lambda w: w.lower() == "ets")
    r = c.post("/api/lookup",
               json={"selection": "Ets",
                     "sentence": "Ets molt intel·ligent, tu."}).json()
    assert r["word_es"] == "eres"
    assert r["ipa"] == "/əts/"
    assert "active" in r


def _send_all():
    """Como _flush con Anki abierto: todas las de la cola pasan a enviadas."""
    for card in main.db.pending_cards(main.CON):
        main.db.mark_card_sent(main.CON, card["id"], 1)
    return 1


@patch("app.main._flush", side_effect=_send_all)
@patch("app.main.media.animated_clip")
@patch("app.main.media.snapshot")
@patch("app.main.media.cut_audio")
@patch("app.main.translate.sentence", side_effect=lambda t: "ES:" + t)
@patch("app.main.translate.translate", side_effect=lambda t: "ES:" + t)
def test_mine_creates_and_flushes(_tr, _sen, _cut, _snap, _clip, _fl, tmp_path):
    c = client(tmp_path)
    sid = _seg_session("El gos corre")
    r = c.post("/api/cards/mine",
               json={"session_id": sid, "segment_index": 0,
                     "selection": "gos"}).json()
    assert r["sent_now"] is True
    assert r["paraula"] == "gos"
    assert r["word_status"] == "learning"
    rows = [dict(x) for x in main.CON.execute("SELECT * FROM cards")]
    assert any(cc["paraula"] == "gos" for cc in rows)


@patch("app.main._flush", return_value=0)
@patch("app.main.media.animated_clip")
@patch("app.main.media.snapshot")
@patch("app.main.media.cut_audio")
@patch("app.main.translate.sentence", side_effect=lambda t: "ES:" + t)
@patch("app.main.translate.translate", side_effect=lambda t: "ES:" + t)
def test_mine_respects_chosen_sense(_tr, _sen, _cut, _snap, _clip, _fl, tmp_path):
    c = client(tmp_path)
    sid = _seg_session("El gos corre")
    r = c.post("/api/cards/mine",
               json={"session_id": sid, "segment_index": 0,
                     "selection": "gos", "paraula_es": "perro"}).json()
    assert r["sent_now"] is False
    row = main.CON.execute("SELECT paraula_es FROM cards").fetchone()
    assert row["paraula_es"] == "perro"


@patch("app.main.anki.is_up", return_value=False)
def test_stats_local_only_when_anki_down(_up, tmp_path):
    c = client(tmp_path)
    sid = _seg_session("El gos corre")
    main.db.create_card(
        main.CON, session_id=sid, segment_index=0, paraula="gos",
        lema="gos", pos="NOUN", paraula_es="perro", frase="El gos corre",
        frase_es="El perro corre", freq_rank="common", audio_file="",
        image_file="", font="V")
    main.db.set_word_status(main.CON, "gos", "learning")
    main.db.set_word_status(main.CON, "casa", "known")
    r = c.get("/api/stats").json()
    assert r["total_cards"] == 1
    assert r["status_counts"]["learning"] == 1
    assert r["status_counts"]["known"] == 1
    assert len(r["by_month"]) == 1
    assert r["anki"] is None
