"""
Дополнение search_keywords английскими парами к русским токенам (шаг 0).

LLM в промпте просят добавить перевод, но это не гарантировано — здесь детерминированный словарь.
"""

from __future__ import annotations

import re

from incident_intent.keyword_utils import normalize_search_keywords

_CYRILLIC = re.compile(r"[\u0400-\u04FF]")

# Корень/подстрока (lower) → варианты для grep в логах CaseOne (.NET, SQL, UI)
_RU_STEM_TO_EN: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("таймаут", ("timeout", "Timeout", "timed out")),
    ("сохран", ("save", "Save", "Saving")),
    ("кнопк", ("button", "Button", "btn")),
    ("ошибк", ("error", "Error", "Exception")),
    ("исключен", ("Exception", "exception")),
    ("документ", ("document", "Document", "documents")),
    ("отчёт", ("report", "Report", "reports")),
    ("отчет", ("report", "Report")),
    ("вкладк", ("tab", "Tab", "UpdateProjectTab")),
    ("медлен", ("slow", "timeout")),
    ("завис", ("hang", "timeout", "deadlock")),
    ("блокир", ("deadlock", "lock", "blocked")),
    ("дедлок", ("deadlock", "Deadlock")),
    ("соединен", ("connection", "Connection", "connect")),
    ("обрыв", ("reset", "ConnectionReset", "disconnect")),
    ("сервер", ("server", "500", "Internal Server")),
    ("клиент", ("client", "Client", "browser")),
    ("браузер", ("browser", "client")),
    ("запрос", ("request", "Request")),
    ("ответ", ("response", "Response")),
    ("поиск", ("search", "Search", "FullSearchString")),
    ("проект", ("project", "Project", "Projects")),
    ("тип дела", ("ProjectType", "project type")),
    ("конфиг", ("config", "Configuration", "ProjectType")),
    ("форм", ("form", "Form")),
    ("загруз", ("load", "upload", "Loading")),
    ("удал", ("delete", "Delete", "remove")),
    ("обнов", ("update", "Update", "PUT")),
    ("создан", ("create", "Create", "POST")),
    ("sql", ("SqlException", "SQL", "sql")),
    ("баз", ("database", "SQL", "SqlException")),
    ("дубликат", ("duplicate", "Duplicate", "PK")),
    ("повтор", ("retry", "duplicate", "again")),
)


def _has_cyrillic(text: str) -> bool:
    return bool(_CYRILLIC.search(text))


def _english_for_token(token: str) -> list[str]:
    low = token.casefold()
    out: list[str] = []
    for stem, variants in _RU_STEM_TO_EN:
        if stem in low:
            out.extend(variants)
    return out


def expand_keywords_with_english(keywords: list[str] | None) -> tuple[list[str], list[str]]:
    """
    Для каждого keyword с кириллицей добавить английские эквиваленты из словаря.
    Возвращает (расширенный список, заметки для notes).
    """
    base = normalize_search_keywords(keywords)
    if not base:
        return [], []

    extra: list[str] = []
    notes: list[str] = []
    added_pairs: list[str] = []

    for kw in base:
        if not _has_cyrillic(kw):
            continue
        for en in _english_for_token(kw):
            if en.casefold() != kw.casefold():
                extra.append(en)
                if len(added_pairs) < 8:
                    added_pairs.append(f"«{kw}»→{en}")

    merged = normalize_search_keywords(base + extra)
    if len(merged) > len(base):
        notes.append(
            "К search_keywords добавлены английские пары из словаря PoC "
            f"({len(merged) - len(base)} шт.): "
            + ", ".join(added_pairs[:6])
            + ("…" if len(added_pairs) > 6 else "")
            + "."
        )
    return merged, notes
