#!/bin/bash
# LinguaMiner — instalación en macOS y Linux. No requiere Homebrew ni ffmpeg
# a mano: uv se instala solo y ffmpeg lo aporta static-ffmpeg si falta.
set -euo pipefail
cd "$(dirname "$0")"
echo "== LinguaMiner install =="

# 1) uv (gestor de Python; se instala solo si falta, sin sudo)
if ! command -v uv >/dev/null 2>&1; then
  echo "-- Installing uv --"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || { echo "Could not install uv. See https://docs.astral.sh/uv/"; exit 1; }

# 2) espeak-ng (opcional: la voz principal es Piper; esto solo añade IPA)
if ! command -v espeak-ng >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then brew install espeak-ng || true
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y espeak-ng || true; fi
fi

# 3) entorno y dependencias, con las versiones exactas de uv.lock: la misma
# combinación que pasó los tests, no lo último que haya salido hoy. Así se
# colaron PyAV 19, que rompió Transcribir (#8), y la yt-dlp del 403 (#9).
# --inexact: no borrar los modelos de spaCy que la app instala en el venv.
echo "-- Installing dependencies --"
uv sync --frozen --inexact --no-dev --python 3.12

# Aquí ya no se bajan modelos: el asistente de primer arranque pregunta antes
# qué idioma estudias. Antes todo el mundo se bajaba los de catalán.

# 4) comprobación de arranque
# Si la app no puede ni importarse, la ventana de escritorio salía en blanco y
# el usuario no tenía forma de saber por qué. Mejor fallar aquí, con el error
# delante, que en el primer doble clic.
echo "-- Checking that the app starts --"
if ! .venv/bin/python -c "from app.main import app" 2>/tmp/linguaminer-smoke.log; then
  echo
  echo "ERROR: the install finished but the app doesn't start."
  echo "This is what failed:"
  echo
  sed 's/^/    /' /tmp/linguaminer-smoke.log
  echo
  echo "Please paste those lines in https://github.com/thecopybookhare-cmd/lingua-miner/issues"
  exit 1
fi
echo "   ok"

# 5) lanzador
if [ "$(uname)" = "Darwin" ]; then
  ./make-app.sh || echo "WARNING: could not create LinguaMiner.app"
  echo
  echo "Done! Open LinguaMiner.app (Launchpad/Spotlight) or run ./run.sh"
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
  echo "Done! Start it with:  ./run.sh    or from your applications menu (LinguaMiner)"
fi
echo "Optional: install Anki (https://apps.ankiweb.net) + the AnkiConnect add-on (2055492159)."
echo "When the app opens, pick the language you're learning: it downloads what that language needs."
