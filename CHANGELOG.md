# Changelog

## Unreleased (rama `feat/cookie-multi-browser`)

- **Extracción de cookie multi-navegador** (`browser_cookies.py`):
  - Chrome / Chromium / Brave / Edge: descifrado AES con **autodetección de la
    clave** (prueba passwords del keyring hasta que el `sessionKey` valida).
  - Firefox (incluido snap/flatpak): lee `moz_cookies` en texto plano.
  - Fallback `--password-store=basic` (clave `peanuts`).
- Config `browser` + flags `--browser` y `--list-browsers`.
- **Selección de perfil**: config `profile` / flag `--profile` (match exacto o
  substring); `--list-browsers` lista todos los perfiles con su estado.
- `chrome_cookies.py` queda como shim de compatibilidad.
- Tests (`tests/test_browser_cookies.py`) con SQLite mockeado.

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
