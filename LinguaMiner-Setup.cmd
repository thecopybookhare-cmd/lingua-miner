@echo off
rem LinguaMiner - instalador de doble clic para Windows.
rem Hace lo mismo que pegar en PowerShell la linea de bootstrap.ps1, sin abrir
rem PowerShell ni pegar nada: Windows pregunta una vez si se ejecuta y el resto
rem va solo. Despues, la app se actualiza desde dentro. Solo ASCII: cmd.exe lee
rem este archivo con la pagina de codigos OEM.
title LinguaMiner setup
echo Installing LinguaMiner. This takes a few minutes: keep this window open.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/thecopybookhare-cmd/lingua-miner/main/bootstrap.ps1 | iex"
echo.
echo You can close this window.
pause
