# Changelog

## 1.1.0

- **Re-extracción automática de la cookie** cuando expira (401/403): si Chrome
  sigue logueado en claude.ai, la app renueva la cookie sola y reintenta, sin
  intervención del usuario.
- **Notificaciones de escritorio** (libnotify) al cruzar los umbrales 80% / 90%.
- **Single-instance lock**: evita abrir la app dos veces.
- **Archivo de configuración** en `~/.config/claude-usage-bar/config.json`
  (intervalo de refresco, umbrales, notificaciones, auto-grab). Ver
  `config.example.json`.
- **CLI**: `--once` (imprime el uso y sale), `--grab` (extrae cookie de Chrome),
  `--version`.
- Ítem de menú **"Abrir uso en el navegador"**.
- La barra muestra el límite **más alto** (el que tenés más cerca), no solo la sesión.
- `uninstall.sh`.

## 1.0.0

- Versión inicial: indicador de bandeja en Python + GTK3 + AyatanaAppIndicator.
- Lee `/api/organizations/{org}/usage` con `curl_cffi` (pasa el challenge TLS de
  Cloudflare).
- Cookie cifrada en GNOME Keyring; extracción automática desde Chrome.
- Ícono "spark" de Claude coloreado por estado; autostart en login.
