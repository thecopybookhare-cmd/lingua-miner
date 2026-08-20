from app import youtube


def test_progress_dash_fragments():
    # 3cat / HLS: total_bytes ausente, pero hay fragmentos
    frac, clave, args = youtube.progress_of({
        "status": "downloading", "total_bytes": None,
        "total_bytes_estimate": 507860.0, "downloaded_bytes": 5_000_000,
        "fragment_index": 379, "fragment_count": 758})
    assert abs(frac - 0.9 * 379 / 758) < 1e-6         # por fragmentos
    assert clave == "job.dl_frag"
    assert args == (50, 379, 758)


def test_progress_http_total_bytes():
    frac, clave, args = youtube.progress_of({
        "status": "downloading", "total_bytes": 1000, "downloaded_bytes": 500})
    assert abs(frac - 0.9 * 0.5) < 1e-6
    assert clave == "job.dl_pct"
    assert args == (50,)


def test_progress_estimate_only():
    frac, _, _ = youtube.progress_of({
        "status": "downloading", "total_bytes_estimate": 1000,
        "downloaded_bytes": 250})
    assert abs(frac - 0.9 * 0.25) < 1e-6


def test_progress_unknown_total_shows_mb():
    # ni total ni fragmentos -> sin fracción, pero mensaje con MB
    frac, clave, args = youtube.progress_of({
        "status": "downloading", "downloaded_bytes": 2_500_000})
    assert frac is None
    assert clave == "job.dl_mb"
    assert args == ("2.5",)


def test_progress_finished_phase():
    frac, clave, _ = youtube.progress_of({"status": "finished"})
    assert frac == 0.9
    assert clave == "job.preparing"


def test_every_progress_key_has_a_translation():
    """La clave que manda el servidor tiene que existir en i18n.js.

    Si no, `t()` devuelve la propia clave y la barra de progreso enseña
    literalmente «job.dl_pct» mientras se descarga un vídeo.
    """
    import ast
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    i18n = (raiz / "static" / "i18n.js").read_text(encoding="utf-8")
    traducidas = set(re.findall(r'"([\w.]+)":\s*"', i18n))

    faltan = []
    for py in sorted((raiz / "app").rglob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if not (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("set_progress", "set_message")):
                continue
            for k in n.keywords:
                if k.arg == "key" and isinstance(k.value, ast.Constant):
                    if k.value.value not in traducidas:
                        faltan.append(f"{py.name}:{n.lineno} -> {k.value.value}")
    assert not faltan, "claves de progreso sin traducir:\n  " + "\n  ".join(faltan)
