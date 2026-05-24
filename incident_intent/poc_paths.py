"""Пути temp/caseone и каталоги инцидентов PoC."""

from __future__ import annotations

import os
from pathlib import Path

_POC_ROOT = Path(__file__).resolve().parent.parent


def poc_root() -> Path:
    return _POC_ROOT


def temp_dir() -> Path:
    raw = os.getenv("POC_TEMP_DIR", "").strip()
    base = Path(raw) if raw else _POC_ROOT / "temp"
    base.mkdir(parents=True, exist_ok=True)
    return base


def caseone_dir() -> Path:
    path = temp_dir() / "caseone"
    path.mkdir(parents=True, exist_ok=True)
    return path


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
