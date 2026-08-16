"""Los cuatro instaladores tienen que fallar ruidosamente.

Windows se quedó atrás sin que nadie lo notara: install.sh comprobaba que la
app arranca y install.ps1 no, así que un usuario de Windows con la instalación
a medias se llevaba la ventana en blanco igual. Y `$ErrorActionPreference =
"Stop"` no aborta cuando falla un programa externo — solo afecta a los cmdlets
— así que un `uv pip install` roto pasaba de largo y el script terminaba
diciendo "¡Listo!".
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SH = ["install.sh", "bootstrap.sh"]
PS = ["install.ps1", "bootstrap.ps1"]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", SH + PS)
def test_installer_exists_and_is_not_empty(name):
    assert len(read(name).strip()) > 200


@pytest.mark.parametrize("name", SH)
def test_shell_installers_abort_on_error(name):
    assert "set -euo pipefail" in read(name), f"{name} debe abortar al primer fallo"


@pytest.mark.parametrize("name", PS)
def test_powershell_installers_check_native_exit_codes(name):
    """$ErrorActionPreference no cubre los programas externos."""
    src = read(name)
    assert "$ErrorActionPreference" in src
    assert "$LASTEXITCODE" in src, (
        f"{name} llama a programas externos sin mirar su código de salida")


@pytest.mark.parametrize("name", ["install.sh", "install.ps1"])
def test_both_installers_verify_the_app_actually_starts(name):
    """La comprobación que convierte 'ventana en blanco tres días después' en
    'error aquí mismo con la traza delante'."""
    assert "from app.main import app" in read(name), (
        f"{name} no comprueba que la app arranque antes de darse por buena")


@pytest.mark.parametrize("name", ["install.sh", "install.ps1"])
def test_installers_point_at_the_issue_tracker_when_they_fail(name):
    assert "issues" in read(name), (
        f"{name} falla sin decir dónde reportarlo")


def test_powershell_scripts_are_balanced():
    """No hay pwsh en CI para validarlos; al menos que no estén rotos."""
    import re
    pares = {"{": "}", "(": ")", "[": "]"}
    for name in PS:
        limpio = "\n".join(re.sub(r"#.*$", "", ln) for ln in read(name).splitlines())
        pila, en_str = [], None
        for c in limpio:
            if en_str:
                if c == en_str:
                    en_str = None
            elif c in "\"'":
                en_str = c
            elif c in pares:
                pila.append(c)
            elif c in pares.values():
                assert pila and pares[pila.pop()] == c, f"{name}: desbalance"
        assert not pila, f"{name}: {len(pila)} sin cerrar"
        assert en_str is None, f"{name}: comilla sin cerrar"
