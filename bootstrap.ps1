# LinguaMiner — instalación de UN comando (Windows, PowerShell). Clona el repo
# y lo instala todo. Uso (repo público):
#   irm https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.ps1 | iex
# (si el repo es privado, clónalo tú y ejecuta install.ps1)
$ErrorActionPreference = "Stop"

$Repo = if ($env:LINGUAMINER_REPO) { $env:LINGUAMINER_REPO } else { "https://github.com/thecopybookhare-cmd/lingua-miner.git" }
$Dest = if ($env:LINGUAMINER_HOME) { $env:LINGUAMINER_HOME } else { Join-Path $env:USERPROFILE "LinguaMiner" }

Write-Host "== LinguaMiner - instalacion de un comando =="
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host "Necesitas 'git': instala Git for Windows (https://git-scm.com/download/win) o 'winget install Git.Git'." -ForegroundColor Yellow
  exit 1
}

if (Test-Path (Join-Path $Dest ".git")) {
  Write-Host "-- Actualizando copia en $Dest --"
  git -C $Dest pull --ff-only
  # tolerante como la version de bash: si no se puede actualizar, seguimos
  if ($LASTEXITCODE -ne 0) { Write-Host "(no pude actualizar; sigo con lo que hay)" }
} else {
  Write-Host "-- Clonando en $Dest --"
  git clone --depth 1 $Repo $Dest
  # $ErrorActionPreference no aborta con programas externos: sin esto, un
  # clone fallido seguia adelante y el error que veia el usuario era otro
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: no se pudo clonar $Repo" -ForegroundColor Red
    Write-Host "Comprueba tu conexion, o clona el repo a mano y ejecuta install.ps1"
    exit 1
  }
}

if (-not (Test-Path (Join-Path $Dest "install.ps1"))) {
  Write-Host "ERROR: $Dest existe pero no contiene LinguaMiner." -ForegroundColor Red
  exit 1
}
Set-Location $Dest
powershell -ExecutionPolicy Bypass -File .\install.ps1
