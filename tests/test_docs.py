"""Enlaces e imágenes de la documentación.

El README y el tutorial son la primera pantalla del proyecto para alguien que
llega de Reddit. Una imagen que no existe sale como un icono roto, y un ancla
mal escrita lleva a la nada — las dos cosas pasan solas al renumerar secciones
o al renombrar una captura, y ningún test las veía.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def _anclas(texto: str) -> set[str]:
    """Las que genera GitHub: minúsculas, sin puntuación, espacios a guiones."""
    return {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-")
            for h in re.findall(r"^#{1,6} (.+)$", texto, re.M)}


def test_every_image_in_the_docs_exists():
    faltan = []
    for doc in DOCS:
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            ref = m.group(1)
            if ref.startswith("http"):
                continue
            if not (doc.parent / ref).exists():
                faltan.append(f"{doc.name} -> {ref}")
    assert not faltan, "imágenes que no existen:\n  " + "\n  ".join(faltan)


def test_internal_anchors_point_somewhere():
    rotas = []
    for doc in DOCS:
        txt = doc.read_text(encoding="utf-8")
        anclas = _anclas(txt)
        for m in re.finditer(r"\]\(#([^)]+)\)", txt):
            if m.group(1) not in anclas:
                rotas.append(f"{doc.name} -> #{m.group(1)}")
    assert not rotas, "anclas rotas dentro del documento:\n  " + "\n  ".join(rotas)


def test_anchors_that_cross_documents_point_somewhere():
    """El índice del tutorial se renumera a mano; el README lo enlaza."""
    rotas = []
    for doc in DOCS:
        for m in re.finditer(r"\]\(([^)#]+\.md)#([^)]+)\)", doc.read_text(encoding="utf-8")):
            destino = (doc.parent / m.group(1)).resolve()
            if not destino.exists():
                rotas.append(f"{doc.name} -> {m.group(1)} (no existe)")
            elif m.group(2) not in _anclas(destino.read_text(encoding="utf-8")):
                rotas.append(f"{doc.name} -> {m.group(1)}#{m.group(2)}")
    assert not rotas, "enlaces entre documentos rotos:\n  " + "\n  ".join(rotas)


def test_the_tutorial_covers_the_reader():
    """Se anuncia como «every feature»; el lector faltó tres versiones."""
    txt = (ROOT / "docs" / "tutorial.md").read_text(encoding="utf-8").lower()
    for pieza in ("epub", "sentence mode", "open a book"):
        assert pieza in txt, f"el tutorial no menciona «{pieza}»"


def test_the_tutorial_sections_are_numbered_without_gaps():
    txt = (ROOT / "docs" / "tutorial.md").read_text(encoding="utf-8")
    nums = [int(n) for n in re.findall(r"^## (\d+)\. ", txt, re.M)]
    assert nums == list(range(1, len(nums) + 1)), f"numeración con saltos: {nums}"


def test_no_text_file_is_read_without_saying_utf8():
    """En Windows, `read_text()` sin encoding usa cp1252 y revienta.

    Pasó de verdad: los tests de esta misma página cascaron en CI de Windows
    con UnicodeDecodeError, y el audit destapó que la importación de YouTube
    leía así los subtítulos — un `.vtt` catalán o alemán tumbaba el trabajo
    entero en Windows, mientras que en Mac y Linux no se notaba nada.
    """
    import ast

    faltan = []
    for py in [*(ROOT / "app").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]:
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not (isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr in ("read_text", "write_text")):
                continue
            # `textimport.read_text(path)` es nuestro y ya prueba varios
            # encodings; el de pathlib no lleva argumentos posicionales
            if nodo.func.attr == "read_text" and nodo.args:
                continue
            if not any(k.arg == "encoding" for k in nodo.keywords):
                faltan.append(f"{py.relative_to(ROOT)}:{nodo.lineno}"
                              f" -> {nodo.func.attr}() sin encoding")
    assert not faltan, ("lecturas de texto sin utf-8 explícito:\n  "
                        + "\n  ".join(faltan))
