# LinguaMiner — instalación en Windows (PowerShell).
# No requiere instalar Python ni ffmpeg a mano: uv aporta Python y
# static-ffmpeg descarga ffmpeg solo. Ejecuta con:
#   powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Write-Host "== LinguaMiner install (Windows) =="

# $ErrorActionPreference NO aborta cuando falla un programa externo: solo
# afecta a los cmdlets. Sin mirar $LASTEXITCODE, un `uv pip install` que
# fallara pasaba desapercibido y la instalación terminaba diciendo "¡Listo!"
# con la app rota.
function Assert-Ok([string]$What) {
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: $What falló (código $LASTEXITCODE)." -ForegroundColor Red
    Write-Host "La instalación se detiene aquí. Copia las líneas de arriba en"
    Write-Host "https://github.com/thecopybookhare-cmd/lingua-miner/issues"
    exit 1
  }
}

# 1) uv (gestor de Python; se instala solo si falta)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host "-- Instalando uv --"
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "ERROR: uv se instaló pero no aparece en el PATH." -ForegroundColor Red
    Write-Host "Cierra esta ventana, abre otra de PowerShell y vuelve a ejecutar."
    exit 1
  }
}

# 2) entorno + dependencias (uv instala Python 3.12 si hace falta)
if (-not (Test-Path .venv)) {
  uv venv --python 3.12 .venv
  Assert-Ok "crear el entorno virtual"
}
uv pip install -p .venv\Scripts\python.exe -e .
Assert-Ok "instalar las dependencias"

# 3) modelos ligeros de primer uso
Write-Host "-- Modelo spaCy (catalan) --"
.\.venv\Scripts\python.exe -m spacy download ca_core_news_sm
if ($LASTEXITCODE -ne 0) {
  # opcional: sin el modelo se cae al tokenizador regex, la app funciona
  Write-Host "AVISO: spaCy ca no instalado (se usara el tokenizador regex)."
}
Write-Host "-- Traductor + diccionarios (descarga unica) --"
.\.venv\Scripts\python.exe -c "from app import translate, dictionary, forms; translate.is_downloaded() or translate.download(); print('traductor:', 'ok' if translate.is_downloaded() else 'ERROR'); print('diccionario:', 'ok' if dictionary.load().lookup('gos') else 'ERROR')"
Assert-Ok "descargar el traductor y los diccionarios"

# 4) comprobacion de arranque
# Si la app no puede ni importarse, la ventana salia en blanco y el usuario no
# tenia forma de saber por que. Mejor fallar aqui, con el error delante.
Write-Host "-- Comprobando que la app arranca --"
.\.venv\Scripts\python.exe -c "from app.main import app"
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "ERROR: la instalacion termino pero la app no arranca." -ForegroundColor Red
  Write-Host "El error esta justo arriba. Copialo en"
  Write-Host "https://github.com/thecopybookhare-cmd/lingua-miner/issues"
  exit 1
}
Write-Host "   ok"

# 5) acceso directo en el menú Inicio (con icono propio)
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
  Write-Host "Acceso directo creado: menú Inicio > LinguaMiner"
} catch { Write-Host "AVISO: no se pudo crear el acceso directo ($_)" }

Write-Host ""
Write-Host "¡Listo! Arranca con:  .\run.bat   (o desde el menú Inicio > LinguaMiner)"
Write-Host "Opcional: instala Anki (https://apps.ankiweb.net) + add-on AnkiConnect (2055492159)."
Write-Host "El modelo Whisper catalán (~3 GB) se descarga solo al transcribir por primera vez."
