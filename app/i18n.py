"""Interface language. HUB_LANG picks a file in app/lang/*.json (flat JSON, keys like "login.title").

A key missing in the chosen language falls back to English. Never call t() at import time:
LANG is read at every lookup (tests switch it).
"""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path

from markupsafe import Markup, escape

LANG_DIR = Path(__file__).parent / "lang"
DEFAULT = "en"
ALIASES = {"no": "nb"}


def available() -> list[str]:
    return sorted(p.stem for p in LANG_DIR.glob("*.json"))


def resolve(value: str | None) -> str:
    lang = (value or "").strip().lower() or DEFAULT
    lang = ALIASES.get(lang, lang)
    if lang not in available():
        raise SystemExit(f"HUB_LANG must be one of: {', '.join(available())} (got '{value}')")
    return lang


LANG = resolve(os.environ.get("HUB_LANG"))


@functools.cache
def _load(lang: str) -> dict:
    return json.loads((LANG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _get(lang: str, key: str):
    own = _load(lang)
    if key in own:
        return own[key]
    en = _load(DEFAULT)
    if key in en:
        return en[key]
    raise KeyError(key)


def t_in(lang: str, key: str, /, **vars) -> str:
    return _get(lang, key).format_map(vars)


def t(key: str, /, **vars) -> str:
    return t_in(LANG, key, **vars)


def tn(key: str, n: int, /, **vars) -> str:
    return t(key + (".one" if n == 1 else ".other"), **vars, n=n)


def t_list(key: str) -> list[str]:
    return list(_get(LANG, key))


def t_html(key: str, /, **vars) -> Markup:
    return Markup(_get(LANG, key)).format_map({k: escape(v) for k, v in vars.items()})


def raw(key: str):
    return _get(LANG, key)


def js(prefix: str) -> dict:
    out = {}
    for lang in (DEFAULT, LANG):
        for k, v in _load(lang).items():
            if k.startswith(prefix):
                out[k[len(prefix):]] = v
    return out
