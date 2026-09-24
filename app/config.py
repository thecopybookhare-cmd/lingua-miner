import os
import sys
from pathlib import Path

PORT = 8977
# AnkiConnect default port is 8765, but on this machine another local
# service can squat it — we probe candidates and remember the winner.
ANKI_PORTS = (8765, 8766, 8767)
# En Docker, Anki corre en el anfitrión y 127.0.0.1 es el propio contenedor:
# la imagen pone host.docker.internal.
ANKI_HOST = os.environ.get("LINGUAMINER_ANKI_HOST", "127.0.0.1")
# En Docker las peticiones del navegador llegan desde la puerta de enlace de
# la red del contenedor, nunca desde 127.0.0.1, así que la puerta de
# invitados trataba a todo el mundo como invitado y nadie podía administrar.
# Con esto el control de acceso pasa a ser el puerto publicado
# (-p 127.0.0.1:8977:8977). Solo lo activa la imagen de Docker.
TRUST_ALL_CLIENTS = os.environ.get("LINGUAMINER_TRUST_ALL_CLIENTS", "") == "1"


def default_app_dir(platform: str | None = None) -> Path:
    """Directorio de datos según el SO (multiplataforma). Las instalaciones
    previas (cuando la app se llamaba CatalaMiner) se migran renombrando la
    carpeta; si no se puede (otro proceso la usa), se sigue usando la vieja.
    LINGUAMINER_DIR lo sobreescribe (tests / instalaciones portables)."""
    plat = platform or sys.platform
    if plat == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif plat.startswith("win"):
        base = Path(os.environ.get("APPDATA")
                    or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME")
                    or Path.home() / ".local" / "share")
    new, old = base / "LinguaMiner", base / "CatalaMiner"
    if not new.exists() and old.exists():
        try:
            old.rename(new)
        except OSError:
            return old
    return new


APP_DIR = Path(os.environ.get("LINGUAMINER_DIR")
               or os.environ.get("CATALAMINER_DIR")    # compat instalaciones previas
               or default_app_dir())
MEDIA_DIR = APP_DIR / "media"
SETTINGS_PATH = APP_DIR / "settings.json"    # única fuente: main y languages la comparten
DL_DIR = APP_DIR / "downloads"
MODELS_DIR = APP_DIR / "models"
DB_PATH = APP_DIR / "app.db"

for d in (APP_DIR, MEDIA_DIR, DL_DIR, MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# HF models cached inside our app dir, not ~/.cache
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))

WHISPER_MODELS = {
    "catala-large": "projecte-aina/faster-whisper-large-v3-ca-3catparla",
    "large-v3": "large-v3",
    "small": "small",
}
DEFAULT_WHISPER = "catala-large"

TRANSLATE_REPO = "softcatala/translate-cat-spa"
# Bilingual dictionary: the repo ships it as .metadix (same XML structure
# with a few extra tags: <g>, <j/>, <v>) — we parse it directly.
BIDIX_URL = ("https://raw.githubusercontent.com/apertium/apertium-spa-cat/"
             "master/apertium-spa-cat.spa-cat.metadix")
# Diccionario de formas flexionadas de Softcatalà (LanguageTool):
# 1,3M líneas "forma lema ETIQUETA" — form->lemma para corregir a spaCy.
FORMS_URL = ("https://raw.githubusercontent.com/Softcatala/catalan-dict-tools/"
             "master/resultats/lt/diccionari.txt")

NOTE_TYPE = "LinguaMiner"
NOTE_TYPE_LEGACY = "CatalaMiner"      # instalaciones previas: no partir la colección
NOTE_FIELDS = ["Paraula", "ParaulaES", "Frase", "FraseES",
               "Audio", "Imatge", "Font", "Freq"]
