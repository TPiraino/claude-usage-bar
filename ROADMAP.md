# Roadmap / mejoras pendientes

Estado de ideas para evolucionar **Claude Usage Bar**. Ordenadas por relación
esfuerzo/impacto. PRs y sugerencias bienvenidos.

## Alto impacto

- [ ] **Screenshot / GIF en el README** — falta lo más visual. Mostrar la barra
  con el menú abierto. (Bloqueado por: captura en Wayland.)
- [ ] **Countdown de reset en vivo** — mostrar "resetea en 2h 15m" en vez de la
  hora fija; más útil de un vistazo.
- [ ] **Robustez de la extracción de cookie** (ver detalle abajo) — soportar más
  navegadores y backends de keyring. **← en progreso (rama `feat/cookie-multi-browser`)**

### Detalle: extracción de cookie multi-navegador

Hoy `chrome_cookies.py` asume **Chrome + GNOME Keyring (libsecret)**. Falta:

- [ ] Probar de verdad **Brave / Chromium / Edge** (los paths ya están listados
  en `COOKIE_GLOBS` pero sin testear; cada navegador usa su propia entrada de
  keyring: "Brave Safe Storage", "Chromium Safe Storage", etc.).
- [ ] Soportar **KDE / kwallet** como backend de la clave (no solo libsecret).
- [ ] Soportar `--password-store=basic` (clave fija `peanuts`, ya hay fallback
  parcial) y detectar cuál corresponde sin adivinar.
- [ ] Permitir **elegir el navegador/perfil** explícitamente (config o flag),
  para máquinas con varios perfiles o varios navegadores logueados.
- [ ] Mensajes de error claros por caso (no hay cookies / no logueado / keyring
  bloqueado / navegador no soportado).
- [ ] Tests con un SQLite de cookies mockeado y valores cifrados de ejemplo.

## Calidad / distribución

- [ ] **Empaquetado**: `.deb` o AppImage para instalar sin clonar; o publicar en
  PyPI / `pipx`.
- [ ] **Tests + CI**: unit tests para `parse_windows` y `chrome_cookies`
  (mock del SQLite) + GitHub Actions.

## Nice-to-have

- [ ] **Histórico**: guardar el uso en SQLite y un mini-gráfico de tendencia.
- [ ] **Cuenta Max/Team**: el endpoint trae `extra_usage` y `spend` (créditos
  USD) que hoy se ignoran; mostrarlos.
- [ ] **Ícono symbolic monocromo** para adaptarse a temas oscuros/claros (hoy es
  a color siempre).
