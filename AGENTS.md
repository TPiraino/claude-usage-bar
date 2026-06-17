# AGENTS.md — instrucciones para agentes (Claude Code, etc.)

Guía para que un agente instale, configure y verifique **Claude Usage Bar**
en Linux de forma autónoma. Pensado para Ubuntu/GNOME pero aplica a cualquier
escritorio con soporte de AppIndicator (KStatusNotifierItem).

## Qué es

Indicador de bandeja en Python que muestra el uso de la cuenta de claude.ai
(ventana de 5h y semanal) leyendo `https://claude.ai/api/organizations/{org}/usage`.
Autenticación por cookie de sesión de claude.ai.

## Componentes

| Archivo | Rol |
|---|---|
| `claude_usage_bar.py` | App principal: indicator GTK + polling + menú |
| `chrome_cookies.py` | Extrae y descifra las cookies de claude.ai desde Chrome |
| `icons/claude-usage-*.svg` | Ícono "spark" de Claude en 5 colores de estado |
| `install.sh` | Instala deps pip, crea lanzador y autostart |

## Restricciones técnicas (LEER)

1. **Cloudflare:** claude.ai bloquea clientes HTTP por huella TLS. Hay que usar
   **`curl_cffi`** con `impersonate="chrome"`. `requests`/`urllib` dan **403**
   ("Just a moment...").
2. **GUI nativa del sistema:** `gi` (PyGObject), `Gtk 3.0`, `AyatanaAppIndicator3`
   y `Secret` vienen de **apt**, NO de pip. Si creás un venv, usá
   `--system-site-packages`.
3. **PEP 668:** Ubuntu 24.04 marca el Python del sistema como "externally
   managed". Para `curl_cffi` usar `pip install --user --break-system-packages`.
4. **Cookie cifrada:** Chrome guarda las cookies en SQLite cifradas con AES-128-CBC;
   la clave sale del GNOME Keyring (schema `chrome_libsecret_os_crypt_password_v2`,
   `application=chrome`). `chrome_cookies.py` ya hace todo esto.

## Instalación paso a paso

```bash
# 1. Dependencias del sistema
sudo apt install -y python3-gi gir1.2-gtk-3.0 \
    gir1.2-ayatanaappindicator3-0.1 gir1.2-secret-1 python3-cryptography

# 2. curl_cffi (vía pip, a nivel usuario)
python3 -m pip install --user --break-system-packages curl_cffi

# 3. Instalador (idempotente): lanzador en ~/.local/bin + autostart en login
./install.sh
```

### Verificación de dependencias

```bash
python3 - <<'EOF'
import gi
gi.require_version("Gtk","3.0"); gi.require_version("AyatanaAppIndicator3","0.1")
gi.require_version("Secret","1")
from gi.repository import Gtk, AyatanaAppIndicator3, Secret
import curl_cffi, cryptography
print("deps OK")
EOF
```

## Configurar la cookie (sin intervención del usuario)

Si Chrome está instalado y con sesión activa en claude.ai, el agente puede
configurar la cookie sin DevTools:

```bash
python3 - <<'EOF'
import chrome_cookies, gi
gi.require_version("Secret","1")
from gi.repository import Secret
cookie = chrome_cookies.get_claude_cookie()          # extrae + descifra de Chrome
schema = Secret.Schema.new("com.claudeusagebar.Cookie", Secret.SchemaFlags.NONE,
                           {"app": Secret.SchemaAttributeType.STRING})
Secret.password_store_sync(schema, {"app":"claude-usage-bar"},
        Secret.COLLECTION_DEFAULT, "Claude.ai session cookie", cookie, None)
print("cookie guardada,", len(cookie.split(";")), "cookies")
EOF
```

En tiempo de ejecución, el usuario también puede usar el menú →
**🍪 Traer cookie de Chrome**.

## Verificar que funciona (sin mirar la barra)

```bash
python3 - <<'EOF'
import importlib.util
s = importlib.util.spec_from_file_location("cub","claude_usage_bar.py")
m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
cookie = m.load_cookie()
assert cookie, "no hay cookie guardada"
org = m.fetch_org(cookie)
data = m.fetch_usage(cookie, org)
w = m.parse_windows(data)
assert w, "respuesta sin ventanas de uso"
for k,v in w.items(): print(f"{k}: {v['util']:.0f}%")
print("OK")
EOF
```

Status 200 + ventanas con `utilization` = todo bien. Un `UsageError` con
401/403 = cookie inválida/expirada → re-extraer de Chrome.

## Ejecutar

```bash
# foreground (debug)
python3 ./claude_usage_bar.py

# background, desacoplado de la terminal del agente
setsid python3 ./claude_usage_bar.py >/tmp/cub.log 2>&1 </dev/null &
```

**No** usar `pkill -f "claude_usage_bar.py"` desde un script cuyo propio
command-line contenga ese patrón (se mata a sí mismo). Matar por PID:
`kill $(pgrep -f "[c]laude_usage_bar.py")`.

## Troubleshooting

| Síntoma | Causa | Fix |
|---|---|---|
| HTTP 403 / "Just a moment..." | huella TLS, falta curl_cffi | instalar `curl_cffi`, usar `impersonate="chrome"` |
| `UsageError 401/403` | cookie expirada | re-extraer cookie de Chrome |
| `ModuleNotFoundError: gi` | venv sin system packages | recrear venv con `--system-site-packages` |
| No aparece el ícono en GNOME | extensión deshabilitada | habilitar `ubuntu-appindicators` |
| Ícono viejo tras cambiarlo | GNOME cachea por nombre | reiniciar el proceso (o renombrar los SVG) |
