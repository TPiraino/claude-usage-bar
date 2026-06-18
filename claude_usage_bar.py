#!/usr/bin/env python3
"""
Claude Usage Bar (Linux)
========================
Indicador de bandeja para GNOME/Ubuntu que muestra el consumo de tu cuenta de
claude.ai (ventana de 5 horas y ventana semanal), leyendo el mismo endpoint
privado que usa el sitio: /api/organizations/{org}/usage.

Port a Linux del proyecto macOS `claude-usage-bar` (Swift) de @tmatteozzi.

Dependencias del sistema (Ubuntu 24.04):
    python3-gi  gir1.2-gtk-3.0  gir1.2-ayatanaappindicator3-0.1
    gir1.2-secret-1  gir1.2-notify-0.7  python3-cryptography
Dependencias pip (--user): curl_cffi

Uso:
    claude_usage_bar.py                      # corre el indicador
    claude_usage_bar.py --once               # imprime el uso actual y sale (debug)
    claude_usage_bar.py --grab [--browser X] # extrae la cookie del navegador y sale
    claude_usage_bar.py --list-browsers      # navegadores detectados + estado de sesión
    claude_usage_bar.py --version
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Secret", "1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator, Secret  # noqa: E402

# libnotify es opcional: si no está, se degrada sin notificaciones.
try:
    gi.require_version("Notify", "0.7")
    from gi.repository import Notify  # noqa: E402

    _HAS_NOTIFY = True
except (ValueError, ImportError):
    _HAS_NOTIFY = False

import os
import sys
import json
import fcntl
import threading
import subprocess
import datetime as dt

# curl_cffi imita la huella TLS de Chrome -> imprescindible para pasar el
# challenge de Cloudflare de claude.ai (requests normal recibe 403).
from curl_cffi import requests as creq

import browser_cookies

__version__ = "1.1.0"

# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
APP_ID = "claude-usage-bar"
APP_NAME = "Claude Usage Bar"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
USAGE_URL = "https://claude.ai/settings/usage"

BASE = "https://claude.ai/api"
IMPERSONATE = "chrome"  # perfil TLS/HTTP2 que usa curl_cffi
HTTP_TIMEOUT = 20

CONFIG_DIR = os.path.expanduser("~/.config/claude-usage-bar")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULTS = {
    "refresh_seconds": 300,        # cada cuánto consulta la API
    "warn": 80,                    # umbral amarillo
    "crit": 90,                    # umbral rojo
    "notifications": True,         # avisar al cruzar warn/crit
    "auto_grab_on_expiry": True,   # re-extraer cookie del navegador si expira
    "browser": None,               # None = autodetectar; o "chrome"/"chromium"/"firefox"/...
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        print("config inválida, usando defaults:", e)
    return cfg


CONFIG = load_config()

# Almacenamiento seguro de la cookie en GNOME Keyring (vía libsecret)
SECRET_SCHEMA = Secret.Schema.new(
    "com.claudeusagebar.Cookie",
    Secret.SchemaFlags.NONE,
    {"app": Secret.SchemaAttributeType.STRING},
)
SECRET_ATTRS = {"app": APP_ID}


# ----------------------------------------------------------------------------
# Manejo de la cookie de sesión (Keyring)
# ----------------------------------------------------------------------------
def load_cookie():
    try:
        return Secret.password_lookup_sync(SECRET_SCHEMA, SECRET_ATTRS, None)
    except Exception:
        return None


def save_cookie(cookie):
    Secret.password_store_sync(
        SECRET_SCHEMA, SECRET_ATTRS, Secret.COLLECTION_DEFAULT,
        "Claude.ai session cookie", cookie, None,
    )


def normalize_cookie(text):
    """Acepta el header Cookie completo, 'sessionKey=...' suelto, o solo el
    token crudo, y devuelve siempre un header válido."""
    text = (text or "").strip()
    if not text:
        return ""
    if text.lower().startswith("cookie:"):
        text = text[len("cookie:"):].strip()
    if "=" not in text:
        return "sessionKey=" + text
    return text


def cookie_value(name, cookie):
    """Extrae el valor de una cookie del string completo del header Cookie."""
    if not cookie:
        return None
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith(name + "="):
            return part[len(name) + 1:]
    return None


# ----------------------------------------------------------------------------
# Cliente de la API de uso
# ----------------------------------------------------------------------------
class UsageError(Exception):
    """Error genérico de la API."""


class AuthError(UsageError):
    """Cookie inválida o expirada (401/403)."""


def _headers(cookie):
    return {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": USAGE_URL,
    }


def _get(url, cookie):
    r = creq.get(
        url, headers=_headers(cookie), impersonate=IMPERSONATE, timeout=HTTP_TIMEOUT
    )
    if r.status_code in (401, 403):
        raise AuthError("Cookie inválida o expirada (401/403)")
    if r.status_code != 200:
        raise UsageError(f"HTTP {r.status_code}")
    return r.json()


def fetch_org(cookie):
    """Devuelve el uuid de la organización (lastActiveOrg o la primera)."""
    arr = _get(f"{BASE}/organizations", cookie)
    if not isinstance(arr, list) or not arr:
        raise UsageError("No se encontraron organizaciones")
    preferred = cookie_value("lastActiveOrg", cookie)
    if preferred:
        for o in arr:
            if o.get("uuid") == preferred:
                return preferred
    return arr[0].get("uuid")


def fetch_usage(cookie, org):
    return _get(f"{BASE}/organizations/{org}/usage", cookie)


def _first(d, *keys):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return None


def parse_windows(data):
    """Normaliza la respuesta a {label: {util, resets_at}}."""
    out = {}

    def take(label, *aliases):
        w = _first(data, *aliases)
        if isinstance(w, dict):
            util = _first(w, "utilization", "percent", "percentage")
            resets = _first(w, "resets_at", "reset_at", "resetsAt")
            if util is not None:
                out[label] = {"util": float(util), "resets_at": resets}

    take("session", "five_hour", "session", "current_session")
    take("weekly", "seven_day", "weekly", "week")
    take("weekly_opus", "seven_day_opus", "weekly_opus")
    return out


# ----------------------------------------------------------------------------
# Helpers de presentación
# ----------------------------------------------------------------------------
def color_dot(util):
    if util >= CONFIG["crit"]:
        return "🔴"
    if util >= CONFIG["warn"]:
        return "🟡"
    return "🟢"


def status_color(util):
    if util >= CONFIG["crit"]:
        return "red"
    if util >= CONFIG["warn"]:
        return "yellow"
    return "green"


def level(util):
    """0 = normal, 1 = warn, 2 = crit. Para decidir notificaciones."""
    if util >= CONFIG["crit"]:
        return 2
    if util >= CONFIG["warn"]:
        return 1
    return 0


def fmt_reset(iso):
    if not iso:
        return ""
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        now = dt.datetime.now().astimezone()
        if t.date() == now.date():
            return "reset " + t.strftime("%H:%M")
        return "reset " + t.strftime("%d/%m %H:%M")
    except Exception:
        return ""


# ----------------------------------------------------------------------------
# App
# ----------------------------------------------------------------------------
class ClaudeUsageBar:
    def __init__(self):
        self.cookie = load_cookie()
        self.org = None
        self._busy = False
        self._last_level = 0  # para no spamear notificaciones

        if _HAS_NOTIFY and CONFIG["notifications"]:
            Notify.init(APP_NAME)

        self.indicator = AppIndicator.Indicator.new_with_path(
            APP_ID, "claude-usage-gray",
            AppIndicator.IndicatorCategory.SYSTEM_SERVICES, ICON_DIR,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title(APP_NAME)

        self.menu = Gtk.Menu()
        self._build_menu([])
        self.indicator.set_menu(self.menu)

        GLib.timeout_add_seconds(2, self._kick)
        GLib.timeout_add_seconds(CONFIG["refresh_seconds"], self._tick)

    # --- construcción del menú -------------------------------------------
    def _build_menu(self, rows, footer=None):
        for child in self.menu.get_children():
            self.menu.remove(child)

        if not self.cookie:
            self._add_item("⚠️  Sin cookie — traela de Chrome ↓", None, enabled=False)
        elif not rows:
            self._add_item(footer or "Cargando…", None, enabled=False)
        else:
            for text in rows:
                self._add_item(text, None, enabled=False)

        self._sep()
        if footer and rows:
            self._add_item(footer, None, enabled=False)
            self._sep()
        self._add_item("🔄  Actualizar ahora", self.on_refresh)
        self._add_item("🌐  Abrir uso en el navegador", self.on_open_usage)
        self._add_item("🍪  Traer cookie de Chrome", self.on_grab_chrome)
        self._add_item("🔑  Configurar cookie manualmente…", self.on_set_cookie)
        self._sep()
        self._add_item("✖  Salir", self.on_quit)
        self.menu.show_all()

    def _add_item(self, label, cb, enabled=True):
        item = Gtk.MenuItem(label=label)
        item.set_sensitive(enabled)
        if cb:
            item.connect("activate", cb)
        self.menu.append(item)
        return item

    def _sep(self):
        self.menu.append(Gtk.SeparatorMenuItem())

    # --- refresco ---------------------------------------------------------
    def _kick(self):
        self._tick()
        return False

    def _tick(self):
        if not self._busy:
            threading.Thread(target=self._refresh_worker, daemon=True).start()
        return True

    def _refresh_worker(self):
        self._busy = True
        try:
            if not self.cookie:
                GLib.idle_add(self._set_icon, "gray")
                GLib.idle_add(self._set_label, "")
                GLib.idle_add(self._build_menu, [])
                return
            GLib.idle_add(self._set_icon, "claude")
            GLib.idle_add(self._set_label, "…")
            windows = self._fetch_with_auto_grab()
            GLib.idle_add(self._apply, windows)
        except AuthError as e:
            self.org = None
            GLib.idle_add(self._error, str(e))
        except browser_cookies.BrowserCookieError as e:
            GLib.idle_add(self._error, f"Cookie: {e}")
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self._error, f"Error: {e}")
        finally:
            self._busy = False

    def _fetch_with_auto_grab(self):
        """Consulta la API; si la cookie expiró, intenta re-extraerla de Chrome
        una vez y reintenta automáticamente."""
        try:
            if not self.org:
                self.org = fetch_org(self.cookie)
            return parse_windows(fetch_usage(self.cookie, self.org))
        except AuthError:
            if not CONFIG["auto_grab_on_expiry"]:
                raise
            # un solo reintento re-extrayendo la cookie de Chrome
            cookie = browser_cookies.get_claude_cookie(CONFIG["browser"])
            self.cookie = cookie
            self.org = None
            try:
                save_cookie(cookie)
            except Exception:  # noqa: BLE001
                pass
            self.org = fetch_org(self.cookie)
            return parse_windows(fetch_usage(self.cookie, self.org))

    def _apply(self, windows):
        if not windows:
            self._error("Respuesta sin datos de uso")
            return

        labels = {
            "session": "Sesión 5h",
            "weekly": "Semanal (todos)",
            "weekly_opus": "Semanal Opus",
        }
        rows = []
        worst = 0.0
        worst_label = ""
        for key in ("session", "weekly", "weekly_opus"):
            w = windows.get(key)
            if not w:
                if key == "weekly_opus":
                    rows.append("⚪  Semanal Opus: sin datos")
                continue
            util = w["util"]
            reset = fmt_reset(w.get("resets_at"))
            tail = f" · {reset}" if reset else ""
            rows.append(f"{color_dot(util)}  {labels[key]}: {util:.0f}%{tail}")
            if util >= worst:
                worst, worst_label = util, labels[key]

        now = dt.datetime.now().strftime("%H:%M")
        self._build_menu(rows, footer=f"Actualizado {now}")
        self._set_icon(status_color(worst))
        self._set_label(f"{worst:.0f}%")
        self.indicator.set_title(f"{APP_NAME} — {worst_label} {worst:.0f}%")
        self._maybe_notify(worst, worst_label)
        return False

    def _maybe_notify(self, worst, worst_label):
        lvl = level(worst)
        if lvl > self._last_level and lvl > 0 and _HAS_NOTIFY and CONFIG["notifications"]:
            urgency = "crítico" if lvl == 2 else "alto"
            icon = os.path.join(ICON_DIR, f"claude-usage-{status_color(worst)}.svg")
            try:
                n = Notify.Notification.new(
                    f"Uso de Claude {urgency}: {worst:.0f}%",
                    f"{worst_label} alcanzó {worst:.0f}%.",
                    icon,
                )
                n.show()
            except Exception:  # noqa: BLE001
                pass
        self._last_level = lvl

    def _error(self, msg):
        self._set_icon("gray")
        self._set_label("!")
        now = dt.datetime.now().strftime("%H:%M")
        self._build_menu([], footer=f"⚠️ {msg} ({now})")
        return False

    # --- indicador --------------------------------------------------------
    def _set_icon(self, color):
        self.indicator.set_icon_full(f"claude-usage-{color}", APP_NAME)
        return False

    def _set_label(self, text):
        self.indicator.set_label(text or "", "100%")
        return False

    # --- callbacks de menú ------------------------------------------------
    def on_refresh(self, _):
        self._tick()

    def on_open_usage(self, _):
        try:
            subprocess.Popen(["xdg-open", USAGE_URL])
        except Exception as e:  # noqa: BLE001
            print("no se pudo abrir el navegador:", e)

    def on_grab_chrome(self, _):
        self._set_label("…")
        threading.Thread(target=self._grab_chrome_worker, daemon=True).start()

    def _grab_chrome_worker(self):
        try:
            cookie = browser_cookies.get_claude_cookie(CONFIG["browser"])
            self.cookie = cookie
            self.org = None
            try:
                save_cookie(cookie)
            except Exception as e:  # noqa: BLE001
                print("No se pudo guardar en keyring:", e)
            GLib.idle_add(self._tick)
        except browser_cookies.BrowserCookieError as e:
            GLib.idle_add(self._error, str(e))
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self._error, f"Chrome: {e}")

    def on_quit(self, _):
        Gtk.main_quit()

    def on_set_cookie(self, _):
        dialog = Gtk.Dialog(title="Cookie de sesión de claude.ai")
        dialog.add_button("Cancelar", Gtk.ResponseType.CANCEL)
        dialog.add_button("Guardar", Gtk.ResponseType.OK)
        dialog.set_default_size(560, 220)

        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        info = Gtk.Label()
        info.set_xalign(0)
        info.set_line_wrap(True)
        info.set_markup(
            "Lo más fácil es <b>🍪 Traer cookie de Chrome</b>. Si preferís a mano:\n"
            "DevTools (F12) → <b>Application</b> → <b>Cookies</b> → "
            "<tt>https://claude.ai</tt> → copiá el valor de <tt>sessionKey</tt> "
            "(o el header Cookie completo) y pegalo acá.\n"
            "Se guarda cifrado en tu GNOME Keyring."
        )
        box.add(info)

        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        textview = Gtk.TextView()
        textview.set_wrap_mode(Gtk.WrapMode.CHAR)
        buf = textview.get_buffer()
        if self.cookie:
            buf.set_text(self.cookie)
        scroller.add(textview)
        box.add(scroller)

        dialog.show_all()
        resp = dialog.run()
        if resp == Gtk.ResponseType.OK:
            start, end = buf.get_bounds()
            text = normalize_cookie(buf.get_text(start, end, True))
            if text:
                self.cookie = text
                self.org = None
                try:
                    save_cookie(text)
                except Exception as e:  # noqa: BLE001
                    print("No se pudo guardar en keyring:", e)
                self._tick()
        dialog.destroy()


# ----------------------------------------------------------------------------
# Single-instance + CLI
# ----------------------------------------------------------------------------
def acquire_single_instance():
    """Evita múltiples instancias. Devuelve el file handle del lock (hay que
    mantenerlo vivo) o None si ya hay otra corriendo."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    lock_path = os.path.join(runtime, "claude-usage-bar.lock")
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def cli_once():
    """Imprime el uso actual y sale (debug / scripting)."""
    cookie = load_cookie()
    if not cookie:
        print("No hay cookie guardada. Usá --grab o configurala desde la app.")
        return 2
    try:
        org = fetch_org(cookie)
        windows = parse_windows(fetch_usage(cookie, org))
    except AuthError:
        print("Cookie expirada (401/403). Probá --grab.")
        return 3
    if not windows:
        print("Respuesta sin datos de uso.")
        return 4
    for k, v in windows.items():
        print(f"{k:14s} {v['util']:5.1f}%   {fmt_reset(v.get('resets_at'))}")
    return 0


def cli_grab(browser=None):
    """Extrae la cookie del navegador, la guarda y sale."""
    try:
        cookie = browser_cookies.get_claude_cookie(browser or CONFIG["browser"])
    except browser_cookies.BrowserCookieError as e:
        print("No se pudo extraer la cookie:", e)
        return 5
    save_cookie(cookie)
    print(f"Cookie guardada ({len(cookie.split(';'))} cookies).")
    return 0


def cli_list_browsers():
    """Lista los navegadores detectados y si tienen sesión de claude.ai."""
    sources = browser_cookies.list_sources()
    if not sources:
        print("No detecté ningún navegador con base de cookies.")
        return 6
    for s in sources:
        print(f"{s['browser']:9s} {s['status']:42s} {s['db']}")
    return 0


def _arg_value(args, name):
    """Lee --name=valor o '--name valor'."""
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def main():
    args = sys.argv[1:]
    if "--version" in args:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--list-browsers" in args:
        return cli_list_browsers()
    if "--once" in args:
        return cli_once()
    if "--grab" in args:
        return cli_grab(_arg_value(args, "--browser"))

    lock = acquire_single_instance()
    if lock is None:
        print("Ya hay una instancia corriendo.")
        return 0

    ClaudeUsageBar()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
