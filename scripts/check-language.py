#!/usr/bin/env python3
"""¿Se puede añadir este idioma a LinguaMiner? Comprueba las piezas una a una.

    .venv/bin/python scripts/check-language.py it ru zh

Un idioma necesita cinco cosas, y no todas pesan igual:

  Whisper    transcribe el audio. Sin esto no hay nada que hacer.
  traductor  OPUS-MT →es o →en. Sin ninguno de los dos, tampoco.
  wordfreq   frecuencia de las palabras. Sin esto la recomendación i+1 no
             puede distinguir una palabra que vale la pena de una rara.
  spaCy      lema y categoría gramatical. Sin esto no se agrupan las formas
             de una misma palabra ni se filtran los nombres propios.
  Piper      voz neural para la pronunciación. Opcional.

Los tres primeros deciden si el idioma es viable; los otros dos, si va
completo o cojo.
"""
import sys
import urllib.error
import urllib.request

HF = "https://huggingface.co/api/models/"
SPACY_COMPAT = ("https://raw.githubusercontent.com/explosion/spacy-models/"
                "master/compatibility.json")
TIMEOUT = 20


def _exists(url: str) -> bool:
    try:
        urllib.request.urlopen(url, timeout=TIMEOUT)
        return True
    except urllib.error.HTTPError:
        return False
    except Exception:                      # red caída: mejor "?" que un falso no
        raise


def whisper_ok(code: str) -> bool:
    from faster_whisper.tokenizer import _LANGUAGE_CODES
    return code in _LANGUAGE_CODES


def wordfreq_ok(code: str) -> bool:
    import wordfreq
    return code in set(wordfreq.available_languages())


def spacy_models(code: str, cache: dict) -> list[str]:
    if "m" not in cache:
        import json
        d = json.loads(urllib.request.urlopen(SPACY_COMPAT, timeout=TIMEOUT).read())
        models: set[str] = set()
        for mm in d.get("spacy", {}).values():
            models.update(mm.keys())
        cache["m"] = models
    return sorted(m for m in cache["m"] if m.startswith(code + "_"))


def translators(code: str) -> dict[str, bool]:
    return {
        "→es": _exists(f"{HF}Helsinki-NLP/opus-mt-{code}-es"),
        "→en": _exists(f"{HF}Helsinki-NLP/opus-mt-{code}-en"),
    }


def piper_ok(code: str, cache: dict) -> bool:
    if "p" not in cache:
        import json
        d = json.loads(urllib.request.urlopen(
            f"{HF}rhasspy/piper-voices/tree/main", timeout=TIMEOUT).read())
        cache["p"] = {x["path"] for x in d if x["type"] == "directory"}
    return code in cache["p"]


# NLLB-200 cubre 200 idiomas y hay conversión CTranslate2 hecha; se usa cuando
# OPUS-MT no llega (el cantonés no tiene modelo bilingüe). Códigos en
# https://github.com/facebookresearch/flores/blob/main/flores200
NLLB = {"yue": "yue_Hant", "bn": "ben_Beng", "te": "tel_Telu", "kk": "kaz_Cyrl",
        "bg": "bul_Cyrl", "zh": "zho_Hans", "nl": "nld_Latn"}


def verdict(w: bool, tr: dict, wf: bool, sp: list[str], code: str = "") -> str:
    if not w:
        return "NO — Whisper no transcribe este idioma"
    if not any(tr.values()):
        if code in NLLB:
            return (f"SIN OPUS-MT, pero NLLB-200 lo cubre como {NLLB[code]} — "
                    "así se añadió el cantonés (ver translate_bases con clave nllb)")
        return "NO — no hay traductor OPUS-MT ni a español ni a inglés"
    if not wf and not sp:
        return "MUY LIMITADO — sin frecuencia ni lemas: la recomendación i+1 no funciona"
    if not wf:
        return "LIMITADO — sin frecuencia: no puede priorizar palabras que valgan la pena"
    if not sp:
        return "LIMITADO — sin lemas ni categoría: las formas no se agrupan y colará algún nombre propio"
    base = "español e inglés" if tr["→es"] and tr["→en"] else (
        "español" if tr["→es"] else "inglés")
    return f"SÍ — completo, con base en {base}"


def main(codes: list[str]) -> int:
    cache: dict = {}
    worst = 0
    for code in codes:
        try:
            w, wf = whisper_ok(code), wordfreq_ok(code)
            tr, sp = translators(code), spacy_models(code, cache)
            pv = piper_ok(code, cache)
        except Exception as e:                     # noqa: BLE001
            print(f"\n=== {code} ===\n  no se pudo comprobar: {e}")
            worst = 2
            continue
        print(f"\n=== {code} ===")
        print(f"  Whisper      {'sí' if w else 'NO'}")
        print(f"  traductor    →es {'sí' if tr['→es'] else 'no'} · "
              f"→en {'sí' if tr['→en'] else 'no'}")
        print(f"  wordfreq     {'sí' if wf else 'NO'}")
        print(f"  spaCy        {sp[0] if sp else 'NINGUNO'}")
        print(f"  voz Piper    {'sí' if pv else 'no'} (opcional)")
        v = verdict(w, tr, wf, sp, code)
        print(f"  → {v}")
        worst = max(worst, 0 if v.startswith("SÍ") else 1)
    return worst


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
