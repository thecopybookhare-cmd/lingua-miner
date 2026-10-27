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


def _model() -> genanki.Model:
    return genanki.Model(
        MODEL_ID, config.NOTE_TYPE,
        fields=[{"name": f} for f in config.NOTE_FIELDS],
        templates=[{"name": "Card 1", "qfmt": anki.FRONT, "afmt": anki.BACK}],
        css=anki.CARD_CSS)


def deck_id(name: str) -> int:
    return int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)


def guid(card_id: str) -> str:
    return genanki.guid_for("lingua-miner", card_id)


def build(cards: list[dict], deck_name: str, dest: Path) -> int:
    """Escribe el .apkg en `dest` con sus audios e imágenes. Devuelve cuántas
    notas lleva. Un medio que ya no está en disco se omite: la tarjeta va
    igual, como haría AnkiConnect."""
    model = _model()
    deck = genanki.Deck(deck_id(deck_name), deck_name)
    media = []
    for c in cards:
        fields = anki.build_note(c, deck_name)["fields"]
        deck.add_note(genanki.Note(model=model, guid=guid(c["id"]), tags=["lingua-miner"],
                                   fields=[fields[f] for f in config.NOTE_FIELDS]))
        for key in ("audio_file", "image_file"):
            name = c.get(key)
            if name and (config.MEDIA_DIR / name).is_file():
                media.append(str(config.MEDIA_DIR / name))
    pkg = genanki.Package(deck)
    pkg.media_files = media
    pkg.write_to_file(str(dest))
    return len(cards)
