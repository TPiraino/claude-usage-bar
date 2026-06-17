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
    gir1.2-secret-1  python3-requests
"""

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Secret", "1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator, Secret  # noqa: E402

import os
import threading
import datetime as dt

# curl_cffi imita la huella TLS de Chrome -> imprescindible para pasar el
# challenge de Cloudflare de claude.ai (requests normal recibe 403).
from curl_cffi import requests as creq

import chrome_cookies

# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
APP_ID = "claude-usage-bar"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

REFRESH_SECONDS = 5 * 60  # igual al original: 5 minutos
HTTP_TIMEOUT = 20

BASE = "https://claude.ai/api"
IMPERSONATE = "chrome"  # perfil TLS/HTTP2 que usa curl_cffi

# Umbrales de color (igual al original)
WARN = 80
CRIT = 90

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
        SECRET_SCHEMA,
        SECRET_ATTRS,
        Secret.COLLECTION_DEFAULT,
        "Claude.ai session cookie",
        cookie,
        None,
    )


def normalize_cookie(text):
    """Acepta el header Cookie completo, 'sessionKey=...' suelto, o solo el
    token crudo, y devuelve siempre un header válido."""
    text = (text or "").strip()
    if not text:
        return ""
    # quita un prefijo 'cookie:' / 'Cookie:' si lo copiaron del DevTools
    low = text.lower()
    if low.startswith("cookie:"):
        text = text[len("cookie:"):].strip()
    # si no hay ningún 'clave=valor', asumimos que es el token de sessionKey
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
    pass


def _headers(cookie):
    return {
        "Cookie": cookie,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://claude.ai/settings/usage",
    }


def _get(url, cookie):
    r = creq.get(
        url, headers=_headers(cookie), impersonate=IMPERSONATE, timeout=HTTP_TIMEOUT
    )
    if r.status_code in (401, 403):
        raise UsageError("Cookie inválida o expirada (401/403)")
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
    """Devuelve el primer key presente (alias del endpoint cambian)."""
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
    take("weekly_sonnet", "seven_day_sonnet", "weekly_sonnet")
    take("weekly_opus", "seven_day_opus", "weekly_opus")
    return out


# ----------------------------------------------------------------------------
# Helpers de presentación
# ----------------------------------------------------------------------------
def color_dot(util):
    if util >= CRIT:
        return "🔴"
    if util >= WARN:
        return "🟡"
    return "🟢"


def status_color(util):
    if util >= CRIT:
        return "red"
    if util >= WARN:
        return "yellow"
    return "green"


def fmt_reset(iso):
    if not iso:
        return ""
    try:
        s = iso.replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(s).astimezone()
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

        self.indicator = AppIndicator.Indicator.new_with_path(
            APP_ID,
            "claude-usage-gray",
            AppIndicator.IndicatorCategory.SYSTEM_SERVICES,
            ICON_DIR,
        )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title("Claude Usage")

        self.menu = Gtk.Menu()
        self._build_menu([])
        self.indicator.set_menu(self.menu)

        # Primer refresh + timer periódico
        GLib.timeout_add_seconds(2, self._kick)
        GLib.timeout_add_seconds(REFRESH_SECONDS, self._tick)

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
        return False  # one-shot

    def _tick(self):
        if not self._busy:
            threading.Thread(target=self._refresh_worker, daemon=True).start()
        return True  # mantener el timer

    def _refresh_worker(self):
        self._busy = True
        try:
            if not self.cookie:
                GLib.idle_add(self._set_icon, "gray")
                GLib.idle_add(self._set_label, "")
                GLib.idle_add(self._build_menu, [])
                return
            # estado "cargando": logo Claude mientras consulta
            GLib.idle_add(self._set_icon, "claude")
            GLib.idle_add(self._set_label, "…")
            if not self.org:
                self.org = fetch_org(self.cookie)
            data = fetch_usage(self.cookie, self.org)
            windows = parse_windows(data)
            GLib.idle_add(self._apply, windows)
        except UsageError as e:
            self.org = None
            GLib.idle_add(self._error, str(e))
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(self._error, f"Error: {e}")
        finally:
            self._busy = False

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
        for key in ("session", "weekly", "weekly_opus"):
            w = windows.get(key)
            if not w:
                # mostramos la fila igual aunque el endpoint no la traiga
                if key == "weekly_opus":
                    rows.append("⚪  Semanal Opus: sin datos")
                continue
            util = w["util"]
            reset = fmt_reset(w.get("resets_at"))
            tail = f" · {reset}" if reset else ""
            rows.append(f"{color_dot(util)}  {labels[key]}: {util:.0f}%{tail}")
            worst = max(worst, util)

        now = dt.datetime.now().strftime("%H:%M")
        self._build_menu(rows, footer=f"Actualizado {now}")

        # la barra muestra el uso MÁS ALTO (el límite que más cerca tenés)
        self._set_icon(status_color(worst))
        self._set_label(f"{worst:.0f}%")
        return False

    def _error(self, msg):
        self._set_icon("gray")
        self._set_label("!")
        now = dt.datetime.now().strftime("%H:%M")
        self._build_menu([], footer=f"⚠️ {msg} ({now})")
        return False

    # --- indicador --------------------------------------------------------
    def _set_icon(self, color):
        self.indicator.set_icon_full(f"claude-usage-{color}", "Claude Usage")
        return False

    def _set_label(self, text):
        self.indicator.set_label(text or "", "100%")
        return False

    # --- callbacks de menú ------------------------------------------------
    def on_refresh(self, _):
        self._tick()

    def on_grab_chrome(self, _):
        """Extrae la cookie de claude.ai directamente de Chrome y refresca."""
        self._set_label("…")
        threading.Thread(target=self._grab_chrome_worker, daemon=True).start()

    def _grab_chrome_worker(self):
        try:
            cookie = chrome_cookies.get_claude_cookie()
            self.cookie = cookie
            self.org = None
            try:
                save_cookie(cookie)
            except Exception as e:  # noqa: BLE001
                print("No se pudo guardar en keyring:", e)
            GLib.idle_add(self._tick)
        except chrome_cookies.ChromeCookieError as e:
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
            "Pegá el <b>header Cookie completo</b> de una pestaña logueada en "
            "claude.ai.\n\n"
            "Cómo obtenerlo: DevTools (F12) → pestaña <b>Network</b> → recargá → "
            "click en cualquier request a claude.ai → <b>Headers</b> → copiá el "
            "valor de <tt>cookie:</tt> (debe contener <tt>sessionKey</tt>).\n"
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


def main():
    app = ClaudeUsageBar()
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
