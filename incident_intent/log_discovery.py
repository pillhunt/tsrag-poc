"""Рекурсивный поиск файлов логов в каталоге."""

from __future__ import annotations

import os
from pathlib import Path

_LOG_SUFFIXES = (".log", ".txt")
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
    }
)


def is_log_filename(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(_LOG_SUFFIXES):
        return True
    return any(lower.endswith(suffix) for suffix in _LOG_ROLLING_SUFFIXES)


def is_priority_log(name: str) -> bool:
    return name in _PRIORITY_LOG_NAMES or (
        "RequestLogging" in name and name.lower().endswith(".log")
    )


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
