"""In-memory background job registry, polled by the frontend."""
import threading
import traceback
import uuid

JOBS: dict[str, dict] = {}


class JobError(Exception):
    """Fallo previsible de un trabajo, con clave para que el navegador lo
    traduzca. Un `raise ValueError("…")` normal llega al usuario tal cual, en
    castellano, sea cual sea el idioma de la interfaz."""

    def __init__(self, key: str, msg: str, args: tuple | list = ()):
        super().__init__(msg)
        self.key = key
        self.msg_args = list(args)


def running_with_label(label: str) -> str | None:
    """Job en curso con esa etiqueta, si lo hay. Evita lanzar dos trabajos
    pesados sobre lo mismo (p. ej. dos Whisper a la vez sobre un video, que
    se pelean por la CPU y parecen colgados)."""
    for jid, j in JOBS.items():
        if j["status"] == "running" and j["label"] == label:
            return jid
    return None


def start(target, *args, label="") -> str:
    # cap: los jobs terminados más viejos se descartan para no crecer sin
    # límite (relevante con invitados del modo compartir lanzando streams)
    if len(JOBS) > 100:
        done = [k for k, j in JOBS.items() if j["status"] != "running"]
        for k in done[:len(JOBS) - 100]:
            del JOBS[k]
    jid = uuid.uuid4().hex[:8]
    # `message` es el texto de siempre (castellano) y sigue siendo el
    # respaldo; `key`+`args` son lo que el navegador traduce al idioma de la
    # interfaz. Sin la clave, un usuario en inglés miraba una barra en español
    # durante los tres minutos que tarda una transcripción.
    JOBS[jid] = {"status": "running", "progress": 0.0, "label": label,
                 "message": "", "key": "", "args": [], "result": None}

    def _run():
        try:
            JOBS[jid]["result"] = target(jid, *args)
            JOBS[jid]["status"] = "done"
            JOBS[jid]["progress"] = 1.0
        except Exception as e:  # surfaced to UI
            traceback.print_exc()
            JOBS[jid]["status"] = "error"
            JOBS[jid]["message"] = str(e)
            # solo JobError trae clave; el texto de una excepción cualquiera
            # se enseña tal cual, que es mejor que nada
            JOBS[jid]["key"] = getattr(e, "key", "")
            JOBS[jid]["args"] = getattr(e, "msg_args", [])

    threading.Thread(target=_run, daemon=True).start()
    return jid


def set_progress(jid: str, p: float, message: str = "", key: str = "",
                 args: tuple | list = ()):
    if jid in JOBS:
        JOBS[jid]["progress"] = round(p, 3)
        if message or key:
            JOBS[jid]["message"] = message
            JOBS[jid]["key"] = key
            JOBS[jid]["args"] = list(args)


def set_message(jid: str, message: str, key: str = "",
                args: tuple | list = ()):
    if jid in JOBS and (message or key):
        JOBS[jid]["message"] = message
        JOBS[jid]["key"] = key
        JOBS[jid]["args"] = list(args)


def get(jid: str) -> dict | None:
    return JOBS.get(jid)
