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

_SEEN: set[str] = set()


def warn_once(key: str, msg: str, exc: BaseException | None = None) -> None:
    """Registra `msg` la primera vez que se ve `key`. Las siguientes, calla.

    La clave agrupa por causa, no por llamada: traducir 500 subtítulos con el
    motor roto tiene que dejar una línea, no quinientas.
    """
    if key in _SEEN:
        return
    _SEEN.add(key)
    log = logging.getLogger("degradado")
    if exc is None:
        log.warning("%s", msg)
    else:
        log.warning("%s (%s: %s)", msg, type(exc).__name__, exc)


def reset() -> None:
    """Solo para los tests."""
    _SEEN.clear()
