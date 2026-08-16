#!/bin/bash
# LinguaMiner — instalación en macOS y Linux. No requiere Homebrew ni ffmpeg
# a mano: uv se instala solo y ffmpeg lo aporta static-ffmpeg si falta.
set -euo pipefail
cd "$(dirname "$0")"
echo "== LinguaMiner install =="

# 1) uv (gestor de Python; se instala solo si falta, sin sudo)
if ! command -v uv >/dev/null 2>&1; then
  echo "-- Instalando uv --"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { echo "No pude instalar uv. Ver https://docs.astral.sh/uv/"; exit 1; }

# 2) espeak-ng (opcional: la voz principal es Piper; esto solo añade IPA)
if ! command -v espeak-ng >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install espeak-ng || true
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y espeak-ng || true; fi
fi

# 3) entorno y dependencias
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install -p .venv/bin/python -e .

# 4) modelos ligeros de primer uso (spaCy + traductor + diccionarios)
echo "-- Modelo spaCy (catalán) --"
.venv/bin/python -m spacy download ca_core_news_sm || echo "AVISO: spaCy ca no instalado (fallback regex)"
echo "-- Traductor Softcatalà + diccionarios (descarga única) --"
.venv/bin/python - <<'PY'
from app import translate, dictionary, forms
if not translate.is_downloaded():
    translate.download()
print("traductor:", "ok" if translate.is_downloaded() else "ERROR")
print("diccionario:", "ok" if dictionary.load().lookup("gos") else "ERROR")
print("formas:", "ok" if forms.lookup("ets") else "ERROR")
PY

# 5) comprobación de arranque
# Si la app no puede ni importarse, la ventana de escritorio salía en blanco y
# el usuario no tenía forma de saber por qué. Mejor fallar aquí, con el error
# delante, que en el primer doble clic.
echo "-- Comprobando que la app arranca --"
if ! .venv/bin/python -c "from app.main import app" 2>/tmp/linguaminer-smoke.log; then
  echo
  echo "ERROR: la instalación terminó pero la app no arranca."
  echo "Esto es lo que falló:"
  echo
  sed 's/^/    /' /tmp/linguaminer-smoke.log
  echo
  echo "Copia esas líneas en https://github.com/thecopybookhare-cmd/lingua-miner/issues"
  exit 1
fi
echo "   ok"

# 6) lanzador
if [ "$(uname)" = "Darwin" ]; then
  ./make-app.sh || echo "AVISO: no se pudo crear LinguaMiner.app"
  echo
  echo "¡Listo! Abre LinguaMiner.app (Launchpad/Spotlight) o ejecuta ./run.sh"
else
  # lanzador de escritorio en Linux (menú de aplicaciones)
  APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$APPS_DIR"
  cat > "$APPS_DIR/linguaminer.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=LinguaMiner
Comment=Mine languages from video — Anki cards in one click
Exec=$(pwd)/run.sh
Path=$(pwd)
Icon=$(pwd)/static/icons/icon-512.png
Terminal=false
Categories=Education;Languages;
DESK
  chmod +x "$APPS_DIR/linguaminer.desktop" 2>/dev/null || true
  echo
  echo "¡Listo! Arranca con:  ./run.sh    o desde el menú de aplicaciones (LinguaMiner)"
fi
echo "Opcional: instala Anki (https://apps.ankiweb.net) + add-on AnkiConnect (2055492159)."
echo "El modelo Whisper catalán (≈3 GB) se descarga solo al transcribir por primera vez."
