"""
Shim de compatibilidad: la extracción de cookies vive ahora en
`browser_cookies.py` (multi-navegador). Este módulo se mantiene para no romper
imports/scripts existentes (`import chrome_cookies`).
"""

from browser_cookies import (  # noqa: F401
    get_claude_cookie,
    list_sources,
    BrowserCookieError,
    ChromeCookieError,
)

if __name__ == "__main__":
    import browser_cookies

    browser_cookies.__name__  # nada, solo para linters
    for src in list_sources():
        print(f"{src['browser']:9s} {src['status']:40s} {src['db']}")
