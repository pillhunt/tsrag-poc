"""Рекурсивный поиск файлов логов в каталоге."""

from __future__ import annotations

import os
import re
from pathlib import Path

from incident_intent.error_classifier import infer_log_kind

_LOG_SUFFIXES = (".log", ".txt", ".out", ".jsonl")
_LOG_ROLLING_SUFFIXES = (".log.1", ".log.2", ".log.gz", ".log.zip")

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "bin",
        "obj",
        "packages",
    }
)

_PRIORITY_LOG_NAMES = frozenset(
    {
        "CaseMap.Core.Infrastructure.RequestLoggingMiddleware.log",
        "global.log",
        "WorkflowTrace.log",
        "ClientLogs.log",
        "access.log",
        "error.log",
        "ERRORLOG",
    }
)

_RE_IIS = re.compile(r"^u_ex\d+\.log$", re.IGNORECASE)
_RE_PG = re.compile(r"^postgresql-\d{4}-\d{2}-\d{2}.*\.log$", re.IGNORECASE)


def is_log_filename(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(_LOG_SUFFIXES):
        return True
    if any(lower.endswith(suffix) for suffix in _LOG_ROLLING_SUFFIXES):
        return True
    if lower == "errorlog" or lower.startswith("errorlog."):
        return True
    if _RE_IIS.match(name):
        return True
    if _RE_PG.match(name):
        return True
    if lower.startswith("httperr") and lower.endswith(".log"):
        return True
    if lower.startswith("sqlagent") and lower.endswith(".out"):
        return True
    return False


def is_priority_log(name: str) -> bool:
    if name in _PRIORITY_LOG_NAMES:
        return True
    lower = name.lower()
    if "requestlogging" in lower and lower.endswith(".log"):
        return True
    if lower in ("access.log", "error.log", "errorlog"):
        return True
    if _RE_IIS.match(name) or _RE_PG.match(name):
        return True
    return False


def log_kind_for_path(relative_path: str) -> str:
    return infer_log_kind(relative_path)


def _sort_key(path: Path) -> tuple:
    return (not is_priority_log(path.name), path.name.lower())


def discover_log_files(
    root: Path,
    *,
    recursive: bool = True,
    max_depth: int | None = None,
    follow_symlinks: bool = False,
) -> list[Path]:
    """
    Найти файлы логов под root.

    - Если root — файл *.log / *.txt, вернуть только его.
    - Если recursive=False — только файлы в корне каталога (без подкаталогов).
    - Если recursive=True — обход всех подкаталогов (os.walk), с опциональным max_depth.
    """
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root

    if resolved.is_file():
        return [resolved] if is_log_filename(resolved.name) else []

    if not resolved.is_dir():
        return []

    if not recursive:
        files = [p for p in resolved.iterdir() if p.is_file() and is_log_filename(p.name)]
        return sorted(files, key=_sort_key)

    base_depth = len(resolved.parts)
    found: list[Path] = []

    for dirpath, dirnames, filenames in os.walk(
        resolved,
        topdown=True,
        followlinks=follow_symlinks,
        onerror=lambda _err: None,
    ):
        current = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES
            and not d.startswith(".")
            and d not in ("$Recycle.Bin", "System Volume Information")
        ]

        if max_depth is not None:
            depth = len(current.parts) - base_depth
            if depth > max_depth:
                dirnames.clear()
                continue

        for name in filenames:
            if is_log_filename(name):
                found.append(current / name)

    return sorted(found, key=_sort_key)
