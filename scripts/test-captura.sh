#!/usr/bin/env bash
# ¿La pantalla y el audio se capturan, o el DRM los deja en negro/silencio?
# Uso: pon el video reproduciendo A PANTALLA COMPLETA y corre esto.
set -u
OUT=/tmp/captura_test.mp4

# --- detectar los índices de dispositivo (no los hardcodeamos: cambian) ---
DEVS=$(ffmpeg -f avfoundation -list_devices true -i "" 2>&1)
VID=$(echo "$DEVS" | sed -n '/video devices/,/audio devices/p' \
      | sed -n 's/.*\[\([0-9]*\)\] Capture screen 0.*/\1/p' | head -1)
AUD=$(echo "$DEVS" | sed -n '/audio devices/,$p' \
      | sed -n 's/.*\[\([0-9]*\)\] BlackHole.*/\1/p' | head -1)

if [ -z "${VID:-}" ]; then echo "❌ No encuentro 'Capture screen 0'."; exit 1; fi
if [ -z "${AUD:-}" ]; then echo "❌ No encuentro BlackHole. ¿Está instalado?"; exit 1; fi
echo "Dispositivos: pantalla=[$VID]  audio=[$AUD]"
echo "Capturando 4 segundos… (que el video esté corriendo AHORA)"
sleep 2

# BlackHole 16ch se presenta como 9.1.6 y AAC no soporta esa distribución:
# tomamos los dos primeros canales, que es donde escribe una salida estéreo.
ffmpeg -hide_banner -loglevel error -y \
  -f avfoundation -framerate 15 -capture_cursor 0 -i "${VID}:${AUD}" -t 4 \
  -vf "scale=1280:-2" -c:v h264_videotoolbox -b:v 3M \
  -af "pan=stereo|c0=c0|c1=c1" -c:a aac -ar 48000 \
  "$OUT" || { echo "❌ falló la captura"; exit 1; }

echo
echo "── VIDEO ─────────────────────────────"
# OJO: metadata=print escribe a nivel info — no poner -loglevel error aquí.
STATS=$(ffmpeg -hide_banner -i "$OUT" \
     -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG" -f null - 2>&1 \
     | sed -n 's/.*YAVG=\([0-9.]*\).*/\1/p')
Y=$(echo "$STATS" | sort -n | tail -1)
VAR=$(echo "$STATS" | sort -n -u | wc -l | tr -d ' ')
echo "   luminancia máxima: ${Y:-?}   (valores distintos: ${VAR:-0})"
awk -v y="${Y:-0}" -v n="${VAR:-0}" 'BEGIN{
  if (y+0 <= 16.5 && n+0 <= 1) { print "   ❌ NEGRO TOTAL, varianza cero — no se está capturando NADA.\n      Eso es falta de permiso, no DRM: Configuración → Privacidad y\n      seguridad → Grabación de pantalla, y REINICIA la app que corre esto.";
                                 exit }
  if (y+0 < 20) print "   ❌ NEGRO.\n      Antes de culpar al DRM: corre el test otra vez SIN Netflix, mirando\n      tu escritorio. Si también sale negro, es que la Terminal no tiene\n      permiso de Grabación de Pantalla (Configuración → Privacidad y\n      seguridad → Grabación de pantalla). macOS entrega negro en silencio.\n      Si el escritorio SÍ se ve y Netflix no, ahí sí es el DRM: prueba Firefox.";
  else          print "   ✅ SE VE — la captura funciona."}'

echo
echo "── AUDIO ─────────────────────────────"
V=$(ffmpeg -hide_banner -i "$OUT" -af volumedetect -f null - 2>&1 \
     | sed -n 's/.*mean_volume: \(-*[0-9.]*\) dB.*/\1/p')
echo "   volumen medio: ${V:-?} dB"
awk -v v="${V:--100}" 'BEGIN{
  if (v+0 < -80) print "   ❌ SILENCIO — la salida del Mac no está yendo a BlackHole.\n      Configuración → Sonido → Salida debe ser un Dispositivo de Salida Múltiple\n      (creado en Configuración de Audio MIDI) que incluya BlackHole + tus altavoces.";
  else           print "   ✅ SE OYE — el audio del sistema entra bien."}'

echo
echo "Míralo tú mismo:  open $OUT"
