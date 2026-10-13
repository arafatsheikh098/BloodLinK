"""Translation helper.

All user-facing strings come from translation dictionaries (F10). The
`t(key)` function reads the request-scoped language cookie and looks the key
up in the appropriate JSON file. A test (test_i18n.py) asserts that en.json
and bn.json share the same key set.
"""
from __future__ import annotations

import json
from functools import cache
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).parent / "translations"
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "bn")
COOKIE_NAME = "lang"


@cache
def _load(lang: str) -> dict[str, str]:
    path = TRANSLATIONS_DIR / f"{lang}.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_dict(lang: str) -> dict[str, str]:
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    return _load(lang)


def available_keys() -> set[str]:
    return set(get_dict(DEFAULT_LANG).keys())


def t(key: str, lang: str = DEFAULT_LANG, **params: object) -> str:
    """Look up a translation key. Falls back to English, then to the key itself.

    Params are not interpolated by default (we keep things simple) but the
    signature accepts them for future use.
    """
    d = get_dict(lang)
    if key in d:
        return d[key]
    if lang != DEFAULT_LANG:
        d_en = get_dict(DEFAULT_LANG)
        if key in d_en:
            return d_en[key]
    return key
