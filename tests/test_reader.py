"""El lector: pasar de página marcando el resto, modo frase y teclado.

Marcar en silencio lo que queda de la página es la mecánica central de LingQ y
también su queja más repetida: el contador crece solo y deja de ser creíble.
Aquí se marca igual, pero nunca por encima de un estado que pusiste tú, y
siempre devolviendo la lista exacta de lo que cambió — sin esa lista no hay
deshacer.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app import db

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def client(tmp_path):
    main.CON = db.connect(tmp_path / "t.db")
    return TestClient(main.app)


# ---------- marcar al pasar de página ----------

def test_page_known_marks_only_words_without_a_status(tmp_path):
    c = client(tmp_path)
    db.set_word_status(main.CON, "casa", "learning")
    db.set_word_status(main.CON, "taula", "ignored")
    r = c.post("/api/words/page-known",
               json={"lemmas": ["gos", "casa", "taula", "platja"]}).json()
    assert r["marked"] == 2
    assert sorted(r["lemmas"]) == ["gos", "platja"]
    st = db.word_statuses(main.CON)
    assert st["gos"] == st["platja"] == "known"
    assert st["casa"] == "learning"      # tu estado no se toca
    assert st["taula"] == "ignored"


def test_page_known_undo_restores_exactly_what_it_marked(tmp_path):
    c = client(tmp_path)
    db.set_word_status(main.CON, "casa", "learning")
    marcadas = c.post("/api/words/page-known",
                      json={"lemmas": ["gos", "casa"]}).json()["lemmas"]
    r = c.post("/api/words/page-known",
               json={"lemmas": marcadas, "undo": True}).json()
    assert r["marked"] == 1
    st = db.word_statuses(main.CON)
    assert "gos" not in st               # vuelve a ser nueva
    assert st["casa"] == "learning"      # nunca fue nuestra


def test_undo_leaves_alone_a_word_you_changed_afterwards(tmp_path):
    """Si marcas la palabra a mano después, deshacer no debe pisarte."""
    c = client(tmp_path)
    c.post("/api/words/page-known", json={"lemmas": ["gos"]})
    db.set_word_status(main.CON, "gos", "learning")
    r = c.post("/api/words/page-known",
               json={"lemmas": ["gos"], "undo": True}).json()
    assert r["marked"] == 0
    assert db.word_statuses(main.CON)["gos"] == "learning"


def test_page_known_normalises_and_ignores_empties(tmp_path):
    c = client(tmp_path)
    r = c.post("/api/words/page-known",
               json={"lemmas": ["  Gos ", "", "  ", "GOS"]}).json()
    assert r["lemmas"] == ["gos"]        # misma palabra, una sola vez
    assert db.word_statuses(main.CON) == {"gos": "known"}


def test_marking_is_off_by_default_and_the_api_accepts_it(tmp_path):
    c = client(tmp_path)
    assert main.DEFAULT_SETTINGS["reader_mark_known"] is False
    assert c.get("/api/settings").json()["reader_mark_known"] is False
    assert c.post("/api/settings",
                  json={"reader_mark_known": True}).status_code == 200
    assert c.get("/api/settings").json()["reader_mark_known"] is True
    # un no-booleano se rechaza, como el resto de ajustes tipados
    assert c.post("/api/settings",
                  json={"reader_mark_known": "sí"}).status_code == 400


def test_the_checkbox_writes_the_setting_the_api_knows(tmp_path):
    """El nombre del ajuste vive en dos sitios; si se separan, no persiste."""
    assert 'saveSettings({ reader_mark_known:' in APP_JS
    assert "reader_mark_known" in main.DEFAULT_SETTINGS


# ---------- teclado y modo frase ----------

def test_reader_has_its_own_keyboard_branch():
    """Los botones del lector prometen A/← y D/→ desde que existe.

    Durante dos versiones no hicieron nada: el `keydown` global salía antes de
    llegar, porque comprobaba que el reproductor estuviera visible.
    """
    assert "readerKey(e); return;" in APP_JS
    cuerpo = APP_JS[APP_JS.index("function readerKey(e)"):]
    cuerpo = cuerpo[:cuerpo.index("\nfunction ")]
    for accion in ('act === "prev"', 'act === "next"', 'act === "mine"'):
        assert accion in cuerpo, f"readerKey no atiende {accion}"
    assert "ArrowLeft" in cuerpo and "ArrowRight" in cuerpo


def test_sentence_mode_reuses_the_player_word_rendering():
    """Los colores de palabra son los del reproductor, no unos propios."""
    cuerpo = APP_JS[APP_JS.index("function renderSentence()"):]
    cuerpo = cuerpo[:cuerpo.index("\nfunction ")]
    assert "tokenHtml(seg)" in cuerpo
    assert "bindTokenEvents(" in cuerpo


def test_sentence_mode_hides_the_page_turn_switch():
    """En modo frase no existe «el resto de la página» que marcar."""
    cuerpo = APP_JS[APP_JS.index("function setReaderMode("):]
    cuerpo = cuerpo[:cuerpo.index("\nasync function ")]
    assert '$("reader-auto").hidden = frase' in cuerpo


def test_page_lemmas_are_read_before_turning():
    """Se marcan las palabras de la página que dejas, no las de la siguiente."""
    cuerpo = APP_JS[APP_JS.index("function readerGo(delta)"):]
    assert cuerpo.index("pageUnknownLemmas()") < cuerpo.index("READ_PAGE += delta")


# ---------- guardas de la interfaz ----------

def test_every_element_the_js_asks_for_exists_in_the_html():
    """`$("x")` sobre un id que no existe devuelve null y revienta al usarlo.

    Ningún test de Python ejecuta el JS, así que un id mal escrito llegaría
    entero al usuario en forma de pantalla que no responde.
    """
    ids = set(re.findall(r'id="([^"]+)"', INDEX))
    usados = set(re.findall(r'\$\("([^"]+)"\)', APP_JS))
    faltan = sorted(usados - ids)
    assert not faltan, f"app.js pide ids que no están en index.html: {faltan}"


def test_the_toast_is_not_buried_inside_the_player():
    """El aviso vivía dentro de `<main id="player">`.

    En el lector el reproductor está `hidden`, así que el aviso heredaba un
    ancestro oculto y no se veía NUNCA: ni al cambiar el estado de una
    palabra, ni el «deshacer» del marcado al pasar de página. Se veía perfecto
    en el reproductor, que es donde se probó, y por eso pasó desapercibido dos
    versiones.
    """
    import re as _re
    # sin comentarios: un `<main>` citado dentro de un <!-- --> no abre nada
    limpio = _re.sub(r"<!--.*?-->", "", INDEX, flags=_re.S)
    prof = 0
    dentro = None
    for linea in limpio.split("\n"):
        for tk in _re.findall(r"</?(?:main|div|section|aside|article|dialog)\b[^>]*>",
                              linea):
            if tk.startswith("</"):
                prof -= 1
            else:
                if 'id="toast"' in tk:
                    dentro = prof
                if not tk.endswith("/>"):
                    prof += 1
    assert dentro == 0, ("#toast está anidado dentro de otra capa "
                         f"(profundidad {dentro}); si esa capa se oculta, "
                         "el aviso deja de verse")


def test_the_undo_toast_can_actually_carry_a_button():
    """Un recuento sin marcha atrás es justo lo que no queremos copiar."""
    cabecera = APP_JS[APP_JS.index("const toast = ("):]
    cabecera = cabecera[:cabecera.index("\n};")]
    assert "accion" in cabecera and "appendChild" in cabecera
    assert 't("rd.undo")' in APP_JS
