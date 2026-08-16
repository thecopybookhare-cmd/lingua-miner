#!/bin/bash
# Genera ~/Applications/LinguaMiner.app apuntando a este checkout.
set -e
cd "$(dirname "$0")"
REPO="$(pwd)"
APP="$HOME/Applications/LinguaMiner.app"
VER="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)"
VER="${VER:-0.0.0}"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# icono del Dock/Finder
if [ -f "$REPO/assets/AppIcon.icns" ]; then
  cp "$REPO/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>LinguaMiner</string>
  <key>CFBundleDisplayName</key><string>LinguaMiner</string>
  <key>CFBundleIdentifier</key><string>app.linguaminer.desktop</string>
  <key>CFBundleVersion</key><string>$VER</string>
  <key>CFBundleShortVersionString</key><string>$VER</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>NSHighResolutionCapable</key><true/>
  <!-- App Transport Security bloquea http:// dentro de una .app empaquetada.
       La UI se sirve desde http://127.0.0.1, así que sin esta excepción
       WKWebView puede quedarse con la página en blanco. NSAllowsLocalNetworking
       es la llave de Apple para permitir HTTP solo a destinos locales: no abre
       la mano con internet. -->
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
cd "$REPO"
exec "$REPO/.venv/bin/python" -m app.desktop
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"
echo "✅ Creada $APP — ábrela desde Launchpad o Spotlight."
