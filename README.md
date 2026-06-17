# Claude Usage Bar (Linux)

Indicador de bandeja para **GNOME / Ubuntu** que muestra el consumo de tu cuenta
de **claude.ai** directamente en la barra superior: la ventana de uso de **5 horas**
y la **semanal** (con desglose por modelo).

Port a Linux del proyecto macOS
[`claude-usage-bar`](https://github.com/tmatteozzi/claude-usage-bar) de
@tmatteozzi (originalmente en Swift). Acá está reescrito en Python + GTK3 +
Ayatana AppIndicator, sin compilar nada.

## Qué muestra

- Etiqueta en la barra con el `%` del límite **más alto** (el que tenés más cerca).
- Ícono (el "spark" de Claude) que cambia de color: 🟢 < 80% · 🟡 ≥ 80% · 🔴 ≥ 90%.
- Menú desplegable con cada ventana (sesión 5h, semanal, semanal Opus), su `%`
  y a qué hora resetea.
- Refresco automático cada 5 minutos (igual al original).

## Características

- 🔁 **Cookie auto-renovable**: si la cookie expira (401), la app la re-extrae
  sola de Chrome y reintenta — no tenés que hacer nada mientras Chrome siga
  logueado en claude.ai.
- 🔔 **Notificaciones** de escritorio al cruzar 80% y 90%.
- 🔒 **Single-instance**: no se abre dos veces.
- ⚙️ **Configurable** (`~/.config/claude-usage-bar/config.json`).
- 🖥️ **CLI** para debug/scripting (`--once`, `--grab`, `--version`).

## Cómo funciona

Lee el mismo endpoint privado que usa el sitio web:

```
GET https://claude.ai/api/organizations            -> elige la org (lastActiveOrg)
GET https://claude.ai/api/organizations/{org}/usage -> utilization + resets_at
```

La autenticación es por **cookie de sesión** (igual que el original). La cookie
se guarda cifrada en tu **GNOME Keyring** vía libsecret (equivalente al Keychain
de macOS). Las cookies expiran cada tanto y hay que renovarla.

> **Cloudflare:** claude.ai está detrás de Cloudflare, que bloquea a clientes
> HTTP normales por su huella TLS. Por eso la app usa **`curl_cffi`**, que imita
> la huella TLS/HTTP2 de Chrome. Con `requests` común da 403.

## Instalación

```bash
# 1. Clonar
git clone https://github.com/TPiraino/claude-usage-bar.git
cd claude-usage-bar

# 2. Dependencias del sistema (Ubuntu 24.04 ya las trae casi todas)
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1 \
    gir1.2-secret-1 gir1.2-notify-0.7 python3-cryptography

# 3. Instalar (chequea deps, instala curl_cffi, crea lanzador + autostart)
./install.sh

# 4. Arrancar
claude-usage-bar
```

> Para una instalación asistida por un agente (Claude Code u otro), ver
> [`AGENTS.md`](AGENTS.md).

## Configurar la cookie

**Opción fácil (automática):** click en el ícono → **🍪 Traer cookie de Chrome**.
La app lee y descifra la cookie de claude.ai directamente de tu Chrome (de su
base SQLite, usando la clave del GNOME Keyring) y queda configurada sola.
Repetí esto cuando la cookie expire (ícono gris con `!`).

**Opción manual:** click en el ícono → **Configurar cookie manualmente** →
en el navegador logueado en claude.ai, `F12` → **Application** → **Cookies** →
`https://claude.ai` → copiá el valor de `sessionKey` → pegalo y **Guardar**.

## Configuración (opcional)

Creá `~/.config/claude-usage-bar/config.json` (ver [`config.example.json`](config.example.json)):

```json
{
  "refresh_seconds": 300,
  "warn": 80,
  "crit": 90,
  "notifications": true,
  "auto_grab_on_expiry": true
}
```

## CLI

```bash
claude-usage-bar --once      # imprime el uso actual y sale
claude-usage-bar --grab      # extrae la cookie de Chrome y la guarda
claude-usage-bar --version
```

## Desinstalar

```bash
./uninstall.sh   # cierra la app, quita autostart/lanzador y borra la cookie del keyring
```

## Notas

- Probado en Ubuntu 24.04 / GNOME 46 (Wayland) con la extensión
  `ubuntu-appindicators` (viene activada por defecto).
- En otros escritorios (KDE, XFCE) funciona igual mientras haya soporte de
  AppIndicator/KStatusNotifierItem.
- Si el endpoint cambia los nombres de los campos, el parser ya contempla varios
  alias (`five_hour`/`session`, `seven_day`/`weekly`, etc.).
