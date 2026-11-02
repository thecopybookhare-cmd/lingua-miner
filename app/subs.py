import re

_TS = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")
_TAG = re.compile(r"<[^>]+>")


def _secs(h, m, s, ms) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_subtitles(text: str) -> list[dict]:
    """Parse SRT or WebVTT into [{start, end, text}]. Strips markup tags."""
    segs = []
    cur = None
    for line in text.splitlines():
        m = _TS.search(line)
        if m:
            if cur and cur["text"]:
                segs.append(cur)
            g = m.groups()
            cur = {"start": _secs(*g[:4]), "end": _secs(*g[4:]), "text": ""}
        elif cur is not None:
            clean = _TAG.sub("", line).strip()
            if clean and not clean.isdigit():
                cur["text"] = (cur["text"] + " " + clean).strip()
    if cur and cur["text"]:
        segs.append(cur)
    return segs


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
