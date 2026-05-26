"""Клиент Confluence (atlassian-python-api) — конфигурация из env."""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any

_CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "").strip()
_CONFLUENCE_CLOUD = os.getenv("CONFLUENCE_CLOUD", "false").lower() in (
    "1",
    "true",
    "yes",
)
_CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME", "").strip()
_CONFLUENCE_TOKEN = os.getenv("CONFLUENCE_TOKEN", "").strip()
_CONFLUENCE_PAT = os.getenv("CONFLUENCE_PAT", "").strip()
_CONFLUENCE_TIMEOUT = float(os.getenv("CONFLUENCE_TIMEOUT_SEC", "60"))


class ConfluenceNotConfigured(Exception):
    pass


class ConfluenceClientError(RuntimeError):
    pass


def is_confluence_configured() -> bool:
    if not _CONFLUENCE_URL:
        return False
    if _CONFLUENCE_PAT:
        return True
    return bool(_CONFLUENCE_USERNAME and _CONFLUENCE_TOKEN)


def confluence_config_summary() -> dict[str, Any]:
    return {
        "configured": is_confluence_configured(),
        "url": _CONFLUENCE_URL or None,
        "cloud": _CONFLUENCE_CLOUD,
        "username_set": bool(_CONFLUENCE_USERNAME),
        "token_set": bool(_CONFLUENCE_TOKEN or _CONFLUENCE_PAT),
        "space_key": os.getenv("CONFLUENCE_SPACE_KEY", "").strip() or None,
    }


@lru_cache(maxsize=1)
def get_confluence_client() -> Any:
    if not is_confluence_configured():
        raise ConfluenceNotConfigured(
            "Confluence не настроен: задайте CONFLUENCE_URL и CONFLUENCE_TOKEN "
            "(или CONFLUENCE_PAT для Server/DC)."
        )
    try:
        from atlassian import Confluence
    except ImportError as exc:
        raise ConfluenceClientError(
            "Установите atlassian-python-api: pip install atlassian-python-api"
        ) from exc

    kwargs: dict[str, Any] = {"url": _CONFLUENCE_URL.rstrip("/")}
    if _CONFLUENCE_PAT and not _CONFLUENCE_CLOUD:
        kwargs["token"] = _CONFLUENCE_PAT
    else:
        kwargs["username"] = _CONFLUENCE_USERNAME
        kwargs["password"] = _CONFLUENCE_TOKEN
    if _CONFLUENCE_CLOUD:
        kwargs["cloud"] = True
    return Confluence(**kwargs)


def build_page_url(page_id: str) -> str:
    base = _CONFLUENCE_URL.rstrip("/")
    if _CONFLUENCE_CLOUD:
        return f"{base}/wiki/spaces/~pages/{page_id}"
    return f"{base}/pages/viewpage.action?pageId={page_id}"


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()
