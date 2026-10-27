# LinguaMiner — instalación en Windows (PowerShell).
# No requiere instalar Python ni ffmpeg a mano: uv aporta Python y
# static-ffmpeg descarga ffmpeg solo. Ejecuta con:
#   powershell -ExecutionPolicy Bypass -File install.ps1
# Los textos que ve el usuario van en ASCII: PowerShell 5.1 lee los .ps1 sin
# BOM como ANSI y convertía los acentos en basura.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "== LinguaMiner install (Windows) =="

# $ErrorActionPreference NO aborta cuando falla un programa externo: solo
# afecta a los cmdlets. Sin mirar $LASTEXITCODE, un `uv` que fallara pasaba
# desapercibido y la instalación terminaba diciendo "listo" con la app rota.
function Assert-Ok([string]$What) {
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: $What failed (code $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "The install stops here. Please paste the lines above in"
    Write-Host "https://github.com/thecopybookhare-cmd/lingua-miner/issues"
    exit 1
  }
}

# 1) uv (gestor de Python; se instala solo si falta)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "-- Installing uv --"
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ERROR: uv was installed but isn't on the PATH." -ForegroundColor Red
    Write-Host "Close this window, open a new PowerShell and run the installer again."
    exit 1
  }
}

# 2) entorno + dependencias con las versiones exactas de uv.lock: la misma
# combinación que pasó los tests, no lo último que haya salido hoy. Así se
# colaron PyAV 19 (#8) y la yt-dlp del 403 (#9). uv instala Python 3.12 si
# hace falta. --inexact: no borrar los modelos de spaCy que instala la app.
# Aquí ya no se bajan modelos: el asistente de primer arranque pregunta antes
# qué idioma estudias. Antes todo el mundo se bajaba los de catalán.
Write-Host "-- Installing dependencies --"
uv sync --frozen --inexact --no-dev --python 3.12
Assert-Ok "installing the dependencies"

# 3) comprobación de arranque
# Si la app no puede ni importarse, la ventana salía en blanco y el usuario no
# tenía forma de saber por qué. Mejor fallar aquí, con el error delante.
Write-Host "-- Checking that the app starts --"
.\.venv\Scripts\python.exe -c "from app.main import app"
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "ERROR: the install finished but the app doesn't start." -ForegroundColor Red
  Write-Host "The error is right above. Please paste it in"
  Write-Host "https://github.com/thecopybookhare-cmd/lingua-miner/issues"
  exit 1
}
Write-Host "   ok"

# 4) acceso directo en el menú Inicio (con icono propio)
try {
  $StartDir = [Environment]::GetFolderPath('StartMenu')
  $Lnk = Join-Path $StartDir "Programs\LinguaMiner.lnk"
  $Shell = New-Object -ComObject WScript.Shell
  $Sc = $Shell.CreateShortcut($Lnk)
  $Sc.TargetPath = (Join-Path (Get-Location) "run.bat")
  $Sc.WorkingDirectory = (Get-Location).Path
  $Sc.IconLocation = (Join-Path (Get-Location) "assets\AppIcon.ico")
  $Sc.Description = "LinguaMiner - mine languages from video"
  $Sc.Save()
  Write-Host "Shortcut created: Start menu > LinguaMiner"
} catch { Write-Host "WARNING: could not create the shortcut ($_)" }

Write-Host ""
Write-Host "Done! Start it with:  .\run.bat   (or from the Start menu > LinguaMiner)"
Write-Host "Optional: install Anki (https://apps.ankiweb.net) + the AnkiConnect add-on (2055492159)."
Write-Host "When the app opens, pick the language you're learning: it downloads what that language needs."
