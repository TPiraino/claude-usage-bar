#!/usr/bin/env bash
# Desinstala Claude Usage Bar (no borra el repo ni curl_cffi).
set -euo pipefail

echo "==> Cerrando la app si está corriendo…"
pids=$(pgrep -f "[c]laude_usage_bar.py" || true)
[ -n "$pids" ] && kill $pids && echo "   cerrada ($pids)" || echo "   no estaba corriendo"

echo "==> Quitando autostart y lanzador…"
rm -f "$HOME/.config/autostart/claude-usage-bar.desktop"
rm -f "$HOME/.local/bin/claude-usage-bar"

echo "==> Borrando la cookie del keyring…"
python3 - <<'EOF' 2>/dev/null || true
import gi
gi.require_version("Secret", "1")
from gi.repository import Secret
schema = Secret.Schema.new("com.claudeusagebar.Cookie", Secret.SchemaFlags.NONE,
                           {"app": Secret.SchemaAttributeType.STRING})
Secret.password_clear_sync(schema, {"app": "claude-usage-bar"}, None)
print("   cookie borrada del keyring")
EOF

echo
echo "✔ Desinstalado."
echo "  - La config en ~/.config/claude-usage-bar/ quedó (borrala a mano si querés)."
echo "  - El repo clonado no se tocó."
