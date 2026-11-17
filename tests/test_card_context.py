"""Contexto de la tarjeta: oraciones completas y, si se quiere, más de una.

Lo pidieron en Reddit: en Yomitan ponían párrafos de dos oraciones para
entender el contexto, y aquí la tarjeta llevaba una línea de subtítulo,
que a menudo ni siquiera es una oración entera.
"""
import json

from fastapi.testclient import TestClient

import app.main as main


def _segs(*items):
    """(texto, inicio, fin)"""
    return [{"start": a, "end": b, "text": t} for t, a, b in items]


ZDF = _segs(("Ich höre dich.", 0, 2),
            ("Die Imkerei ist eine Kunst, die meist von Generation zu", 2.2, 5),
            ("Generation weitergegeben wird.", 5.1, 7),
            ('"Weißt du, wie das ist?"', 7.3, 9),
            ("Nee.", 9.2, 10))


def test_a_split_sentence_is_joined():
    assert main._context_range(ZDF, 1) == (1, 2)
    assert main._context_range(ZDF, 2) == (1, 2), "también desde la segunda mitad"
    assert main._context_range(ZDF, 0) == (0, 0)


def test_two_and_three_sentences():
    assert main._context_range(ZDF, 2, sentences=2) == (0, 2)
    assert main._context_range(ZDF, 2, sentences=3) == (0, 3)
    assert main._context_range(ZDF, 4, sentences=3) == (3, 4), "no hay siguiente"


def test_editor_buttons_add_one_line_each():
    assert main._context_range(ZDF, 3, pad_before=1) == (2, 3)
    assert main._context_range(ZDF, 3, pad_before=9, pad_after=9) == (0, 4)


def test_quotes_after_the_full_stop_still_end_the_sentence():
    assert main._ends_sentence('"Weißt du, wie das ist?"')
    assert main._ends_sentence("(Er lacht.)")
    assert not main._ends_sentence("Ich wollte...")
    assert not main._ends_sentence("Ich wollte…")
    assert main._ends_sentence("映画を見ました。")


def test_automatic_subtitles_without_punctuation_stay_one_line():
    auto = _segs(*[(f"palabras sin puntuación {i}", i * 2, i * 2 + 1.9) for i in range(10)])
    assert main._context_range(auto, 5) == (5, 5)


def test_a_long_pause_is_a_boundary():
    segs = _segs(("Hola qué tal", 0, 2), ("bien gracias.", 9, 11))
    assert main._context_range(segs, 1) == (1, 1)


def test_automatic_context_is_capped_in_time():
    segs = _segs(("Eins.", 0, 20), ("Zwei.", 20.5, 25), ("Drei.", 25.5, 45))
    lo, hi = main._context_range(segs, 1, sentences=3)
    assert (lo, hi) != (0, 2) and lo <= 1 <= hi
    assert segs[hi]["end"] - segs[lo]["start"] <= 30


def test_setting_is_validated(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    assert c.get("/api/settings").json()["card_sentences"] == 1
    assert c.post("/api/settings", json={"card_sentences": 2}).status_code == 200
    assert c.post("/api/settings", json={"card_sentences": 5}).status_code == 400
    assert c.post("/api/settings", json={"card_sentences": "2"}).status_code == 400


def test_book_card_uses_the_context(tmp_path, monkeypatch):
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    c.post("/api/settings", json={"card_sentences": 2})
    sid = main.db.create_session(main.CON, language="de", title="Buch", source_type="text",
                                 media_path="x", srt_source="-", model_size="-",
                                 duration_secs=0, transcript_json=json.dumps(ZDF))
    monkeypatch.setattr(main.piper_tts, "speak", lambda t: "")
    monkeypatch.setattr(main.translate, "sentence", lambda t: "ES:" + t)
    monkeypatch.setattr(main, "_word_info", lambda sel, txt: {
        "lemma": "kunst", "pos": "NOUN", "headword": "", "gloss_key": "kunst", "word_es": "arte"})
    p = c.post("/api/cards/preview", json={"session_id": sid, "segment_index": 1,
                                           "selection": "Kunst"}).json()
    assert p["frase"] == ("Ich höre dich. Die Imkerei ist eine Kunst, die meist von "
                          "Generation zu Generation weitergegeben wird.")
    assert p["frase_es"].startswith("ES:Ich höre dich.")


def test_video_card_text_and_audio_follow_the_context(tmp_path, monkeypatch):
    main.CON = main.db.connect(tmp_path / "t.db")
    c = TestClient(main.app)
    sid = main.db.create_session(main.CON, language="de", title="Serie", source_type="file",
                                 media_path=str(tmp_path / "v.mp4"), srt_source="srt",
                                 model_size="-", duration_secs=10,
                                 transcript_json=json.dumps(ZDF))
    cut, shot = {}, {}
    monkeypatch.setattr(main.media, "cut_audio", lambda src, a, b, dest, trim=False: cut.update(a=a, b=b))
    monkeypatch.setattr(main.media, "snapshot", lambda src, ts, dest: shot.update(ts=ts))
    monkeypatch.setattr(main.media, "animated_clip", lambda src, a, b, dest, timeout=0: shot.update(a=a, b=b))
    monkeypatch.setattr(main.translate, "sentence", lambda t: "ES")
    monkeypatch.setattr(main, "_word_info", lambda sel, txt: {
        "lemma": "kunst", "pos": "NOUN", "headword": "", "gloss_key": "kunst", "word_es": "arte"})
    p = c.post("/api/cards/preview", json={"session_id": sid, "segment_index": 1,
                                           "selection": "Kunst"}).json()
    assert p["frase"].endswith("Generation weitergegeben wird.")
    assert (cut["a"], cut["b"]) == (2.2, 7), "el audio cubre la oración entera"
    assert 2.2 <= shot["ts"] <= 5 and shot["a"] == 2.2, "la imagen es de la línea de la palabra"
