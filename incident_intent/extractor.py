"""
Шаг 0: таблица намерений из текста, диалога и путей инцидента.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from incident_intent.dialog_parse import (
    is_datetime_clarification,
    parse_date_from_dialog,
    parse_time_from_dialog,
)
from incident_intent.duration_utils import normalize_min_slow_request_ms
from incident_intent.keyword_utils import normalize_search_keywords
from incident_intent.log_folder import hint_from_logs_path
from incident_intent.models import IntentField, IntentTable, IntentTableRequest, IntentTableResponse
from incident_intent.ollama_client import OllamaError, chat_json
from incident_intent.time_window_utils import (
    expand_single_time_window,
    hour_patterns,
    slow_log_search_patterns,
)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_SYSTEM_PROMPT_FILE = _PROMPTS_DIR / "intent_table_system.md"

_FULL_CORPUS_NOTE = (
    "Временной интервал не задан: шаги 1–2 будут использовать все строки логов "
    "(до лимита). Вывод может быть некорректным."
)


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
    if "Пользователь:" in req.incident_description and "Ассистент:" in req.incident_description:
        parts.append(
            "\nНиже — переписка диалога (не одно сообщение). "
            "Учитывай все реплики пользователя после вопроса ассистента. "
            "Если ответ уже дан — не задавай тот же вопрос снова (clarifying_questions = [])."
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


def _parse_optional_float(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apply_slow_window_and_duration(table: IntentTable, raw: dict[str, Any], req: IntentTableRequest) -> None:
    """Расширенное окно для шагов 4–5 и порог min_slow_request_ms."""
    date = table.incident_date.value
    start = table.time_window_start.value
    end = table.time_window_end.value

    if date and start and end and table.time_filter_mode != "full_corpus":
        slow_pats, slow_notes = slow_log_search_patterns(date, start, end)
        table.slow_log_search_patterns = slow_pats
        table.notes.extend(slow_notes)
    elif table.log_search_patterns:
        table.slow_log_search_patterns = list(table.log_search_patterns)

    rep_min = _parse_optional_float(raw.get("reported_duration_min_minutes"))
    rep_max = _parse_optional_float(raw.get("reported_duration_max_minutes"))
    table.reported_duration_min_minutes = rep_min
    table.reported_duration_max_minutes = rep_max

    context = " ".join(
        [
            req.incident_description,
            " ".join(table.symptoms),
            table.investigation_goal or "",
        ]
    )
    ms, dur_notes = normalize_min_slow_request_ms(
        raw.get("min_slow_request_ms"),
        reported_min_minutes=rep_min,
        reported_max_minutes=rep_max,
        context_text=context,
    )
    table.min_slow_request_ms = ms
    table.notes.extend(dur_notes)


def _pick_one_question(questions: list[str]) -> list[str]:
    cleaned = [str(q).strip() for q in questions if q and str(q).strip()]
    return cleaned[:1]


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

    tw_start, tw_end, pad_notes = expand_single_time_window(
        date_field.value,
        str(tw_start) if tw_start else None,
        str(tw_end) if tw_end else None,
    )

    patterns = raw.get("log_search_patterns") or []
    if not isinstance(patterns, list):
        patterns = []
    patterns = [str(p) for p in patterns if p]
    if not patterns:
        patterns = hour_patterns(date_field.value, tw_start, tw_end)

    notes = list(raw.get("notes") or [])
    notes.extend(merge_notes)
    notes.extend(pad_notes)
    log_hint = hint_from_logs_path(req.logs_path)
    if log_hint and log_hint.note and log_hint.iso_date is None:
        notes.append(log_hint.note)

    missing = list(raw.get("missing_fields") or [])
    questions = _pick_one_question(list(raw.get("clarifying_questions") or []))

    if not req.user_force_complete:
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
        if not search_keywords and not questions:
            questions = [
                "Уточните, какие слова или фрагменты искать в логах "
                "(русские и английские: API, ошибки, действия пользователя)."
            ]

        if date_field.value is None and not questions:
            questions = [
                "Уточните дату инцидента (ДД.ММ.ГГГГ) или загрузите логи с датой в имени папки."
            ]
        if (tw_start is None or tw_end is None) and not questions:
            questions = [
                "Уточните интервал времени (с … до …) или одну метку времени в локальном часовом поясе."
            ]
    else:
        search_keywords = normalize_search_keywords(
            [str(k) for k in (raw.get("search_keywords") or []) if k]
        )

    questions = _pick_one_question(questions)

    confidence = str(raw.get("confidence") or "medium").lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"

    time_filter_mode: str = "time_window"
    if req.user_force_complete and not patterns:
        time_filter_mode = "full_corpus"
        notes.append(_FULL_CORPUS_NOTE)
        if confidence == "high":
            confidence = "medium"

    table = IntentTable(
        incident_date=date_field,
        time_window_start=IntentField(value=tw_start, source="user_text" if tw_start else "unknown"),
        time_window_end=IntentField(value=tw_end, source="user_text" if tw_end else "unknown"),
        symptoms=[str(s) for s in (raw.get("symptoms") or []) if s],
        search_keywords=search_keywords,
        investigation_goal=str(
            raw.get("investigation_goal")
            or "Найти в логах долгие операции и ошибки сервера в указанном окне."
        ),
        optional_paths={
            "logs_path": req.logs_path,
            "caseone_path": req.caseone_path,
        },
        log_search_patterns=patterns,
        time_filter_mode=time_filter_mode,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
        missing_fields=missing,
        clarifying_questions=questions,
        notes=notes,
    )
    return table


def _core_fields_ready(table: IntentTable) -> bool:
    return bool(
        table.incident_date.value
        and table.time_window_start.value
        and table.time_window_end.value
        and table.symptoms
        and table.search_keywords
        and table.log_search_patterns
    )


def _enrich_table_from_dialog(table: IntentTable, req: IntentTableRequest) -> None:
    """Дата/время из реплик пользователя — не полагаемся только на LLM."""
    text = req.incident_description.strip()
    if not text:
        return

    dialog_date = parse_date_from_dialog(text)
    if dialog_date and not table.incident_date.value:
        table.incident_date = IntentField(
            value=dialog_date,
            source="user_text",
            note="Извлечено из текста диалога",
        )
        table.notes.append(f"Дата из диалога: {dialog_date}")

    ts, te = parse_time_from_dialog(text)
    if ts and not table.time_window_start.value:
        table.time_window_start = IntentField(value=ts, source="user_text")
    if te and not table.time_window_end.value:
        table.time_window_end = IntentField(value=te, source="user_text")

    if table.time_window_start.value and table.time_window_end.value:
        ts2, te2, pad = expand_single_time_window(
            table.incident_date.value,
            table.time_window_start.value,
            table.time_window_end.value,
        )
        table.time_window_start = IntentField(value=ts2, source="user_text")
        table.time_window_end = IntentField(value=te2, source="user_text")
        table.notes.extend(pad)

    if not table.log_search_patterns and table.incident_date.value:
        table.log_search_patterns = hour_patterns(
            table.incident_date.value,
            table.time_window_start.value,
            table.time_window_end.value,
        )

    table.missing_fields = [
        f
        for f in table.missing_fields
        if not (
            (f == "incident_date" and table.incident_date.value)
            or (f == "time_window_start" and table.time_window_start.value)
            or (f == "time_window_end" and table.time_window_end.value)
        )
    ]

    if table.clarifying_questions and is_datetime_clarification(table.clarifying_questions[0]):
        if (
            table.incident_date.value
            and table.time_window_start.value
            and table.time_window_end.value
        ):
            table.clarifying_questions = []


def _resolve_status(table: IntentTable, req: IntentTableRequest) -> str:
    if req.user_force_complete:
        if not table.log_search_patterns:
            table.time_filter_mode = "full_corpus"
            if _FULL_CORPUS_NOTE not in table.notes:
                table.notes.append(_FULL_CORPUS_NOTE)
        return "complete"

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

    # Лишний вопрос LLM (не про date/time/keywords) не блокирует шаги 1–6
    if _core_fields_ready(table) and not critical_missing:
        if table.clarifying_questions:
            table.notes.append(
                "Уточняющий вопрос модели не блокирует разбор: основные поля заполнены."
            )
        table.clarifying_questions = []
        return "complete"

    needs = bool(table.clarifying_questions) or bool(critical_missing) or table.incident_date.value is None
    if needs and table.confidence == "high":
        table.confidence = "medium"
    return "needs_clarification" if needs else "complete"


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
    _enrich_table_from_dialog(table, req)
    _apply_slow_window_and_duration(table, raw, req)
    status = _resolve_status(table, req)

    return IntentTableResponse(
        status=status,
        table=table,
        clarifying_questions=table.clarifying_questions,
        raw_llm=raw,
    )
