"""Un idioma puede no tener traductor al español.

Hasta el italiano y el ruso, `bases()` daba por hecho que el español siempre
estaba: devolvía `["es", ...]` sin comprobar nada, y `available()` exigía
`translate_repo`/`translate_zip`, que son justamente el traductor →es. Con eso,
un idioma que solo traduce al inglés (el ruso: no hay CT2 ru→es ni zip Marian
en Tatoeba) no aparecía como activable, y si aparecía ofrecía una base española
que no existe.
"""
import pytest

from app import languages as L


def test_russian_offers_english_only():
    assert L.bases("ru") == ["en"]
    assert L.has_spanish_base("ru") is False
    assert "ru" in L.activable(), "el ruso debe ser activable aunque no tenga →es"


def test_italian_offers_both_bases():
    assert L.bases("it") == ["es", "en"]
    assert L.has_spanish_base("it") is True


@pytest.mark.parametrize("code", ["ca", "fr", "en", "de", "pt", "it"])
def test_spanish_stays_first_for_everyone_else(code):
    """Ningún idioma que ya tenía español lo pierde con el cambio."""
    assert L.bases(code)[0] == "es"


def test_every_activable_language_has_at_least_one_base():
    for code in L.activable():
        b = L.bases(code)
        assert b, f"{code} activable sin ninguna base"
        assert all(x in L.BASE_NAMES for x in b), f"{code} declara una base sin nombre: {b}"


def test_base_code_falls_back_to_an_available_base(tmp_path, monkeypatch):
    """Con el ruso activo y 'es' guardado, no puede devolver 'es'."""
    from app import config
    p = tmp_path / "settings.json"
    p.write_text('{"language": "ru", "base_language": "es"}', encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", p)
    assert L.active_code() == "ru"
    assert L.base_code() == "en", "debería caer a la única base que existe"


def test_translate_spec_resolves_for_russian(tmp_path, monkeypatch):
    from app import config
    p = tmp_path / "settings.json"
    p.write_text('{"language": "ru", "base_language": "en"}', encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", p)
    spec = L.translate_spec()
    assert spec["repo"] == "gaudi/opus-mt-ru-en-ctranslate2"
    assert spec["dir"] == "translate-rus-eng"


def test_new_profiles_are_complete():
    """Un perfil a medias rompe en runtime, no al importar."""
    need = ["name", "wordfreq", "espeak", "spacy", "whisper_models",
            "default_whisper", "translate_dir", "piper_voice"]
    for code in ("it", "ru"):
        p = L.PROFILES[code]
        missing = [k for k in need if not p.get(k)]
        assert not missing, f"al perfil {code} le falta {missing}"


def test_italian_reuses_the_romance_model_with_the_spanish_token():
    """it→es sale del modelo multilingüe itc-itc, igual que pt→es: sin el
    token >>spa<< traduciría a un idioma romance cualquiera."""
    it = L.PROFILES["it"]
    assert it["translate_token"] == ">>spa<<"
    assert it["translate_zip"] == L.PROFILES["pt"]["translate_zip"]
    assert it["translate_dir"] != L.PROFILES["pt"]["translate_dir"]


# ---------- chino: el caso que más se puede romper en silencio ----------

def test_chinese_needs_spacy_and_says_so():
    """Sin zh_core_web_sm el tokenizador de reserva devuelve la frase entera
    como UN token, porque el chino no separa palabras con espacios. El perfil
    lo marca para que no se trate como opcional."""
    zh = L.PROFILES["zh"]
    assert zh["spacy"] == "zh_core_web_sm"
    assert zh.get("spacy_required") is True
    assert zh["wordfreq"] == "zh"


def test_chinese_offers_english_only():
    assert L.bases("zh") == ["en"]
    assert L.has_spanish_base("zh") is False
    assert "zh" in L.activable()


def test_chinese_frequencies_need_jieba():
    """wordfreq no tokeniza chino sin jieba, y sin frecuencias la
    recomendación i+1 se apaga entera sin dar ningún error."""
    import wordfreq
    assert wordfreq.zipf_frequency("电影", "zh") > 4.0, (
        "wordfreq devuelve 0 para el chino: falta el extra [jieba]")


def test_jieba_is_declared_as_a_dependency():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    deps = " ".join(data["project"]["dependencies"])
    assert "wordfreq[jieba]" in deps, "wordfreq debe instalarse con el extra jieba"


# ---------- glosas del Wikcionario según la base ----------

def test_every_language_has_english_glosses():
    """Con base inglesa antes no había NINGUNA definición: las acepciones de
    Apertium y las glosas del Wikcionario eran fuentes español→X y se
    ocultaban, dejando solo la traducción neural de la frase."""
    faltan = [c for c, p in L.PROFILES.items()
              if "en" in L.bases(c) and not p.get("wikdict_url_en")]
    assert not faltan, f"sin glosas inglesas: {faltan}"


def test_english_gloss_urls_point_at_english_wiktionary():
    for code, p in L.PROFILES.items():
        u = p.get("wikdict_url_en")
        if not u:
            continue
        assert u.startswith("https://kaikki.org/dictionary/"), (code, u)
        assert "eswiktionary" not in u, f"{code} apunta al Wikcionario español"


def test_wikdict_picks_the_file_that_matches_the_base(tmp_path, monkeypatch):
    from app import config, wikdict
    p = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", p)
    for base, esperado in [("es", "eswiktionary"), ("en", "/dictionary/")]:
        p.write_text(f'{{"language": "ca", "base_language": "{base}"}}', encoding="utf-8")
        url = wikdict._url_for(L.active_code(), L.base_code())
        assert url and esperado in url, (base, url)
