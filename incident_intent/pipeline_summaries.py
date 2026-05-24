"""Краткие строки итога для журнала пайплайна."""

from __future__ import annotations

from incident_intent.conclusion_models import FilterSummary, IncidentConclusionResponse
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexResponse,
    ClientLogAnalysisResponse,
    WorkflowTraceAnalysisResponse,
)
from incident_intent.error_correlation_models import CorrelateErrorsResponse
from incident_intent.log_filter_models import FilterLogsResponse
from incident_intent.slow_requests_models import SlowRequestsResponse
from incident_intent.symptom_search_models import SymptomSearchResponse


def filter_summary_lines(data: FilterLogsResponse) -> list[str]:
    sources = data.sources
    n_files = sources.log_file_count if sources else 0
    lines = [
        f"Файлов логов: {n_files}",
        f"Строк в окне жалобы: {len(data.time_window_lines)} / {data.total_matching_lines}",
    ]
    slow_n = len(data.slow_time_window_lines)
    if slow_n and slow_n != len(data.time_window_lines):
        lines.append(
            f"Расширенное окно: {slow_n} / {data.slow_time_window_total_count or slow_n}"
        )
    if data.time_window_truncated:
        lines.append("Срез жалобы обрезан по лимиту.")
    if data.detected_format_summary:
        lines.append("Форматы: " + ", ".join(data.detected_format_summary[:5]))
    if data.errors:
        lines.append(data.errors[0][:200])
    return lines


def filter_summary_from_response(data: FilterLogsResponse) -> FilterSummary:
    return FilterSummary(
        total_matching_lines=data.total_matching_lines,
        time_window_line_count=len(data.time_window_lines),
        time_window_truncated=data.time_window_truncated,
        slow_time_window_line_count=len(data.slow_time_window_lines),
        slow_time_window_truncated=data.slow_time_window_truncated,
        files_in_window=data.files_in_window,
        patterns_used=data.patterns_used,
        slow_patterns_used=data.slow_patterns_used,
        time_filter_mode=data.time_filter_mode,
    )


def symptom_summary_lines(data: SymptomSearchResponse) -> list[str]:
    if data.status == "error":
        return data.errors[:3] or ["Ошибка шага."]
    return [
        f"Ключевых слов: {len(data.search_keywords_used)}",
        f"Совпадений в срезе: {data.total_matching_lines}",
    ] + (data.conclusions[:2] if data.conclusions else [])


def slow_summary_lines(data: SlowRequestsResponse) -> list[str]:
    if data.status == "error":
        return data.errors[:3] or ["Ошибка шага."]
    lines = [
        f"Порог: {data.min_duration_ms} ms",
        f"Долгих запросов: {len(data.slow_requests)}",
    ]
    if data.slow_requests:
        top = data.slow_requests[0]
        lines.append(f"Макс: {top.method or '?'} {top.path or '?'} — {top.duration_min:.1f} мин")
    return lines + (data.conclusions[:1] if data.conclusions else [])


def errors_summary_lines(data: CorrelateErrorsResponse) -> list[str]:
    if data.status == "error":
        return data.errors[:3] or ["Ошибка шага."]
    return [
        f"Ошибок в окне: {len(data.errors_in_window)}",
        f"Корреляций с долгими запросами: {len(data.correlations)}",
    ] + (data.conclusions[:2] if data.conclusions else [])


def workflow_summary_lines(data: WorkflowTraceAnalysisResponse) -> list[str]:
    if not data.ran:
        return data.conclusions[:2] or ["WorkflowTrace в срезе не найден."]
    return [
        f"Строк WorkflowTrace: {data.line_count}",
        f"Пар начало/конец: {len(data.paired_operations)}",
    ] + (data.conclusions[:2] if data.conclusions else [])


def client_summary_lines(data: ClientLogAnalysisResponse) -> list[str]:
    if not data.ran:
        return data.conclusions[:2] or ["ClientLogs в срезе не найдены."]
    parts = [f"Событий клиента: {data.event_count}"]
    if data.by_category:
        top = max(data.by_category.items(), key=lambda x: x[1])
        parts.append(f"Топ категория: {top[0]} ({top[1]})")
    return parts + (data.conclusions[:1] if data.conclusions else [])


def caseone_summary_lines(data: CaseoneConfigIndexResponse) -> list[str]:
    if data.status == "error":
        return data.errors[:3] or ["Ошибка шага."]
    if not data.ran:
        return data.conclusions[:2] or ["Конфиг caseone не проиндексирован."]
    return [
        f"Файлов просмотрено: {data.files_scanned}",
        f"Фрагментов в досье: {len(data.snippets)}",
    ] + (data.conclusions[:1] if data.conclusions else [])


def conclusion_summary_lines(data: IncidentConclusionResponse) -> list[str]:
    if data.status == "error":
        return data.errors[:3] or ["Ошибка LLM."]
    lines = [f"Уверенность: {data.confidence}"]
    if data.confidence_reason:
        lines.append(data.confidence_reason[:240])
    lines.append(f"Поддержано фактами: {len(data.supported_by)} пунктов")
    return lines
