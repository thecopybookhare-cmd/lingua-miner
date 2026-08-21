"""Paridad de traducciones y coherencia con el HTML.

Cada cadena nueva se añade a mano a los tres diccionarios de `i18n.js`; es fácil
olvidarse de uno y que a un usuario en inglés le salga media interfaz en
español. También es fácil poner un `data-i18n` en el HTML con una clave que no
existe: `t()` devuelve la propia clave y en pantalla aparece "onb.s1".
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _dicts() -> dict[str, set[str]]:
    """Claves por idioma, leídas del literal `const I18N = {…}`."""
    out: dict[str, set[str]] = {}
    # cada idioma abre con dos espacios de sangría: `  es: {`
    for m in re.finditer(r"^  ([a-z]{2}): \{$", I18N_JS, re.M):
        lang, start = m.group(1), m.end()
        end = I18N_JS.index("\n  },", start)
        out[lang] = set(re.findall(r'"([^"]+)":\s', I18N_JS[start:end]))
    return out


def test_all_languages_have_the_same_keys():
    d = _dicts()
    assert set(d) == {"es", "ca", "en"}, f"idiomas inesperados: {sorted(d)}"
    for lang, keys in d.items():
        if lang == "es":
            continue
        missing = d["es"] - keys
        extra = keys - d["es"]
        assert not missing, f"a '{lang}' le faltan claves: {sorted(missing)}"
        assert not extra, f"'{lang}' tiene claves que no están en es: {sorted(extra)}"


def test_html_i18n_keys_exist():
    es = _dicts()["es"]
    attrs = ("data-i18n", "data-i18n-ph", "data-i18n-title", "data-i18n-dph")
    used = set()
    for a in attrs:
        used |= set(re.findall(rf'{a}="([^"]+)"', INDEX))
    unknown = sorted(k for k in used if k not in es)
    assert not unknown, f"claves usadas en index.html sin traducción: {unknown}"


def test_ui_lang_options_are_accepted_by_the_api():
    """El <select> no debe ofrecer un idioma que POST /api/settings rechace."""
    from app.main import DEFAULT_SETTINGS

    block = INDEX[INDEX.index('<select id="set-ui-lang">'):]
    block = block[:block.index("</select>")]
    offered = set(re.findall(r'<option value="([^"]+)"', block))
    assert DEFAULT_SETTINGS["ui_lang"] in offered
    allowed = {"auto", "es", "ca", "en"}
    assert offered <= allowed, f"opciones no soportadas: {sorted(offered - allowed)}"


def test_auto_resolves_against_navigator_language():
    """`detectUILang` debe existir y caer en inglés (idioma del README)."""
    assert "function detectUILang()" in I18N_JS
    assert "navigator.languages" in I18N_JS
    # el fallback final no puede ser español: quien llega de fuera lee el README
    # en inglés y no sabría que hay selector de idioma
    tail = I18N_JS[I18N_JS.index("function detectUILang()"):]
    assert re.search(r'return "en";', tail[:tail.index("}\n")+400])


def test_translations_keep_their_placeholders():
    """{0}, {1}… deben sobrevivir a la traducción o el texto sale roto."""
    d_raw: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"^  ([a-z]{2}): \{$", I18N_JS, re.M):
        lang, start = m.group(1), m.end()
        end = I18N_JS.index("\n  },", start)
        body = I18N_JS[start:end]
        d_raw[lang] = {k: v for k, v in re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', body)}
    for lang, items in d_raw.items():
        if lang == "es":
            continue
        for key, val in items.items():
            want = set(re.findall(r"\{\d\}", d_raw["es"].get(key, "")))
            got = set(re.findall(r"\{\d\}", val))
            assert want == got, f"{lang}.{key}: placeholders {got} ≠ {want}"


def test_i18n_js_is_valid_json_shaped():
    """Sanidad: el bloque debe tener las tres aperturas y cierres emparejados."""
    assert I18N_JS.count("\n  },") == 3
    # y las cadenas no deben llevar comillas sin escapar (rompen el parseo)
    for m in re.finditer(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', I18N_JS):
        json.loads(f'"{m.group(2)}"')


# ---------- guardia contra cadenas sin traducir ----------

# Texto en español que SÍ puede quedarse en el HTML, con el motivo. Todo lo
# demás que suene a español y no lleve data-i18n hace fallar el test.
_ALLOWED = {
    # lo reescribe applySettings() con t("hero.sub", idioma)
    "Mina idiomas desde tus videos — tarjetas con audio, imagen y traducción directas a Anki.",
    # el <select> de modelos lo rellena JS con t("wh.*"); esto es solo el fallback
    "Whisper large-v3 catalán (AINA) — máxima calidad",
    "Whisper large-v3 genérico",
    "Whisper small — rápido",
    # nombres de idioma: van en su propio idioma a propósito
    "Español", "Català", "English",
    # título de la vista de conjugación, lo pone JS con t("conj.btn")
    "Conjugació",
    # etiquetas de la tarjeta y tooltip del dual: los reescribe applySettings()
    # con el nombre del idioma base activo
    "Palabra ES", "Frase ES", "Subtítulo dual en español (E)",
}

_SPANISH = re.compile(
    r"[áéíóúñü¿¡]|\b(el|la|los|las|del|para|con|sin|una|que|más|está|son|hay|"
    r"tus|tu|por|como|desde|cuando|todos|clic|palabra|frase|vídeo|video)\b", re.I)


def test_no_untranslated_text_in_html():
    """Un <button>/<p>/<label> con texto español y sin data-i18n se queda en
    español para siempre — no hay nada que lo reescriba."""
    bad = []
    for m in re.finditer(r"<(button|h1|h2|h3|h4|p|label|span|small|option|summary|li|b)"
                         r"\b([^>]*)>([^<]{3,160})</\1>", INDEX):
        tag, attrs, txt = m.groups()
        if "data-i18n" in attrs:
            continue
        t = txt.strip()
        if not t or "${" in t or t in _ALLOWED:
            continue
        if _SPANISH.search(t):
            bad.append(f"<{tag}> {t[:70]}")
    assert not bad, "texto sin traducir en index.html:\n  " + "\n  ".join(bad)


def test_no_untranslated_tooltips():
    """Los title= son lo que el usuario ve al pasar el ratón: si no llevan
    data-i18n-title, la interfaz en inglés los enseña en español."""
    bad = []
    for m in re.finditer(r'<[a-z]+\b([^>]*\btitle="([^"]{4,200})"[^>]*)>', INDEX):
        attrs, t = m.groups()
        if "data-i18n-title" in attrs or t in _ALLOWED:
            continue
        if _SPANISH.search(t):
            idm = re.search(r'id="([^"]+)"', attrs)
            bad.append(f"{idm.group(1) if idm else '?'}: {t[:60]}")
    assert not bad, "tooltips sin traducir:\n  " + "\n  ".join(bad)


def test_no_untranslated_strings_reaching_the_dom_from_js():
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    bad = []
    for m in re.finditer(r"(innerHTML|textContent|placeholder)\s*=\s*([`\"'])(.*?)\2", js, re.S):
        t = m.group(3)
        if "${t(" in t or "t(" == t[:2] or t.strip() in _ALLOWED:
            continue
        if _SPANISH.search(t) and len(t.strip()) > 4:
            bad.append(t.strip()[:70])
    for m in re.finditer(r"\btoast\(\s*([`\"'])((?:[^\\]|\\.)*?)\1", js):
        t = m.group(2)
        if "${t(" not in t and _SPANISH.search(t):
            bad.append("toast: " + t[:60])
    assert not bad, "cadenas en español que van al DOM desde app.js:\n  " + "\n  ".join(bad)


def test_no_function_shadows_the_translator():
    """`const t = …` dentro de una función que llama a t("clave") revienta.

    `t` es la función de traducción global. Si una función declara una variable
    local con ese nombre, cualquier t("…") anterior a la declaración lanza
    ReferenceError por la zona muerta temporal, y la función entera deja de
    funcionar. Pasó de verdad: al traducir el aviso "Cargando el video…"
    dentro de loadStreamUrl, que tenía `const t = V.currentTime`, se rompió el
    streaming por completo durante tres versiones. Los tests de traducción no
    lo vieron porque solo miran texto, no ejecutan JS.
    """
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    lines = js.split("\n")
    starts = [i for i, ln in enumerate(lines)
              if re.match(r"^(async )?function \w+|^\s*\$\(.*\)\.on\w+ = (async )?\(", ln)]
    starts.append(len(lines))
    bad = []
    for a, b in zip(starts, starts[1:], strict=False):
        body = "\n".join(lines[a:b])
        if re.search(r"\b(const|let)\s+t\s*=", body) and re.search(r'[^.\w]t\("', body):
            bad.append(f"línea {a + 1}: {lines[a].strip()[:60]}")
    assert not bad, ("funciones que declaran `t` local y llaman al traductor:\n  "
                     + "\n  ".join(bad))


def test_no_bare_literal_is_passed_to_a_function_that_paints():
    """El test de arriba solo mira asignaciones y toast(), y además adivina si
    el texto es español.

    Adivinar no basta: «Descargando de YouTube…» no lleva acentos ni ninguna
    palabra de la lista, así que pasaba el filtro. La regla buena no mira el
    idioma — si una función que pinta recibe una frase escrita a mano, es un
    fallo, venga en el idioma que venga. Se colaban las cadenas pasadas como
    argumento (`pollJob(id, "Procesando el video…")`), y quien usaba la app en
    inglés veía la barra en español durante una descarga entera.

    Se ignoran los literales sin espacios: son clases y banderas («ok»,
    «err»), no texto.
    """
    js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    pinta = re.compile(r"\b(pollJob|showProgress|toast|setLabel)\s*\(")
    malas = []
    for n, linea in enumerate(js.split("\n"), 1):
        if linea.strip().startswith("//") or not pinta.search(linea):
            continue
        for m in re.finditer(r'(["`])((?:[^"`\\\n]|\\.){4,120})\1', linea):
            texto = m.group(2)
            if "${" in texto or " " not in texto.strip():
                continue          # clases y banderas, no texto
            if texto.strip() in _ALLOWED:
                continue
            malas.append(f"línea {n}: {texto[:70]}")
    assert not malas, ("texto escrito a mano en funciones que pintan "
                       "(debe pasar por t()):\n  " + "\n  ".join(malas))


def test_every_error_key_the_backend_sends_has_a_translation():
    """`_err("err.x", …)` y `jobs.JobError("err.x", …)` mandan la clave al
    navegador. Si no existe en i18n.js, `t()` devuelve la propia clave y el
    usuario lee literalmente «err.no_words» donde iba el aviso.
    """
    import ast

    traducidas = set(re.findall(r'"([\w.]+)":\s*"', I18N_JS))
    faltan = []
    for py in sorted((ROOT / "app").rglob("*.py")):
        arbol = ast.parse(py.read_text(encoding="utf-8"))
        for n in ast.walk(arbol):
            if not isinstance(n, ast.Call) or not n.args:
                continue
            nombre = (n.func.id if isinstance(n.func, ast.Name)
                      else getattr(n.func, "attr", ""))
            if nombre not in ("_err", "JobError"):
                continue
            clave = n.args[0]
            if isinstance(clave, ast.Constant) and clave.value not in traducidas:
                faltan.append(f"{py.name}:{n.lineno} -> {clave.value}")
    assert not faltan, "claves de error sin traducir:\n  " + "\n  ".join(faltan)
