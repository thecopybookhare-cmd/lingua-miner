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
