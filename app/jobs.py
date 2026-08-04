"""In-memory background job registry, polled by the frontend."""
import threading
import traceback
import uuid

JOBS: dict[str, dict] = {}


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
    JOBS[jid] = {"status": "running", "progress": 0.0, "label": label,
                 "message": "", "result": None}

    def _run():
        try:
            JOBS[jid]["result"] = target(jid, *args)
            JOBS[jid]["status"] = "done"
            JOBS[jid]["progress"] = 1.0
        except Exception as e:  # surfaced to UI
            traceback.print_exc()
            JOBS[jid]["status"] = "error"
            JOBS[jid]["message"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return jid


def set_progress(jid: str, p: float, message: str = ""):
    if jid in JOBS:
        JOBS[jid]["progress"] = round(p, 3)
        if message:
            JOBS[jid]["message"] = message


def set_message(jid: str, message: str):
    if jid in JOBS and message:
        JOBS[jid]["message"] = message


def get(jid: str) -> dict | None:
    return JOBS.get(jid)
