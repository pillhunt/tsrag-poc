"""Пути temp/caseone и каталоги инцидентов PoC."""

from __future__ import annotations

import os
from pathlib import Path

_POC_ROOT = Path(__file__).resolve().parent.parent

# Точка монтирования caseone в Docker (совпадает с target в docker-compose)
CASEONE_CONTAINER_PATH = "/caseone"


def poc_root() -> Path:
    return _POC_ROOT


def temp_dir() -> Path:
    raw = os.getenv("POC_TEMP_DIR", "").strip()
    base = Path(raw) if raw else _POC_ROOT / "temp"
    base.mkdir(parents=True, exist_ok=True)
    return base


def logs_dir() -> Path:
    """Каталог логов REN-*: ./logs на хосте, /app/logs в Docker."""
    raw = os.getenv("POC_LOGS_MOUNT", "").strip()
    if raw:
        path = Path(raw)
    elif Path("/.dockerenv").exists():
        path = Path("/app/logs")
    else:
        path = _POC_ROOT / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def caseone_dir() -> Path:
    path = temp_dir() / "caseone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_caseone_path() -> str:
    """Docker: смонтированный /caseone; локально — temp/caseone."""
    mount = Path(CASEONE_CONTAINER_PATH)
    if Path("/.dockerenv").exists() and mount.is_dir():
        return str(mount)
    return str(caseone_dir())


def incidents_root() -> Path:
    path = temp_dir() / "incidents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def incident_dir(incident_id: str) -> Path:
    path = incidents_root() / incident_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def incident_has_log_files(incident_id: str) -> bool:
    from incident_intent.log_discovery import discover_log_files

    root = incident_dir(incident_id)
    return bool(discover_log_files(root, recursive=True))
