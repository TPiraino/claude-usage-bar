"""
Tests de browser_cookies con bases SQLite mockeadas.
No tocan el keyring real ni navegadores reales.

Correr:  python3 -m pytest tests/ -q     (o)     python3 -m unittest -v
"""

import os
import sys
import sqlite3
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import browser_cookies as bc  # noqa: E402

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.backends import default_backend  # noqa: E402


def _encrypt_v10(value, password=b"peanuts", domain_prefix=True):
    """Cifra como Chrome (v10): AES-128-CBC, iv=16 espacios, PKCS7.
    Chrome reciente antepone 32 bytes de hash de dominio al plaintext."""
    key = bc._derive_key(password)
    plain = (b"\x00" * 32 if domain_prefix else b"") + value.encode("utf-8")
    pad = 16 - (len(plain) % 16)
    plain += bytes([pad]) * pad
    c = Cipher(algorithms.AES(key), modes.CBC(b" " * 16), backend=default_backend())
    enc = c.encryptor()
    return b"v10" + enc.update(plain) + enc.finalize()


def _make_chromium_db(path, cookies):
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)"
    )
    con.executemany(
        "INSERT INTO cookies VALUES (?,?,?)",
        [(".claude.ai", n, _encrypt_v10(v)) for n, v in cookies],
    )
    con.commit()
    con.close()


def _make_firefox_db(path, cookies):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
    con.executemany(
        "INSERT INTO moz_cookies VALUES (?,?,?)",
        [(".claude.ai", n, v) for n, v in cookies],
    )
    con.commit()
    con.close()


SESSION = "sk-ant-sid01-EXAMPLE-TOKEN-1234567890"


class FirefoxTest(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".sqlite")
        self._globs = bc.FIREFOX_GLOBS
        bc.FIREFOX_GLOBS = [self.db]

    def tearDown(self):
        bc.FIREFOX_GLOBS = self._globs
        if os.path.exists(self.db):
            os.unlink(self.db)

    def test_plaintext_extraction(self):
        _make_firefox_db(self.db, [("sessionKey", SESSION), ("lastActiveOrg", "org-1")])
        cookie = bc.get_claude_cookie("firefox")
        self.assertIn(f"sessionKey={SESSION}", cookie)
        self.assertIn("lastActiveOrg=org-1", cookie)

    def test_not_logged_in(self):
        _make_firefox_db(self.db, [("other", "x")])
        with self.assertRaises(bc.BrowserCookieError):
            bc.get_claude_cookie("firefox")


class ChromiumTest(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.mktemp(suffix=".sqlite")
        self._globs = bc.CHROMIUM_BROWSERS["chrome"]["globs"]
        bc.CHROMIUM_BROWSERS["chrome"]["globs"] = [self.db]
        # forzar que NO use el keyring: solo el fallback "peanuts"
        self._kp = bc._keyring_passwords
        bc._keyring_passwords = lambda apps: [b"peanuts"]

    def tearDown(self):
        bc.CHROMIUM_BROWSERS["chrome"]["globs"] = self._globs
        bc._keyring_passwords = self._kp
        if os.path.exists(self.db):
            os.unlink(self.db)

    def test_encrypted_extraction(self):
        _make_chromium_db(self.db, [("sessionKey", SESSION), ("cf_clearance", "abc")])
        cookie = bc.get_claude_cookie("chrome")
        self.assertIn(f"sessionKey={SESSION}", cookie)
        self.assertIn("cf_clearance=abc", cookie)

    def test_no_session_key(self):
        _make_chromium_db(self.db, [("cf_clearance", "abc")])
        with self.assertRaises(bc.BrowserCookieError):
            bc.get_claude_cookie("chrome")


class AutodetectTest(unittest.TestCase):
    def test_unknown_browser(self):
        with self.assertRaises(bc.BrowserCookieError):
            bc.get_claude_cookie("netscape")


if __name__ == "__main__":
    unittest.main(verbosity=2)
