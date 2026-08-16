"""Avisar una vez de los fallos que degradan en silencio.

La app está llena de `except Exception: return ""` a propósito: si no hay voz
neural, o no hay IPA, mejor seguir que reventar. El problema es cuando lo que
falla es una pieza CENTRAL — la traducción, el diccionario, los subtítulos —
porque el usuario ve campos vacíos y no tiene forma de saber por qué.

Esto no cambia la degradación: sigue devolviendo lo que devolvía. Solo deja
una línea en el log, una sola vez por causa, para que el informe de
diagnóstico la lleve. Tres veces en una semana un fallo silencioso costó horas
de investigación: spaCy saliendo por SystemExit, wordfreq devolviendo 0 sin
jieba y el hilo del servidor muriendo sin dejar rastro.
"""
import logging

# clave -> (mensaje para el usuario, detalle técnico). Separados a propósito:
# volcar la excepción cruda en la interfaz da avisos de seis líneas ilegibles
# (yt-dlp suelta el traceback entero dentro del mensaje).
_SEEN: dict[str, tuple[str, str]] = {}


def warn_once(key: str, msg: str, exc: BaseException | None = None) -> None:
    """Registra `msg` la primera vez que se ve `key`. Las siguientes, calla.

    La clave agrupa por causa, no por llamada: traducir 500 subtítulos con el
    motor roto tiene que dejar una línea, no quinientas.
    """
    if key in _SEEN:
        return
    detalle = "" if exc is None else f"{type(exc).__name__}: {exc}"
    _SEEN[key] = (msg, detalle)
    logging.getLogger("degradado").warning(
        "%s", msg if not detalle else f"{msg} ({detalle})")


def active() -> list[str]:
    """Lo que va degradado, en cristiano y sin la excepción.

    El log lo mira quien ya sabe que hay un problema. Esto es para que la app
    lo DIGA: si el traductor está roto, el usuario ve las tarjetas vacías y
    supone que es normal. Nadie reporta lo que cree normal.
    """
    return [msg for msg, _ in _SEEN.values()]


def details() -> list[str]:
    """Con la excepción: para el informe de diagnóstico, no para la interfaz."""
    return [f"{msg} ({det})" if det else msg for msg, det in _SEEN.values()]


def reset() -> None:
    """Solo para los tests."""
    _SEEN.clear()
