"""Importar texto (.txt, .epub) como sesión de lectura.

Un libro se convierte en la misma estructura de segmentos que un subtítulo, así
que todo lo que ya existe —tokenizado, estados de palabra, recomendación i+1,
popup del diccionario, tarjetas a Anki— funciona sin tocarlo. Lo único que
cambia es que no hay tiempos: `start`/`end` llevan el índice de la frase para
que el orden y el indexado sigan siendo los de siempre.

Sin dependencias nuevas: un .epub es un zip de XHTML y la stdlib trae las dos
piezas (`zipfile`, `html.parser`).
"""
import html.parser
import re
import zipfile
from pathlib import Path

MAX_CHARS = 2_000_000        # ~1.400 páginas; por encima el navegador sufre

# Fin de frase: puntuación occidental y CJK. El punto tras una inicial ("J. R.
# R. Tolkien") o una abreviatura no debería partir, así que se exige que lo
# siguiente empiece por mayúscula o carácter CJK y que lo anterior no sea una
# sola letra.
#
# La raya de diálogo cuenta como inicio válido: en novela en español y catalán
# («—No vinc —va dir ell. —Per què no?») lo que sigue al punto es una raya, no
# una mayúscula, y sin esto el capítulo entero salía como una sola frase.
_APERTURA = "—–\\-«»\"'“”‘’¿¡("
_SENT = re.compile(
    rf"(?<=[.!?…。！？])(?=\s+[{_APERTURA}]|\s+[^\Wa-zà-öø-ÿ\d_]|\s*$)|(?<=[。！？])",
    re.UNICODE)
# No cierran frase: una inicial suelta ("J.") o una abreviatura corriente.
# La lista es corta a propósito — tratar cualquier palabra breve como
# abreviatura partiría mal "Sí. Vamos." y eso se nota más que un "EE. UU."
# suelto. Cubre lo frecuente en las lenguas que soporta la app.
_ABREV = ("ee|uu|sr|sra|srta|dr|dra|prof|av|avda|núm|num|pág|pag|cap|vol|"
          "etc|ej|pp|ss|st|mr|mrs|ms|jr|vs|no|nº|art|fig|máx|mín")
_INICIAL = re.compile(
    rf"(?:^|\s)(?:[^\W\d_]|{_ABREV})\.\s*$", re.UNICODE | re.IGNORECASE)


class _Text(html.parser.HTMLParser):
    """Texto visible de un XHTML, con salto de párrafo en los bloques."""

    _SALTO = {"p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr"}
    _MUDO = {"script", "style", "head", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.trozos: list[str] = []
        self._saltar = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._MUDO:
            self._saltar += 1
        elif tag in self._SALTO:
            self.trozos.append("\n")

    def handle_endtag(self, tag):
        if tag in self._MUDO and self._saltar:
            self._saltar -= 1
        elif tag in self._SALTO:
            self.trozos.append("\n")

    def handle_data(self, data):
        if not self._saltar:
            self.trozos.append(data)

    def texto(self) -> str:
        return "".join(self.trozos)


def _epub_text(path: Path) -> str:
    """Capítulos de un .epub, en el orden del lomo (spine).

    Se lee el spine y no el orden del zip: dentro del archivo los capítulos
    pueden ir en cualquier orden, y leerlos como salgan mezcla el libro.
    """
    with zipfile.ZipFile(path) as z:
        nombres = z.namelist()
        opf = next((n for n in nombres if n.endswith(".opf")), None)
        orden: list[str] = []
        if opf:
            raw = z.read(opf).decode("utf-8", "replace")
            base = opf.rsplit("/", 1)[0] + "/" if "/" in opf else ""
            ids = dict(re.findall(r'<item\b[^>]*id="([^"]+)"[^>]*href="([^"]+)"', raw))
            ids.update({i: h for h, i in re.findall(
                r'<item\b[^>]*href="([^"]+)"[^>]*id="([^"]+)"', raw)})
            for idref in re.findall(r'<itemref[^>]*idref="([^"]+)"', raw):
                href = ids.get(idref)
                if href:
                    from urllib.parse import unquote
                    orden.append(base + unquote(href.split("#")[0]))
        if not orden:            # sin opf legible: todo el (x)html, por nombre
            orden = sorted(n for n in nombres
                           if n.lower().endswith((".xhtml", ".html", ".htm")))
        partes = []
        for n in orden:
            if n not in nombres:
                continue
            p = _Text()
            p.feed(z.read(n).decode("utf-8", "replace"))
            partes.append(p.texto())
        return "\n\n".join(partes)


def read_text(path: Path) -> str:
    """Texto plano de un .txt o .epub."""
    if path.suffix.lower() == ".epub":
        return _epub_text(path)
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def split_sentences(text: str) -> list[str]:
    """Frases, respetando los párrafos.

    Se corta primero por párrafo: sin eso, un salto de línea en medio de un
    diálogo pega dos frases que no van juntas.
    """
    fuera: list[str] = []
    for parrafo in re.split(r"\n\s*\n+", text):
        parrafo = " ".join(parrafo.split())
        if not parrafo:
            continue
        acum = ""
        for trozo in _SENT.split(parrafo):
            if not trozo:
                continue
            acum += trozo
            # "J. R. R." no termina frase: la inicial suelta sigue abierta
            if acum.strip() and not _INICIAL.search(acum):
                fuera.append(acum.strip())
                acum = ""
        if acum.strip():
            fuera.append(acum.strip())
    return fuera


def to_segments(text: str) -> list[dict]:
    """Frases en el mismo formato que un subtítulo.

    `start`/`end` llevan el índice, no un tiempo: mantiene el orden y el
    indexado que ya usa todo el código sin inventar una segunda ruta.
    """
    frases = split_sentences(text[:MAX_CHARS])
    return [{"start": float(i), "end": float(i + 1), "text": f, "text_es": ""}
            for i, f in enumerate(frases)]


def title_from(path: Path, text: str) -> str:
    """Título del libro: el del epub si lo trae, si no el nombre del archivo."""
    if path.suffix.lower() == ".epub":
        try:
            with zipfile.ZipFile(path) as z:
                opf = next((n for n in z.namelist() if n.endswith(".opf")), None)
                if opf:
                    raw = z.read(opf).decode("utf-8", "replace")
                    m = re.search(r"<dc:title[^>]*>([^<]+)</dc:title>", raw)
                    if m and m.group(1).strip():
                        return m.group(1).strip()[:120]
        except Exception:
            pass
    del text
    return path.stem[:120]
