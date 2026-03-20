from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .i18n_catalogs import CATALOGS

DEFAULT_LOCALE = "en"
SUPPORTED_LOCALES = ("en", "zh-CN")

_LOCALE_ALIASES = {
    "en": "en",
    "en-us": "en",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
}

LOCALE_SWITCH_ITEMS = (
    {"code": "en", "label": "English", "testid": "dashboard-locale-en"},
    {"code": "zh-CN", "label": "简体中文", "testid": "dashboard-locale-zh-cn"},
)

_CATALOGS: dict[str, dict[str, Any]] = CATALOGS


def resolve_locale(locale: str | None = None) -> str:
    if locale is None:
        return DEFAULT_LOCALE
    normalized = locale.strip().lower()
    if not normalized:
        return DEFAULT_LOCALE
    return _LOCALE_ALIASES.get(normalized, DEFAULT_LOCALE)


def get_messages(locale: str = DEFAULT_LOCALE) -> Mapping[str, Any]:
    return _CATALOGS[resolve_locale(locale)]


__all__ = [
    "DEFAULT_LOCALE",
    "LOCALE_SWITCH_ITEMS",
    "SUPPORTED_LOCALES",
    "get_messages",
    "resolve_locale",
]
