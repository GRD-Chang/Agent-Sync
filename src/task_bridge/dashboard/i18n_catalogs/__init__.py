from __future__ import annotations

from typing import Any

from .en import EN_MESSAGES
from .zh_cn import ZH_CN_MESSAGES

CATALOGS: dict[str, dict[str, Any]] = {
    "en": EN_MESSAGES,
    "zh-CN": ZH_CN_MESSAGES,
}

__all__ = ["CATALOGS", "EN_MESSAGES", "ZH_CN_MESSAGES"]
