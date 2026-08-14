import pytest


@pytest.fixture(autouse=True)
def no_forms_download(monkeypatch):
    """Neutraliza el diccionario de formas por defecto: sin acceso a disco ni
    descarga. Los tests que lo necesiten sobrescriben _CON/_TRIED o mockean
    forms.lookup/known_exact/knows_lower explícitamente."""
    from app import forms
    monkeypatch.setattr(forms, "_CON", None)
    monkeypatch.setattr(forms, "_TRIED", True)
    monkeypatch.setattr(forms, "_LANG", "ca")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Los tests nunca leen/escriben el settings.json real del usuario.
    Se parchea en config: main Y languages.active_code() la comparten."""
    from app import config
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")


@pytest.fixture(autouse=True)
def no_wikdict_download(monkeypatch):
    """Los tests nunca descargan el Wikcionario real.

    La caché va por (idioma, base) desde que hay glosas inglesas además de
    españolas; sembrarla con None para todas las combinaciones deja lookup()
    devolviendo [] sin tocar la red.
    """
    from app import languages, wikdict
    seeded = {(c, b): None for c in languages.PROFILES for b in ("es", "en")}
    monkeypatch.setattr(wikdict, "_CONS", seeded)
