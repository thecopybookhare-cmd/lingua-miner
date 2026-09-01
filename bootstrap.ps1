# LinguaMiner — one-command install (Windows, PowerShell). Clones the repo and
# installs everything. Usage:
#   irm https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.ps1 | iex
#
# NOTA: nada de `exit` aquí dentro. Cuando esto llega por `| iex`, `exit` no
# termina el script: cierra la ventana de PowerShell entera, y el usuario nunca
# llega a leer POR QUÉ falló (era el bug del issue #2: se veía el banner y la
# ventana desaparecía). `return` sale del bloque y deja el mensaje en pantalla.
$ErrorActionPreference = "Stop"

$Repo = if ($env:LINGUAMINER_REPO) { $env:LINGUAMINER_REPO } else { "https://github.com/thecopybookhare-cmd/lingua-miner.git" }
$Dest = if ($env:LINGUAMINER_HOME) { $env:LINGUAMINER_HOME } else { Join-Path $env:USERPROFILE "LinguaMiner" }

Write-Host "== LinguaMiner - one-command install =="

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Write-Host ""
  Write-Host "This installer needs 'git', and it is not on this machine." -ForegroundColor Yellow
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Installing it for you with winget..." -ForegroundColor Yellow
    winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
    # winget no refresca el PATH de esta sesión: hay que releerlo a mano.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
  }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host ""
    Write-Host "Install Git and run this command again:" -ForegroundColor Yellow
    Write-Host "    winget install Git.Git" -ForegroundColor Cyan
    Write-Host "  or download it from https://git-scm.com/download/win" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "(If you just installed it, close this window and open a new one" -ForegroundColor DarkGray
    Write-Host " so PowerShell picks up the new PATH.)" -ForegroundColor DarkGray
    return
  }
  Write-Host "git is ready." -ForegroundColor Green
}

if (Test-Path (Join-Path $Dest ".git")) {
  Write-Host "-- Updating the copy in $Dest --"
  git -C $Dest pull --ff-only
  # tolerante como la versión de bash: si no se puede actualizar, seguimos
  if ($LASTEXITCODE -ne 0) { Write-Host "(could not update; continuing with what is there)" }
} else {
  Write-Host "-- Cloning into $Dest --"
  git clone --depth 1 $Repo $Dest
  # $ErrorActionPreference no aborta con programas externos: sin esto, un
  # clone fallido seguía adelante y el error que veía el usuario era otro
  if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: could not clone $Repo" -ForegroundColor Red
    Write-Host "Check your connection, or clone the repo by hand and run install.ps1"
    return
  }
}

if (-not (Test-Path (Join-Path $Dest "install.ps1"))) {
  Write-Host ""
  Write-Host "ERROR: $Dest exists but does not contain LinguaMiner." -ForegroundColor Red
  Write-Host "Move or delete that folder and run this command again."
  return
}
Set-Location $Dest
powershell -ExecutionPolicy Bypass -File .\install.ps1
