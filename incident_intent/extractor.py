"""
Шаг 0 алгоритма разбора инцидента: таблица намерений из текста + опциональных путей.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from incident_intent.keyword_utils import normalize_search_keywords
from incident_intent.log_folder import hint_from_logs_path
from incident_intent.models import IntentField, IntentTable, IntentTableRequest, IntentTableResponse
from incident_intent.ollama_client import OllamaError, chat_json

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT_FILE = _PROMPTS_DIR / "intent_table_system.md"


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    if not _SYSTEM_PROMPT_FILE.is_file():
        raise FileNotFoundError(f"Не найден файл промпта: {_SYSTEM_PROMPT_FILE}")
    return _SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()


def _build_user_prompt(req: IntentTableRequest, log_hint_iso: str | None) -> str:
    parts = [
        "Описание инцидента от пользователя:",
        req.incident_description.strip(),
        "",
    ]
    if req.logs_path:
        parts.append(f"Путь к логам (контекст): {req.logs_path.strip()}")
        if log_hint_iso:
            parts.append(
                f"Подсказка: в пути логов уже извлечена дата {log_hint_iso} "
                "(используй её, если в тексте нет другой даты)."
            )
    if req.caseone_path:
        parts.append(f"Путь к caseone (контекст): {req.caseone_path.strip()}")
    parts.append(
        "\nЕсли в описании нет даты, но есть подсказка из пути логов — incident_date = эта дата, "
        "incident_date_source = user_text не подходит, в notes укажи что дата взята из пути."
    )
    return "\n".join(parts)


def _merge_date(
    llm_date: str | None,
    llm_source: str,
    folder_date: str | None,
) -> tuple[IntentField, list[str]]:
    notes: list[str] = []
    if folder_date and llm_date and folder_date != llm_date:
        notes.append(
            f"Дата в тексте/модели ({llm_date}) не совпадает с датой из папки логов ({folder_date}). "
            "Нужно уточнение у пользователя."
        )
        return (
            IntentField(value=None, source="unknown", note="; ".join(notes)),
            notes,
        )
    if folder_date:
        return IntentField(value=folder_date, source="log_folder", note="Из имени папки логов"), notes
    if llm_date:
        src = "user_text" if llm_source == "user_text" else "unknown"
        return IntentField(value=llm_date, source=src), notes
    return IntentField(value=None, source="unknown"), notes


def _hour_patterns(iso_date: str | None, start: str | None, end: str | None) -> list[str]:
    if not iso_date or not start or not end:
        return []
    try:
        sh = int(start.split(":")[0])
        eh = int(end.split(":")[0])
    except (ValueError, IndexError):
        return []
    if eh < sh:
        eh = sh
    return [f"{iso_date} {h:02d}:" for h in range(sh, eh + 1)]


def _table_from_llm(
    raw: dict[str, Any],
    req: IntentTableRequest,
    folder_date: str | None,
) -> IntentTable:
    llm_date = raw.get("incident_date")
    if llm_date in ("null", "", None):
        llm_date = None
    date_field, merge_notes = _merge_date(
        llm_date,
        str(raw.get("incident_date_source") or "unknown"),
        folder_date,
    )

    tw_start = raw.get("time_window_start")
    tw_end = raw.get("time_window_end")
    if tw_start in ("null", ""):
        tw_start = None
    if tw_end in ("null", ""):
        tw_end = None

    patterns = raw.get("log_search_patterns") or []
    if not isinstance(patterns, list):
        patterns = []
    patterns = [str(p) for p in patterns if p]
    if not patterns:
        patterns = _hour_patterns(date_field.value, tw_start, tw_end)

    notes = list(raw.get("notes") or [])
    notes.extend(merge_notes)
    log_hint = hint_from_logs_path(req.logs_path)
    if log_hint and log_hint.note and log_hint.iso_date is None:
        notes.append(log_hint.note)

    missing = list(raw.get("missing_fields") or [])
    questions = list(raw.get("clarifying_questions") or [])

    if not date_field.value and "incident_date" not in missing:
        missing.append("incident_date")
    if not tw_start and "time_window_start" not in missing:
        missing.append("time_window_start")
    if not tw_end and "time_window_end" not in missing:
        missing.append("time_window_end")
    if not (raw.get("symptoms") or []):
        missing.append("symptoms")

    search_keywords = normalize_search_keywords(
        [str(k) for k in (raw.get("search_keywords") or []) if k]
    )
    if not search_keywords and "search_keywords" not in missing:
        missing.append("search_keywords")
    if not search_keywords and not any("ключ" in q.lower() or "поиск" in q.lower() for q in questions):
        questions.append(
            "Уточните, какие слова или фрагменты искать в логах "
            "(русские и английские: API, ошибки, действия пользователя)."
        )

    if date_field.value is None and not any("дат" in q.lower() for q in questions):
        questions.append("Уточните дату инцидента (ДД.ММ.ГГГГ) или путь к папке логов с датой в имени.")
    if (tw_start is None or tw_end is None) and not any("врем" in q.lower() for q in questions):
        questions.append("Уточните интервал времени (с … до …) в локальном часовом поясе пользователя.")

    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    return IntentTable(
        incident_date=date_field,
        time_window_start=IntentField(value=tw_start, source="user_text" if tw_start else "unknown"),
        time_window_end=IntentField(value=tw_end, source="user_text" if tw_end else "unknown"),
        symptoms=[str(s) for s in (raw.get("symptoms") or []) if s],
        search_keywords=search_keywords,
        investigation_goal=str(
            raw.get("investigation_goal")
            or "Найти в логах долгие операции сохранения и ошибки сервера в указанном окне."
        ),
        optional_paths={
            "logs_path": req.logs_path,
            "caseone_path": req.caseone_path,
        },
        log_search_patterns=patterns,
        confidence=confidence,  # type: ignore[arg-type]
        missing_fields=missing,
        clarifying_questions=questions,
        notes=notes,
    )


async def build_intent_table(req: IntentTableRequest) -> IntentTableResponse:
    log_hint = hint_from_logs_path(req.logs_path)
    folder_date = log_hint.iso_date if log_hint else None

    try:
        raw = await chat_json(
            load_system_prompt(),
            _build_user_prompt(req, folder_date),
        )
    except OllamaError as exc:
        return IntentTableResponse(
            status="needs_clarification",
            clarifying_questions=[str(exc)],
        )

    table = _table_from_llm(raw, req, folder_date)

    critical_missing = [
        f
        for f in table.missing_fields
        if f
        in (
            "incident_date",
            "time_window_start",
            "time_window_end",
            "symptoms",
            "search_keywords",
        )
    ]
    if not table.search_keywords and "search_keywords" not in critical_missing:
        critical_missing.append("search_keywords")
    needs = bool(table.clarifying_questions) or bool(critical_missing) or table.incident_date.value is None

    if needs and table.confidence == "high":
        table.confidence = "medium"

    return IntentTableResponse(
        status="needs_clarification" if needs else "complete",
        table=table,
        clarifying_questions=table.clarifying_questions,
        raw_llm=raw,
    )
