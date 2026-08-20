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
        for m in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", doc.read_text()):
            ref = m.group(1)
            if ref.startswith("http"):
                continue
            if not (doc.parent / ref).exists():
                faltan.append(f"{doc.name} -> {ref}")
    assert not faltan, "imágenes que no existen:\n  " + "\n  ".join(faltan)


def test_internal_anchors_point_somewhere():
    rotas = []
    for doc in DOCS:
        txt = doc.read_text()
        anclas = _anclas(txt)
        for m in re.finditer(r"\]\(#([^)]+)\)", txt):
            if m.group(1) not in anclas:
                rotas.append(f"{doc.name} -> #{m.group(1)}")
    assert not rotas, "anclas rotas dentro del documento:\n  " + "\n  ".join(rotas)


def test_anchors_that_cross_documents_point_somewhere():
    """El índice del tutorial se renumera a mano; el README lo enlaza."""
    rotas = []
    for doc in DOCS:
        for m in re.finditer(r"\]\(([^)#]+\.md)#([^)]+)\)", doc.read_text()):
            destino = (doc.parent / m.group(1)).resolve()
            if not destino.exists():
                rotas.append(f"{doc.name} -> {m.group(1)} (no existe)")
            elif m.group(2) not in _anclas(destino.read_text()):
                rotas.append(f"{doc.name} -> {m.group(1)}#{m.group(2)}")
    assert not rotas, "enlaces entre documentos rotos:\n  " + "\n  ".join(rotas)


def test_the_tutorial_covers_the_reader():
    """Se anuncia como «every feature»; el lector faltó tres versiones."""
    txt = (ROOT / "docs" / "tutorial.md").read_text().lower()
    for pieza in ("epub", "sentence mode", "open a book"):
        assert pieza in txt, f"el tutorial no menciona «{pieza}»"


def test_the_tutorial_sections_are_numbered_without_gaps():
    txt = (ROOT / "docs" / "tutorial.md").read_text()
    nums = [int(n) for n in re.findall(r"^## (\d+)\. ", txt, re.M)]
    assert nums == list(range(1, len(nums) + 1)), f"numeración con saltos: {nums}"
