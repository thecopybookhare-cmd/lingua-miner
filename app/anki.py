"""AnkiConnect client with port auto-discovery.

AnkiConnect defaults to 8765, but another local service may squat that
port (it answers HTTP but not the AnkiConnect JSON shape). We probe the
candidate ports, remember the first real AnkiConnect, and expose a
diagnosis so the UI can tell the user exactly what is wrong.
"""
import base64

import requests

from . import config


class AnkiError(Exception):
    pass


_PORT: int | None = None  # discovered AnkiConnect port


def _url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def probe(port: int) -> str:
    """Return 'ok' (real AnkiConnect), 'squatted' (other service), 'down'."""
    try:
        r = requests.post(_url(port),
                          json={"action": "version", "version": 6},
                          timeout=3)
        data = r.json()
        if isinstance(data, dict) and "result" in data and "error" in data:
            return "ok"
        return "squatted"
    except Exception:
        return "down"


def find_port(preferred: int | None = None) -> tuple[int | None, dict]:
    """Locate AnkiConnect. Returns (port or None, {port: probe_result})."""
    global _PORT
    if _PORT is not None and probe(_PORT) == "ok":
        return _PORT, {str(_PORT): "ok"}
    ports = [preferred] if preferred else list(config.ANKI_PORTS)
    diag = {}
    for p in ports:
        st = probe(p)
        diag[str(p)] = st
        if st == "ok":
            _PORT = p
            return p, diag
    _PORT = None
    return None, diag


def invoke(action: str, **params):
    port = _PORT or config.ANKI_PORTS[0]
    r = requests.post(_url(port),
                      json={"action": action, "version": 6, "params": params},
                      timeout=10)
    data = r.json()
    if not (isinstance(data, dict) and "result" in data and "error" in data):
        raise AnkiError(f"port {port} is not AnkiConnect")
    if data.get("error"):
        raise AnkiError(data["error"])
    return data.get("result")


def is_up(preferred: int | None = None) -> bool:
    return find_port(preferred)[0] is not None


CARD_CSS = """.card { font-family: -apple-system, sans-serif; font-size: 22px;
text-align: center; color: #222; background: #fdfdfd; }
.front { font-size: 34px; font-weight: 700; }
.frase { margin-top: 12px; } .es { color: #666; font-size: 18px; }
.font { color: #999; font-size: 13px; margin-top: 10px; }
img { max-width: 90%; border-radius: 8px; margin-top: 10px; }"""

# Migaku-style: full context (sentence + image + audio) on the FRONT
FRONT = """<div class="front">{{Paraula}}</div>
<div class="frase">{{Frase}}</div>
{{Imatge}}<br>{{Audio}}"""
BACK = """{{FrontSide}}<hr id=answer>
<div class="es">{{ParaulaES}}</div>
<div class="es">{{FraseES}}</div>
<div class="font">{{Font}} · {{Freq}}</div>"""


def model_in_use() -> str:
    """Nombre del modelo en el Anki del usuario. Las instalaciones previas
    crearon «CatalaMiner»; si existe (y no el nuevo) se sigue usando para
    no partir la colección en dos tipos de nota."""
    names = invoke("modelNames") or []
    if config.NOTE_TYPE not in names and config.NOTE_TYPE_LEGACY in names:
        return config.NOTE_TYPE_LEGACY
    return config.NOTE_TYPE


def ensure_note_type() -> str:
    """Create the note type, or sync its templates/styling if it exists
    (so template improvements reach decks created by older versions).
    Returns the model name in use."""
    model = model_in_use()
    if model not in (invoke("modelNames") or []):
        invoke("createModel", modelName=model,
               inOrderFields=config.NOTE_FIELDS, css=CARD_CSS,
               cardTemplates=[{"Name": "Card 1", "Front": FRONT, "Back": BACK}])
        return model
    invoke("updateModelTemplates",
           model={"name": model,
                  "templates": {"Card 1": {"Front": FRONT, "Back": BACK}}})
    invoke("updateModelStyling",
           model={"name": model, "css": CARD_CSS})
    return model


def deck_names() -> list[str]:
    return invoke("deckNames") or []


def deck_words(deck: str, max_notes: int = 5000) -> list[str]:
    """Palabras del anverso de las notas de un mazo.

    Para sembrar el vocabulario que YA estudias en Anki: se lee solo el primer
    campo (el anverso suele ser la palabra/expresión), se limpia el HTML y se
    descartan las entradas largas (frases enteras, no vocabulario)."""
    import html
    import re
    ids = invoke("findNotes", query=f'"deck:{deck}"') or []
    words: list[str] = []
    for i in range(0, min(len(ids), max_notes), 200):     # por lotes
        for n in invoke("notesInfo", notes=ids[i:i + 200]) or []:
            fields = n.get("fields") or {}
            if not fields:
                continue
            first = min(fields.values(), key=lambda f: f.get("order", 0))
            raw = html.unescape(re.sub(r"<[^>]+>", " ", first.get("value") or ""))
            raw = re.sub(r"\[sound:[^\]]*\]", " ", raw).strip()
            if raw and len(raw) <= 40 and len(raw.split()) <= 3:
                words.append(raw)
    return words


def find_cards(query: str) -> list[int]:
    return invoke("findCards", query=query) or []


def cards_info(card_ids: list[int]) -> list[dict]:
    if not card_ids:
        return []
    return invoke("cardsInfo", cards=card_ids) or []


def note_intervals(note_ids: list[int]) -> dict[int, int]:
    """Max card interval (days) per note id, for status sync."""
    if not note_ids:
        return {}
    card_ids = invoke("findCards",
                      query=f'"note:{model_in_use()}"')
    infos = invoke("cardsInfo", cards=card_ids) or []
    out: dict[int, int] = {}
    wanted = set(note_ids)
    for info in infos:
        nid = info.get("note")
        if nid in wanted:
            out[nid] = max(out.get(nid, 0), int(info.get("interval") or 0))
    return out


def build_note(card: dict, deck: str, model: str | None = None) -> dict:
    return {
        "deckName": deck,
        "modelName": model or config.NOTE_TYPE,
        "fields": {
            "Paraula": card["paraula"] or "",
            "ParaulaES": card["paraula_es"] or "",
            "Frase": card["frase"] or "",
            "FraseES": card["frase_es"] or "",
            "Audio": f"[sound:{card['audio_file']}]" if card.get("audio_file") else "",
            "Imatge": f'<img src="{card["image_file"]}">' if card.get("image_file") else "",
            "Font": card.get("font") or "",
            "Freq": card.get("freq_rank") or "",
        },
        "options": {"allowDuplicate": False},
        "tags": ["lingua-miner"],
    }


def send_card(card: dict, deck: str) -> int:
    """Upload media + note. Raises AnkiError/requests errors if Anki is down."""
    model = ensure_note_type()
    if deck not in invoke("deckNames"):
        invoke("createDeck", deck=deck)
    for key in ("audio_file", "image_file"):
        name = card.get(key)
        if name:
            path = config.MEDIA_DIR / name
            if path.exists():
                invoke("storeMediaFile", filename=name,
                       data=base64.b64encode(path.read_bytes()).decode())
    return invoke("addNote", note=build_note(card, deck, model))
