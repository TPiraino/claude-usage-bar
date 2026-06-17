#!/usr/bin/env bash
# Instalador de Claude Usage Bar para Linux (GNOME / Ubuntu)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$APP_DIR/claude_usage_bar.py"
AUTOSTART_DIR="$HOME/.config/autostart"
DESKTOP_DST="$AUTOSTART_DIR/claude-usage-bar.desktop"
LAUNCHER="$HOME/.local/bin/claude-usage-bar"

echo "==> Verificando dependencias del sistema (apt)…"
MISSING=()
python3 -c "import gi" 2>/dev/null || MISSING+=("python3-gi")
python3 -c "import gi; gi.require_version('Gtk','3.0')" 2>/dev/null || MISSING+=("gir1.2-gtk-3.0")
python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1')" 2>/dev/null || MISSING+=("gir1.2-ayatanaappindicator3-0.1")
python3 -c "import gi; gi.require_version('Secret','1')" 2>/dev/null || MISSING+=("gir1.2-secret-1")
python3 -c "import gi; gi.require_version('Notify','0.7')" 2>/dev/null || MISSING+=("gir1.2-notify-0.7")
python3 -c "import cryptography" 2>/dev/null || MISSING+=("python3-cryptography")

if [ ${#MISSING[@]} -ne 0 ]; then
  echo "   Faltan paquetes. Instalá con:"
  echo "      sudo apt install ${MISSING[*]}"
  exit 1
fi
echo "   OK"

echo "==> Verificando curl_cffi (pasa el challenge de Cloudflare)…"
if ! python3 -c "import curl_cffi" 2>/dev/null; then
  echo "   Instalando curl_cffi (pip --user)…"
  python3 -m pip install --user --break-system-packages -q curl_cffi
fi
python3 -c "import curl_cffi" 2>/dev/null && echo "   OK" || { echo "   ERROR: no se pudo instalar curl_cffi"; exit 1; }

chmod +x "$PY"

echo "==> Creando lanzador en $LAUNCHER"
mkdir -p "$HOME/.local/bin"
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
exec python3 "$PY" "\$@"
EOF
chmod +x "$LAUNCHER"

echo "==> Configurando autostart en $DESKTOP_DST"
mkdir -p "$AUTOSTART_DIR"
cat > "$DESKTOP_DST" <<EOF
[Desktop Entry]
Type=Application
Name=Claude Usage Bar
Comment=Muestra el consumo de tu cuenta de claude.ai en la barra
Exec=python3 $PY
Icon=$APP_DIR/icons/claude-usage-green.svg
Terminal=false
X-GNOME-Autostart-enabled=true
Categories=Utility;
EOF

echo
echo "✔ Instalado."
echo "  - Arrancalo ahora:   claude-usage-bar   (o: python3 $PY)"
echo "  - Se iniciará solo en cada login."
echo "  - Primera vez: click en el ícono → 'Configurar cookie de sesión'."
