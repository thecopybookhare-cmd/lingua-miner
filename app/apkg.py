"""Exportar tarjetas a .apkg, para quien no usa AnkiConnect.

Crear tarjetas exigía Anki abierto con el complemento AnkiConnect: justo los
dos pasos que, según las reseñas de toda la categoría, espantan a la gente.
Un .apkg se importa abriéndolo en Anki de escritorio, AnkiDroid o AnkiMobile,
sin complementos.

Mismo tipo de nota, campos y plantillas que crea anki.py por AnkiConnect,
para que una tarjeta se vea igual llegue por donde llegue.
"""
import hashlib
from pathlib import Path

import genanki

from . import anki, config

# Identificadores fijos: Anki reconoce el tipo de nota y el mazo entre una
# exportación y otra, y cada nota lleva un guid derivado del id de la tarjeta,
# así que importar dos veces el mismo .apkg actualiza en vez de duplicar.
MODEL_ID = 1874263951


def _model(layout: str = "reading") -> genanki.Model:
    front, back = anki.templates(layout)
    return genanki.Model(
        MODEL_ID, config.NOTE_TYPE,
        fields=[{"name": f} for f in config.NOTE_FIELDS],
        templates=[{"name": "Card 1", "qfmt": front, "afmt": back}],
        css=anki.CARD_CSS)


def deck_id(name: str) -> int:
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)


def guid(card_id: str) -> str:
    return genanki.guid_for("lingua-miner", card_id)


def build(cards: list[dict], deck_name: str, dest: Path,
          layout: str = "reading", deck_for=None) -> int:
    """Escribe el .apkg en `dest` con sus audios e imágenes. Devuelve cuántas
    notas lleva. Un medio que ya no está en disco se omite: la tarjeta va
    igual, como haría AnkiConnect.

    `deck_for(card)` reparte por mazos (uno por idioma); sin él, todas van a
    `deck_name`."""
    model = _model(layout)
    decks: dict[str, genanki.Deck] = {}
    media = []
    for c in cards:
        name = (deck_for(c) if deck_for else None) or deck_name
        deck = decks.setdefault(name, genanki.Deck(deck_id(name), name))
        fields = anki.build_note(c, name)["fields"]
        deck.add_note(genanki.Note(model=model, guid=guid(c["id"]), tags=["lingua-miner"],
                                   fields=[fields[f] for f in config.NOTE_FIELDS]))
        for key in ("audio_file", "image_file"):
            name = c.get(key)
            if name and (config.MEDIA_DIR / name).is_file():
                media.append(str(config.MEDIA_DIR / name))
    pkg = genanki.Package(list(decks.values()) or genanki.Deck(deck_id(deck_name), deck_name))
    pkg.media_files = media
    pkg.write_to_file(str(dest))
    return len(cards)
