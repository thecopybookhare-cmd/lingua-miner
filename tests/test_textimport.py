"""Importar texto: partir en frases y crear la sesión de lectura.

Un libro entra por el mismo camino que un subtítulo, así que lo único nuevo que
puede romperse es el corte en frases. Y ahí lo que más se nota es partir donde
no toca: si un capítulo entero sale como una sola "frase", la tarjeta lleva
tres párrafos y no sirve.
"""
import io
import zipfile

from fastapi.testclient import TestClient

import app.main as main
from app import textimport as T


def client(tmp_path):
    main.CON = main.db.connect(tmp_path / "t.db")
    return TestClient(main.app)


def _wait(jid, timeout=30):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = main.jobs.get(jid)
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise TimeoutError(jid)


# ---------- corte en frases ----------

def test_splits_on_normal_punctuation():
    assert T.split_sentences("Una cosa. Otra cosa! ¿Y esta?") == [
        "Una cosa.", "Otra cosa!", "¿Y esta?"]


def test_dialogue_dashes_start_a_sentence():
    """En novela en español y catalán lo que sigue al punto es una raya, no
    una mayúscula. Sin contemplarlo, el capítulo salía de una pieza."""
    fs = T.split_sentences("—No vinc —va dir ell. —Per què no?")
    assert len(fs) == 2 and fs[1].startswith("—Per")


def test_initials_do_not_end_a_sentence():
    assert T.split_sentences("És de J. R. R. Tolkien. És llarg.") == [
        "És de J. R. R. Tolkien.", "És llarg."]


def test_common_abbreviations_survive():
    assert T.split_sentences("Vive en EE. UU. desde 2020.") == [
        "Vive en EE. UU. desde 2020."]


def test_short_sentences_still_split():
    """El guardia de abreviaturas no puede tragarse una frase de verdad."""
    assert T.split_sentences("¿Vienes? Sí. Vamos.") == ["¿Vienes?", "Sí.", "Vamos."]


def test_cjk_punctuation():
    assert T.split_sentences("我昨天看了電影。你想做什麼？") == [
        "我昨天看了電影。", "你想做什麼？"]


def test_paragraphs_are_not_glued_together():
    """Un salto de línea dentro de un párrafo une; entre párrafos, no."""
    fs = T.split_sentences("Primera línia.\n\nSegon paràgraf que\nsegueix.")
    assert fs == ["Primera línia.", "Segon paràgraf que segueix."]


def test_segments_carry_the_index_as_time():
    """No hay tiempos, pero start/end mantienen el orden y el indexado que ya
    usa todo el código: así no hay una segunda ruta que mantener."""
    segs = T.to_segments("Una. Dos. Tres.")
    assert [s["start"] for s in segs] == [0.0, 1.0, 2.0]
    assert all(s["end"] == s["start"] + 1 for s in segs)


# ---------- epub ----------

def _epub(tmp_path, capitulos, titulo="Un libro"):
    p = tmp_path / "libro.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml" '
                        'media-type="application/xhtml+xml"/>'
                        for i in range(len(capitulos)))
        refs = "".join(f'<itemref idref="c{i}"/>' for i in range(len(capitulos)))
        z.writestr("content.opf",
                   f'<package><metadata><dc:title>{titulo}</dc:title></metadata>'
                   f"<manifest>{items}</manifest><spine>{refs}</spine></package>")
        for i, c in enumerate(capitulos):
            z.writestr(f"c{i}.xhtml", f"<html><body><p>{c}</p></body></html>")
    return p


def test_epub_text_and_title(tmp_path):
    p = _epub(tmp_path, ["Primer capítulo.", "Segundo capítulo."], "Mi novela")
    assert T.title_from(p, "") == "Mi novela"
    txt = T.read_text(p)
    assert "Primer capítulo." in txt and "Segundo capítulo." in txt


def test_epub_follows_the_spine_order(tmp_path):
    """Dentro del zip los capítulos pueden ir en cualquier orden; leerlos como
    salgan mezcla el libro."""
    p = tmp_path / "desordenado.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("content.opf",
                   '<package><manifest>'
                   '<item id="b" href="b.xhtml"/><item id="a" href="a.xhtml"/>'
                   '</manifest><spine>'
                   '<itemref idref="a"/><itemref idref="b"/>'
                   "</spine></package>")
        z.writestr("b.xhtml", "<html><body><p>SEGUNDO</p></body></html>")
        z.writestr("a.xhtml", "<html><body><p>PRIMERO</p></body></html>")
    txt = T.read_text(p)
    assert txt.index("PRIMERO") < txt.index("SEGUNDO")


def test_epub_ignores_script_and_style(tmp_path):
    p = tmp_path / "css.epub"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("c.xhtml", "<html><head><style>p{color:red}</style></head>"
                              "<body><p>Texto bueno.</p>"
                              "<script>var x=1;</script></body></html>")
    txt = T.read_text(p)
    assert "Texto bueno." in txt
    assert "color:red" not in txt and "var x" not in txt


# ---------- endpoint ----------

def test_importing_a_txt_creates_a_readable_session(tmp_path):
    c = client(tmp_path)
    data = "Ahir vaig veure una pel·lícula. Era molt bona.".encode()
    r = c.post("/api/sessions/text",
               files={"file": ("prova.txt", io.BytesIO(data), "text/plain")}).json()
    j = _wait(r["job_id"])
    assert j["status"] == "done", j.get("message")
    assert j["result"]["sentences"] == 2

    d = c.get("/api/sessions/" + j["result"]["session_id"]).json()
    assert d["source_type"] == "text"
    assert d["srt_source"] == "text"
    # lo importante: llega tokenizado, que es lo que hace clicables las palabras
    segs = d["transcript"]
    assert len(segs) == 2
    assert segs[0]["tokens"] and any(t["is_word"] for t in segs[0]["tokens"])
    # y los estados de palabra viajan igual que con un vídeo
    assert "word_statuses" in d


def test_other_extensions_are_rejected(tmp_path):
    c = client(tmp_path)
    r = c.post("/api/sessions/text",
               files={"file": ("peli.mp4", io.BytesIO(b"x"), "video/mp4")})
    assert r.status_code == 400


def test_an_empty_file_fails_with_a_message(tmp_path):
    c = client(tmp_path)
    r = c.post("/api/sessions/text",
               files={"file": ("vacio.txt", io.BytesIO(b"   \n\n  "), "text/plain")}).json()
    j = _wait(r["job_id"])
    assert j["status"] == "error"
    assert "legible" in (j.get("message") or "")


def test_text_import_is_admin_only():
    """Un invitado del modo compartir estudia, no mete archivos."""
    assert "/api/sessions/text" in main._ADMIN_POSTS


def test_title_drops_the_random_prefix(tmp_path):
    """El archivo en disco lleva un prefijo aleatorio para no pisar otros; ese
    prefijo salía en la biblioteca ("969f93-libro")."""
    p = tmp_path / "969f93-El nom de la rosa.txt"
    p.write_text("Text.", encoding="utf-8")
    assert T.title_from(p, "", "El nom de la rosa.txt") == "El nom de la rosa"
