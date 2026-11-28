"""LinguaMiner haciendo de AnkiConnect, para minar desde Netflix con asbplayer.

Netflix no se puede descargar (DRM), pero asbplayer, una extensión abierta,
lee los subtítulos en la propia página y graba el audio y un clip de la
frase. Lo que no sabe es lo que sabe LinguaMiner: el lema, la traducción de
la palabra, la definición o tus otras frases con esa palabra.

Así que asbplayer apunta a LinguaMiner en vez de a Anki
(http://127.0.0.1:8977/ankiconnect). Las peticiones pasan tal cual a
AnkiConnect, salvo las notas del tipo LinguaMiner, que se completan antes de
llegar. Aquí están las piezas sin estado; el pegamento está en main.py.

Seguridad: AnkiConnect decide por el Origin quién puede tocar tu colección
(y pregunta en Anki la primera vez). Reenviada desde aquí, la petición ya no
lleva Origin y AnkiConnect la dejaría pasar sin preguntar, así que el filtro
se hace aquí: extensiones del navegador, la web de asbplayer y localhost.
Cualquier otra página que abras no puede usar este puente para leer o
borrar tus mazos.
"""
import html
import re

EXTENSION_SCHEMES = ("chrome-extension://", "moz-extension://",
                     "safari-web-extension://")
# asbplayer también tiene reproductor web (para vídeos locales)
WEB_ORIGINS = ("https://app.asbplayer.dev",)
_LOCAL = re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$")


def origin_allowed(origin: str | None) -> bool:
    """Sin Origin (curl, programas de escritorio) se acepta, como AnkiConnect.
    «null» (archivos locales, iframes aislados) no."""
    if origin is None:
        return True
    o = origin.strip().lower()
    return (o.startswith(EXTENSION_SCHEMES) or o in WEB_ORIGINS
            or bool(_LOCAL.match(o)))


def cors_headers(origin: str | None) -> dict:
    if not origin:
        return {}
    return {"Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Vary": "Origin"}


_BREAK = re.compile(r"(?i)<br\s*/?>|</?(div|p|li)\b[^>]*>")
_TAG = re.compile(r"<[^>]+>")
_SOUND = re.compile(r"\[sound:[^\]]*\]")
_MARK = re.compile(r"(?is)<(b|strong|u|mark|em|i)\b[^>]*>(.*?)</\1\s*>")


def plain(value) -> str:
    """Texto de un campo de Anki: sin HTML, sin [sound:…], espacios normales.
    Las etiquetas en línea se quitan sin dejar hueco («<b>Kunst</b>.» →
    «Kunst.»); los saltos de línea pasan a espacio."""
    if not isinstance(value, str):
        return ""
    v = _SOUND.sub(" ", _BREAK.sub(" ", value))
    return " ".join(html.unescape(_TAG.sub("", v)).split())


def highlighted(value) -> str:
    """La primera palabra marcada en la frase (negrita, subrayado…): en el
    diálogo de asbplayer se puede resaltar la palabra en vez de escribirla."""
    if not isinstance(value, str):
        return ""
    m = _MARK.search(value)
    return plain(m.group(2)) if m else ""


def esc(text: str) -> str:
    """Lo que pone LinguaMiner en un campo va escapado: una traducción con «<»
    no puede romper la plantilla."""
    return html.escape(text or "", quote=False)
