# Roadmap / mejoras pendientes

Estado de ideas para evolucionar **Claude Usage Bar**. Ordenadas por relación
esfuerzo/impacto. PRs y sugerencias bienvenidos.

## Alto impacto

- [ ] **Screenshot / GIF en el README** — falta lo más visual. Mostrar la barra
  con el menú abierto. (Bloqueado por: captura en Wayland.)
- [ ] **Countdown de reset en vivo** — mostrar "resetea en 2h 15m" en vez de la
  hora fija; más útil de un vistazo.
- [~] **Robustez de la extracción de cookie** (ver detalle abajo) — soportar más
  navegadores y backends de keyring. **← rama `feat/cookie-multi-browser`**

### Detalle: extracción de cookie multi-navegador

El módulo `browser_cookies.py` ya generaliza la extracción (`chrome_cookies.py`
quedó como shim). Estado:

- [x] **Chrome / Chromium / Brave / Edge**: misma lógica AES, con
  **autodetección de la clave** (prueba passwords candidatas del keyring hasta
  que el `sessionKey` descifrado empieza con `sk-ant-sid`).
- [x] **Firefox** (incluido snap/flatpak): lee `moz_cookies` en texto plano.
- [x] `--password-store=basic` (clave fija `peanuts`) como fallback.
- [x] **Elegir navegador** explícito: config `browser` o flag `--browser`;
  `--list-browsers` para ver qué detecta.
- [x] Mensajes de error por caso (no hay cookies / no logueado / no se pudo
  descifrar / navegador no soportado).
- [x] Tests con SQLite mockeado (Firefox plano + Chromium cifrado).
- [x] Selección de **perfil** dentro de un navegador (config `profile` / flag
  `--profile`, match exacto o substring; `--list-browsers` lista todos).
- [ ] Probar Brave/Edge en una máquina real (hoy solo verificado Chrome+Firefox).
- [ ] Soportar **KDE / kwallet** como backend de la clave (no solo libsecret).

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
