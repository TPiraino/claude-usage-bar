"""
Extracción de las cookies de claude.ai desde el navegador (Linux), multi-browser.

Soporta:
  - Familia Chromium (Chrome, Chromium, Brave, Edge): cookies en SQLite cifradas
    con AES-128-CBC; la clave sale del keyring del sistema (libsecret / GNOME
    Keyring) o, si no, de la password fija "peanuts" (--password-store=basic).
    La clave correcta se autodetecta probando candidatas hasta que el sessionKey
    descifrado empieza con "sk-ant-sid".
  - Firefox (incluido el snap de Ubuntu): cookies en `cookies.sqlite`, tabla
    `moz_cookies`, en TEXTO PLANO (no hay que descifrar nada).

API:
  get_claude_cookie(browser=None) -> str            # header Cookie completo
  list_sources() -> list[dict]                      # navegadores disponibles + estado
"""

import os
import glob
import shutil
import sqlite3
import tempfile

import gi

gi.require_version("Secret", "1")
from gi.repository import Secret  # noqa: E402

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.backends import default_backend  # noqa: E402


class BrowserCookieError(Exception):
    pass


# back-compat con la versión anterior (la app importaba chrome_cookies)
ChromeCookieError = BrowserCookieError


# ----------------------------------------------------------------------------
# Definición de navegadores
# ----------------------------------------------------------------------------
# Familia Chromium: globs de la base "Cookies" + apps candidatas del keyring.
CHROMIUM_BROWSERS = {
    "chrome": {
        "globs": ["~/.config/google-chrome/*/Cookies"],
        "keyring_apps": ["chrome"],
    },
    "chromium": {
        "globs": [
            "~/.config/chromium/*/Cookies",
            "~/snap/chromium/common/chromium/*/Cookies",
        ],
        "keyring_apps": ["chromium"],
    },
    "brave": {
        "globs": [
            "~/.config/BraveSoftware/Brave-Browser/*/Cookies",
            "~/snap/brave/*/.config/BraveSoftware/Brave-Browser/*/Cookies",
        ],
        "keyring_apps": ["brave"],
    },
    "edge": {
        "globs": ["~/.config/microsoft-edge/*/Cookies"],
        "keyring_apps": ["chromium", "chrome"],
    },
}

# Firefox: globs de cookies.sqlite (incluye snap y flatpak)
FIREFOX_GLOBS = [
    "~/.mozilla/firefox/*/cookies.sqlite",
    "~/snap/firefox/common/.mozilla/firefox/*/cookies.sqlite",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
]

# Orden de preferencia al autodetectar (browser=None)
PREFERENCE_ORDER = ["chrome", "chromium", "brave", "edge", "firefox"]


def _profile_name(db_path):
    """Nombre del perfil = carpeta que contiene la base de cookies
    (ej. 'Default', 'Profile 1', '72z3jl8j.default-release')."""
    return os.path.basename(os.path.dirname(db_path))


def _list_dbs(globs):
    """Devuelve [(perfil, db_path), ...] ordenado por mtime descendente."""
    hits = []
    for pattern in globs:
        hits += glob.glob(os.path.expanduser(pattern))
    hits = [h for h in hits if os.path.isfile(h)]
    hits.sort(key=os.path.getmtime, reverse=True)
    return [(_profile_name(h), h) for h in hits]


def _select_db(globs, profile=None):
    """Elige una base de cookies: por `profile` (match exacto, luego substring,
    case-insensitive) o, si no se pide, la más reciente."""
    dbs = _list_dbs(globs)
    if not dbs:
        return None
    if not profile:
        return dbs[0][1]
    low = profile.lower()
    for name, path in dbs:
        if name.lower() == low:
            return path
    for name, path in dbs:
        if low in name.lower():
            return path
    return None


def _query_db(path, sql, params=()):
    """Copia la DB (suele estar lockeada) y ejecuta una query de lectura."""
    tmp = tempfile.mktemp(suffix=".sqlite")
    shutil.copy2(path, tmp)
    try:
        con = sqlite3.connect(tmp)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Familia Chromium (cifrado)
# ----------------------------------------------------------------------------
def _keyring_passwords(keyring_apps):
    """Passwords candidatas del keyring para los 'application' dados, + peanuts."""
    pws = []
    seen = set()
    apps = list(keyring_apps) + ["chrome", "chromium", "brave"]
    for app in apps:
        if app in seen:
            continue
        seen.add(app)
        for sname in (
            "chrome_libsecret_os_crypt_password_v2",
            "chrome_libsecret_os_crypt_password_v1",
        ):
            try:
                schema = Secret.Schema.new(
                    sname,
                    Secret.SchemaFlags.DONT_MATCH_NAME,
                    {"application": Secret.SchemaAttributeType.STRING},
                )
                pw = Secret.password_lookup_sync(schema, {"application": app}, None)
                if pw:
                    pws.append(pw.encode("utf-8"))
            except Exception:
                continue
    pws.append(b"peanuts")  # fallback --password-store=basic
    return pws


def _derive_key(password):
    return PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1,
        backend=default_backend(),
    ).derive(password)


def _decrypt(blob, key):
    if not blob:
        return None
    if blob[:3] not in (b"v10", b"v11"):
        try:
            return blob.decode("utf-8")
        except Exception:
            return None
    iv = b" " * 16
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    d = cipher.decryptor()
    try:
        dec = d.update(blob[3:]) + d.finalize()
    except Exception:
        return None
    if not dec:
        return None
    pad = dec[-1]
    if 1 <= pad <= 16:
        dec = dec[:-pad]
    # Chrome reciente antepone 32 bytes de sha256(domain) al valor
    for cut in (32, 0):
        try:
            s = dec[cut:].decode("utf-8")
            if s and all(31 < ord(ch) < 127 for ch in s[:4]):
                return s
        except Exception:
            pass
    return dec.decode("utf-8", "replace")


def _extract_chromium(browser, profile=None):
    spec = CHROMIUM_BROWSERS[browser]
    db = _select_db(spec["globs"], profile)
    if not db:
        if profile:
            raise BrowserCookieError(f"{browser}: no encontré el perfil '{profile}'")
        raise BrowserCookieError(f"{browser}: no encontré la base de cookies")

    rows = _query_db(
        db, "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%claude.ai'"
    )
    if not rows:
        raise BrowserCookieError(f"{browser}: no hay cookies de claude.ai (¿logueado?)")

    enc_session = next((e for n, e in rows if n == "sessionKey"), None)
    if enc_session is None:
        raise BrowserCookieError(f"{browser}: no hay sessionKey (logueate en claude.ai)")

    # autodetectar la clave correcta probando passwords candidatas
    key = None
    for pw in _keyring_passwords(spec["keyring_apps"]):
        k = _derive_key(pw)
        val = _decrypt(enc_session, k)
        if val and val.startswith("sk-ant-sid"):
            key = k
            break
    if key is None:
        raise BrowserCookieError(
            f"{browser}: no pude descifrar el sessionKey (¿keyring bloqueado?)"
        )

    pairs = []
    for name, enc in rows:
        val = _decrypt(enc, key)
        if val:
            pairs.append(f"{name}={val}")
    return "; ".join(pairs)


# ----------------------------------------------------------------------------
# Firefox (texto plano)
# ----------------------------------------------------------------------------
def _extract_firefox(profile=None):
    db = _select_db(FIREFOX_GLOBS, profile)
    if not db:
        if profile:
            raise BrowserCookieError(f"firefox: no encontré el perfil '{profile}'")
        raise BrowserCookieError("firefox: no encontré el perfil / cookies.sqlite")
    rows = _query_db(
        db, "SELECT name, value FROM moz_cookies WHERE host LIKE '%claude.ai'"
    )
    if not rows:
        raise BrowserCookieError("firefox: no hay cookies de claude.ai (¿logueado?)")
    if not any(n == "sessionKey" and v.startswith("sk-ant-sid") for n, v in rows):
        raise BrowserCookieError("firefox: no hay sessionKey válido (logueate en claude.ai)")
    return "; ".join(f"{n}={v}" for n, v in rows)


# ----------------------------------------------------------------------------
# API pública
# ----------------------------------------------------------------------------
def _extract(browser, profile=None):
    if browser == "firefox":
        return _extract_firefox(profile)
    if browser in CHROMIUM_BROWSERS:
        return _extract_chromium(browser, profile)
    raise BrowserCookieError(f"navegador no soportado: {browser}")


def get_claude_cookie(browser=None, profile=None):
    """Devuelve el header Cookie completo de claude.ai.

    - `browser` None → prueba los navegadores en orden de preferencia y se queda
      con el primero que tenga una sesión válida.
    - `profile` selecciona un perfil concreto (nombre exacto o substring); si es
      None se usa el perfil más reciente de cada navegador.
    """
    candidates = [browser] if browser else PREFERENCE_ORDER
    errors = []
    for b in candidates:
        try:
            return _extract(b, profile)
        except BrowserCookieError as e:
            errors.append(str(e))
    detail = "; ".join(errors) if errors else "ningún navegador disponible"
    raise BrowserCookieError(
        "No encontré una sesión de claude.ai en ningún navegador. " + detail
    )


def list_sources():
    """Lista cada navegador/perfil con base de cookies presente y si tiene sesión."""
    out = []
    for b in PREFERENCE_ORDER:
        globs = FIREFOX_GLOBS if b == "firefox" else CHROMIUM_BROWSERS[b]["globs"]
        for profile, db in _list_dbs(globs):
            try:
                _extract(b, profile)
                status = "sesión OK"
            except BrowserCookieError as e:
                status = str(e).split(":", 1)[-1].strip()
            out.append({"browser": b, "profile": profile, "db": db, "status": status})
    return out


if __name__ == "__main__":
    for src in list_sources():
        print(f"{src['browser']:9s} {src['profile']:24s} {src['status']:40s} {src['db']}")
