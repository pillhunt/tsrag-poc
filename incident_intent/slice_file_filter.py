"""Фильтрация строк среза по имени файла."""

from __future__ import annotations

from collections.abc import Callable

from incident_intent.log_filter_models import TimeWindowLine


def filter_lines_by_file(
    lines: list[TimeWindowLine],
    predicate: Callable[[str], bool],
) -> list[TimeWindowLine]:
    out: list[TimeWindowLine] = []
    for line in lines:
        path = line.file.replace("\\", "/")
        if predicate(path):
            out.append(line)
    return out


def file_name_lower(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1].lower()
