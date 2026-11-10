import re

_TS = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")
# Anotaciones de los subtítulos para sordos: quién habla o desde dónde
# («(Handy)», «(Lisa, rufend)»), sonidos («* leises Schmatzen *», «[Musik]»,
# «♪ … ♪»). No son diálogo: salían subrayadas como palabras nuevas, se
# traducían con la frase y se podían minar.
_ANNOT = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|([*♪#])[^*♪#\n]*\1")
_DASHES = re.compile(r"^(?:\s*[-–—]\s*)+|(?:\s*[-–—]\s*)+$")


def strip_annotations(text: str) -> str:
    """El diálogo sin anotaciones: «(Handy) "Nur 19 Euro." * Er lacht. *» →
    «"Nur 19 Euro."». Quita también el guion que quedaba colgando."""
    t = " ".join(_ANNOT.sub(" ", text).split())
    t = re.sub(r"(?:\s*[-–—]\s*){2,}", " - ", t)      # «- (Lisa) -» → «-»
    return _DASHES.sub("", t).strip()


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_subtitles(text: str) -> list[dict]:
    """Parse SRT or WebVTT into [{start, end, text}]. Strips markup tags.

    Lo que viene tras una línea en blanco no es texto del cue anterior: o es
    el identificador del siguiente (en WebVTT puede ser cualquier cosa, «sub9»,
    no solo el número del SRT) o un bloque NOTE. Antes se pegaba al final de
    la frase anterior: «… gegrillt!" sub9».
    """
    segs = []
    cur = None
    held: list[str] = []       # líneas tras un blanco, a la espera de saber qué son
    after_blank = False
    for line in text.splitlines():
        m = _TS.search(line)
        if m:
            held = []          # eran el identificador de este cue
            if cur and cur["text"]:
                segs.append(cur)
            g = m.groups()
            cur = {"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": ""}
            after_blank = False
            continue
        clean = _TAG.sub("", line).strip()
        if not line.strip():
            held = []          # un bloque suelto (NOTE, STYLE…): fuera
            after_blank = True
            continue
        if cur is None or not clean or clean.isdigit():
            after_blank = False
            continue
        if (after_blank or held) and cur["text"]:
            # tras un blanco, ¿texto o identificador del cue siguiente? Se sabe
            # en la línea de después: si es un tiempo, era el identificador
            if held:
                held.append(clean)
            else:
                held = [clean]
            after_blank = False
            continue
        cur["text"] = (cur["text"] + " " + clean).strip()
        after_blank = False
    if cur and cur["text"]:
        segs.append(cur)
    out = []
    for x in segs:
        x["text"] = strip_annotations(x["text"])
        if x["text"]:
            out.append(x)
    return out


def merge_split_cues(segs: list[dict]) -> list[dict]:
    """Subtítulos troceados (HLS): una frase que cruza el corte entre dos
    trozos llega en los dos, con el tiempo recortado en cada uno. Se ordenan
    y se funden las repeticiones contiguas."""
    out: list[dict] = []
    for s in sorted(segs, key=lambda x: (x["start"], x["end"])):
        if out and s["text"] == out[-1]["text"] and s["start"] <= out[-1]["end"] + 0.5:
            out[-1]["end"] = max(out[-1]["end"], s["end"])
            continue
        out.append(dict(s))
    return out


def _strip_overlap(prev: str, cur: str) -> str:
    """Quita del inicio de `cur` el mayor sufijo de `prev` que lo prefija."""
    for k in range(min(len(prev), len(cur)), 3, -1):
        if prev[-k:] == cur[:k]:
            return cur[k:].strip()
    return cur


def clean_auto(segs: list[dict]) -> list[dict]:
    """Subtítulos automáticos de YouTube: cada cue repite la línea anterior
    (ventana rodante). Fusiona cues idénticos y recorta el solape para que
    cada frase aparezca una sola vez."""
    out: list[dict] = []
    prev_full = ""
    for s in segs:
        text = " ".join((s.get("text") or "").split())
        if not text:
            continue
        if out and text == prev_full:
            out[-1]["end"] = max(out[-1]["end"], s["end"])
            continue
        shown = _strip_overlap(prev_full, text) if prev_full else text
        prev_full = text
        if not shown:
            if out:
                out[-1]["end"] = max(out[-1]["end"], s["end"])
            continue
        out.append({**s, "text": shown})
    return out
