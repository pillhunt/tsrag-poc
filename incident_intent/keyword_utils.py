"""Нормализация и сопоставление search_keywords (без привязки к типу инцидента)."""

from __future__ import annotations

_MIN_LEN = 2
_MAX_KEYWORDS = 25
_MAX_TOKEN_LEN = 48


def normalize_search_keywords(keywords: list[str] | None) -> list[str]:
    """Дедупликация с сохранением регистра первого вхождения."""
    if not keywords:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for item in keywords:
        if not item:
            continue
        token = str(item).strip()
        if len(token) < _MIN_LEN or len(token) > _MAX_TOKEN_LEN:
            continue
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
        if len(result) >= _MAX_KEYWORDS:
            break
    return result


def merge_keywords(*lists: list[str] | None) -> list[str]:
    merged: list[str] = []
    for lst in lists:
        if lst:
            merged.extend(lst)
    return normalize_search_keywords(merged)


def find_matching_keyword(line: str, keywords: list[str]) -> str | None:
    """Первое ключевое слово из списка, входящее в строку (без учёта регистра)."""
    if not line or not keywords:
        return None
    line_fold = line.casefold()
    for kw in keywords:
        if kw.casefold() in line_fold:
            return kw
    return None
