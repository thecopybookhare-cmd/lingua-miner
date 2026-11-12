from app.subs import parse_subtitles

SRT = """1
00:00:01,000 --> 00:00:02,500
Hola món

2
00:00:03,000 --> 00:00:04,000
Adeu <i>amic</i>
"""

VTT = """WEBVTT

00:01.000 --> 00:02.500
Hola món

00:00:03.000 --> 00:00:04.000
Adeu
"""


def test_parse_srt():
    segs = parse_subtitles(SRT)
    assert segs[0] == {"start": 1.0, "end": 2.5, "text": "Hola món"}
    assert segs[1]["text"] == "Adeu amic"  # tags stripped


def test_parse_vtt():
    segs = parse_subtitles(VTT)
    assert segs[0]["start"] == 1.0 and segs[0]["end"] == 2.5
    assert segs[1]["start"] == 3.0


def test_clean_auto_collapses_rolling_captions():
    # ventana rodante típica de YouTube: cada cue repite la línea anterior
    segs = [
        {"start": 0.0, "end": 2.0, "text": "hola a tothom"},
        {"start": 2.0, "end": 2.1, "text": "hola a tothom"},          # duplicado
        {"start": 2.1, "end": 4.0, "text": "hola a tothom com esteu"},
        {"start": 4.0, "end": 6.0, "text": "com esteu molt bé gràcies"},
        {"start": 6.0, "end": 6.5, "text": "   "},                    # vacío
    ]
    from app import subs as subs_mod
    out = subs_mod.clean_auto(segs)
    assert [s["text"] for s in out] == \
        ["hola a tothom", "com esteu", "molt bé gràcies"]
    assert out[0]["end"] == 2.1        # el duplicado extendió el final


# WebVTT con identificadores de texto: salía «… gegrillt!" sub9» en pantalla
VTT_IDS = """WEBVTT

NOTE generado por el sitio,
dos líneas

sub8
00:00:10.000 --> 00:00:12.000
"Die haben gerade angerufen
und mich gegrillt!"

sub9
00:00:12.500 --> 00:00:14.000 align:center
Echt?

intro-3
00:00:15.000 --> 00:00:16.000
<v Nico>Ja.
"""


def test_vtt_cue_identifiers_are_not_subtitle_text():
    segs = parse_subtitles(VTT_IDS)
    assert [s["text"] for s in segs] == [
        '"Die haben gerade angerufen und mich gegrillt!"', "Echt?", "Ja."]
    assert segs[1]["start"] == 12.5


def test_note_blocks_are_skipped():
    assert "NOTE" not in " ".join(s["text"] for s in parse_subtitles(VTT_IDS))


def test_text_after_a_blank_right_after_the_timing_is_kept():
    """SRT mal formados: tiempo, línea en blanco y luego el texto."""
    segs = parse_subtitles("1\n00:00:01,000 --> 00:00:02,000\n\nHallo\n")
    assert segs == [{"start": 1.0, "end": 2.0, "text": "Hallo"}]


def test_sound_descriptions_are_not_dialogue():
    vtt = ("WEBVTT\n\nsub0\n00:00:07.160 --> 00:00:09.160\n* fröhlicher Elektropop *\n\n"
           "sub1\n00:00:10.000 --> 00:00:11.000\n♪ Lied ♪\n\n"
           "sub2\n00:00:12.000 --> 00:00:13.000\n*seufzt* Na gut.\n")
    assert [s["text"] for s in parse_subtitles(vtt)] == ["Na gut."]


def test_hearing_impaired_annotations_are_stripped():
    from app.subs import strip_annotations as st
    assert st('(Handy) "Nur 19 Euro im Monat." * Er lacht. *') == '"Nur 19 Euro im Monat."'
    assert st("Das ist doch einfach scheiße. * leises Schmatzen *") == "Das ist doch einfach scheiße."
    assert st("(Lisa, rufend) Frank!") == "Frank!"
    assert st("[Musik] Hallo zusammen") == "Hallo zusammen"
    assert st("Ich höre dich. - (Mutter) Weißt du?") == "Ich höre dich. - Weißt du?"
    assert st("* Er stöhnt schneller. * - \"Ja, Baby...\"") == '"Ja, Baby..."'
    assert st("Ich höre dich. - \"Weißt du, wie das ist?\"") == 'Ich höre dich. - "Weißt du, wie das ist?"'
    assert st("(lacht)") == ""


def test_cue_left_empty_after_stripping_is_dropped():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n(Musik)\n\n00:00:03.000 --> 00:00:04.000\n(Lisa) Hallo\n"
    assert parse_subtitles(vtt) == [{"start": 3.0, "end": 4.0, "text": "Hallo"}]


def test_old_subtitle_sessions_are_cleaned_when_reopened(tmp_path):
    import json

    from fastapi.testclient import TestClient

    import app.main as main
    main.CON = main.db.connect(tmp_path / "t.db")
    segs = [{"start": 1, "end": 2, "text": '"… mich gegrillt!" sub9', "tokens": []},
            {"start": 3, "end": 4, "text": "(Handy) Hallo", "tokens": []},
            {"start": 5, "end": 6, "text": "* Musik *", "tokens": []}]
    sid = main.db.create_session(main.CON, language="de", title="t", source_type="stream",
                                 media_path="x", srt_source="youtube_subs", model_size="-",
                                 duration_secs=6, transcript_json=json.dumps(segs))
    tr = TestClient(main.app).get(f"/api/sessions/{sid}").json()["transcript"]
    assert [s["text"] for s in tr] == ['"… mich gegrillt!"', "Hallo", "* Musik *"], \
        "ningún segmento desaparece: las tarjetas guardan su índice"
