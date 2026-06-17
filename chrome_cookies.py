"""
Extracción automática de las cookies de claude.ai desde Chrome (Linux).

Chrome guarda las cookies en una base SQLite cifradas con AES-128-CBC; la clave
se deriva (PBKDF2-SHA1, salt 'saltysalt', 1 iteración) de la password
"Chrome Safe Storage" que vive en el GNOME Keyring.
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

# Bases de cookies candidatas (varios navegadores / perfiles basados en Chromium)
COOKIE_GLOBS = [
    "~/.config/google-chrome/*/Cookies",
    "~/.config/chromium/*/Cookies",
    "~/.config/BraveSoftware/Brave-Browser/*/Cookies",
    "~/.config/microsoft-edge/*/Cookies",
]

# (nombre del schema en el keyring, valor del atributo 'application')
KEYRING_APPS = [
    ("chrome_libsecret_os_crypt_password_v2", "chrome"),
    ("chrome_libsecret_os_crypt_password_v2", "chromium"),
    ("chrome_libsecret_os_crypt_password_v2", "brave"),
    ("chrome_libsecret_os_crypt_password_v1", "chrome"),
]


class ChromeCookieError(Exception):
    pass


def _safe_storage_password():
    for sname, app in KEYRING_APPS:
        try:
            schema = Secret.Schema.new(
                sname,
                Secret.SchemaFlags.DONT_MATCH_NAME,
                {"application": Secret.SchemaAttributeType.STRING},
            )
            pw = Secret.password_lookup_sync(schema, {"application": app}, None)
            if pw:
                return pw.encode("utf-8")
        except Exception:
            continue
    # fallback: store "basic" usa la password fija "peanuts"
    return b"peanuts"


def _derive_key(password):
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA1(),
        length=16,
        salt=b"saltysalt",
        iterations=1,
        backend=default_backend(),
    )
    return kdf.derive(password)


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
    dec = d.update(blob[3:]) + d.finalize()
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


def _find_cookie_db():
    for pattern in COOKIE_GLOBS:
        for path in glob.glob(os.path.expanduser(pattern)):
            if os.path.isfile(path):
                return path
    return None


def get_claude_cookie():
    """Devuelve el header Cookie completo de claude.ai, o lanza ChromeCookieError."""
    db = _find_cookie_db()
    if not db:
        raise ChromeCookieError("No encontré la base de cookies de Chrome/Chromium")

    key = _derive_key(_safe_storage_password())

    tmp = tempfile.mktemp(suffix=".sqlite")
    shutil.copy2(db, tmp)
    try:
        con = sqlite3.connect(tmp)
        cur = con.cursor()
        cur.execute(
            "SELECT name, encrypted_value FROM cookies WHERE host_key LIKE '%claude.ai'"
        )
        rows = cur.fetchall()
        con.close()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    pairs = []
    has_session = False
    for name, enc in rows:
        val = _decrypt(enc, key)
        if not val:
            continue
        if name == "sessionKey":
            has_session = val.startswith("sk-ant-sid")
        pairs.append(f"{name}={val}")

    if not pairs:
        raise ChromeCookieError("No hay cookies de claude.ai en Chrome (¿estás logueado?)")
    if not has_session:
        raise ChromeCookieError("No encontré un sessionKey válido (logueate en claude.ai)")

    return "; ".join(pairs)


if __name__ == "__main__":
    c = get_claude_cookie()
    print("OK, %d cookies" % len(c.split(";")))
