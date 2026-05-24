"""
Оркестратор пайплайна: шаги 1–8 строго последовательно.
"""

from __future__ import annotations

from dataclasses import dataclass

from incident_intent.caseone_config_index import index_caseone_config
from incident_intent.client_log_analysis import analyze_client_logs
from incident_intent.conclusion_models import IncidentConclusionRequest
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexRequest,
    ClientLogAnalysisRequest,
    WorkflowTraceAnalysisRequest,
)
from incident_intent.error_correlation import correlate_errors
from incident_intent.error_correlation_models import CorrelateErrorsRequest
from incident_intent.log_filter import filter_logs
from incident_intent.log_filter_models import FilterLogsRequest
from incident_intent.models import IntentTable
from incident_intent.pipeline_models import (
    PipelineRequest,
    PipelineResponse,
    PipelineStepLog,
    PipelineStepStatus,
)
from incident_intent.pipeline_summaries import (
    caseone_summary_lines,
    client_summary_lines,
    conclusion_summary_lines,
    errors_summary_lines,
    filter_summary_from_response,
    filter_summary_lines,
    slow_summary_lines,
    symptom_summary_lines,
    workflow_summary_lines,
)
from incident_intent.slow_requests import find_slow_requests
from incident_intent.slow_requests_models import SlowRequestsRequest
from incident_intent.symptom_search import search_symptoms
from incident_intent.symptom_search_models import SymptomSearchRequest
from incident_intent.workflow_trace_analysis import analyze_workflow_trace


@dataclass(frozen=True)
class _StepDef:
    number: int
    step_id: str
    title_suffix: str


PIPELINE_STEP_DEFS: tuple[_StepDef, ...] = (
    _StepDef(1, "filter", "Сужение логов по времени и проверка источников"),
    _StepDef(2, "symptoms", "Поиск по ключевым словам в срезе"),
    _StepDef(3, "slow", "Долгие HTTP-запросы"),
    _StepDef(4, "errors", "Ошибки и корреляция с долгими запросами"),
    _StepDef(5, "workflow_trace", "WorkflowTrace — этапы на клиенте"),
    _StepDef(6, "client_logs", "ClientLogs — события клиента"),
    _StepDef(7, "caseone_config", "Индекс конфигурации caseone"),
    _StepDef(8, "conclusion", "Итоговое заключение (LLM)"),
)


def step_title(number: int, suffix: str) -> str:
    return f"Шаг {number}. {suffix}"


def _log_step(
    steps: list[PipelineStepLog],
    defn: _StepDef,
    *,
    status: PipelineStepStatus,
    summary_lines: list[str],
) -> None:
    steps.append(
        PipelineStepLog(
            step_number=defn.number,
            step_id=defn.step_id,
            title=step_title(defn.number, defn.title_suffix),
            status=status,
            summary_lines=summary_lines,
        )
    )


def _build_filter_request(table: IntentTable, logs_path: str, caseone_path: str | None) -> FilterLogsRequest:
    return FilterLogsRequest(
        logs_path=logs_path,
        caseone_path=caseone_path,
        log_search_patterns=list(table.log_search_patterns or []),
        slow_log_search_patterns=list(table.slow_log_search_patterns or table.log_search_patterns or []),
        incident_date=table.incident_date.value,
        time_window_start=table.time_window_start.value,
        time_window_end=table.time_window_end.value,
        time_filter_strategy="auto",
        time_filter_mode=table.time_filter_mode,
    )


def _context_lines(filter_resp) -> list:
    slow = filter_resp.slow_time_window_lines
    if slow:
        return slow
    return filter_resp.time_window_lines


def run_pipeline_sync(req: PipelineRequest) -> PipelineResponse:
    """Шаги 1–7 синхронно; заключение (8) — без LLM, см. run_pipeline_async."""
    table = req.intent_table
    steps: list[PipelineStepLog] = []
    errors: list[str] = []

    d1 = PIPELINE_STEP_DEFS[0]
    filt = filter_logs(_build_filter_request(table, req.logs_path, req.caseone_path))
    if filt.status == "error" and not filt.time_window_lines:
        _log_step(steps, d1, status="error", summary_lines=filter_summary_lines(filt) or filt.errors)
        errors.extend(filt.errors or ["Шаг 1: не удалось получить срез логов."])
        return PipelineResponse(status="error", steps=steps, filter=filt, errors=errors)

    _log_step(steps, d1, status="ok", summary_lines=filter_summary_lines(filt))
    if not filt.time_window_lines and table.time_filter_mode != "full_corpus":
        errors.append("Шаг 1: срез пустой — проверьте дату и временное окно.")
        return PipelineResponse(
            status="error",
            steps=steps,
            filter=filt,
            filter_summary=filter_summary_from_response(filt),
            errors=errors,
        )

    fs = filter_summary_from_response(filt)
    tw = filt.time_window_lines
    slow_tw = filt.slow_time_window_lines or tw
    ctx = _context_lines(filt)

    d2 = PIPELINE_STEP_DEFS[1]
    keywords = list(table.search_keywords or [])
    if not keywords:
        _log_step(
            steps,
            d2,
            status="skipped",
            summary_lines=["Нет search_keywords — шаг пропущен."],
        )
        sym = None
    else:
        sym = search_symptoms(
            SymptomSearchRequest(
                logs_path=req.logs_path,
                log_search_patterns=table.log_search_patterns or [],
                time_window_lines=tw,
                search_keywords=keywords,
                caseone_path=req.caseone_path,
            )
        )
        st: PipelineStepStatus = "error" if sym.status == "error" else "ok"
        _log_step(steps, d2, status=st, summary_lines=symptom_summary_lines(sym))

    d3 = PIPELINE_STEP_DEFS[2]
    min_ms = table.min_slow_request_ms if table.min_slow_request_ms is not None else 60000
    slow = find_slow_requests(
        SlowRequestsRequest(
            logs_path=req.logs_path,
            log_search_patterns=table.log_search_patterns or [],
            time_window_lines=slow_tw,
            search_keywords=keywords,
            min_duration_ms=min_ms,
            filter_by_keywords=False,
            http_access_only=False,
        )
    )
    st3: PipelineStepStatus = "error" if slow.status == "error" else "ok"
    _log_step(steps, d3, status=st3, summary_lines=slow_summary_lines(slow))

    d4 = PIPELINE_STEP_DEFS[3]
    err = correlate_errors(
        CorrelateErrorsRequest(
            logs_path=req.logs_path,
            log_search_patterns=table.log_search_patterns or [],
            time_window_lines=slow_tw,
            slow_requests=slow.slow_requests if slow else [],
        )
    )
    st4: PipelineStepStatus = "error" if err.status == "error" else "ok"
    _log_step(steps, d4, status=st4, summary_lines=errors_summary_lines(err))

    d5 = PIPELINE_STEP_DEFS[4]
    wt = analyze_workflow_trace(WorkflowTraceAnalysisRequest(time_window_lines=ctx))
    _log_step(steps, d5, status="ok", summary_lines=workflow_summary_lines(wt))

    d6 = PIPELINE_STEP_DEFS[5]
    cl = analyze_client_logs(ClientLogAnalysisRequest(time_window_lines=ctx))
    _log_step(steps, d6, status="ok", summary_lines=client_summary_lines(cl))

    d7 = PIPELINE_STEP_DEFS[6]
    co_path = (req.caseone_path or "").strip()
    if not co_path:
        _log_step(steps, d7, status="skipped", summary_lines=["caseone_path не задан — шаг пропущен."])
        cc = None
    else:
        cc = index_caseone_config(
            CaseoneConfigIndexRequest(caseone_path=co_path, search_keywords=keywords)
        )
        st7: PipelineStepStatus = "error" if cc.status == "error" else "ok"
        _log_step(steps, d7, status=st7, summary_lines=caseone_summary_lines(cc))

    return PipelineResponse(
        status="ok",
        steps=steps,
        filter_summary=fs,
        filter=filt,
        symptom_search=sym,
        slow_requests=slow,
        error_correlation=err,
        workflow_trace=wt,
        client_logs=cl,
        caseone_config=cc,
        errors=errors,
    )


async def run_incident_pipeline(req: PipelineRequest) -> PipelineResponse:
    """Полный пайплайн шагов 1–8, включая LLM на шаге 8."""
    from incident_intent.incident_conclusion import build_incident_conclusion

    base = run_pipeline_sync(req)
    if base.status == "error" or base.filter is None or base.filter_summary is None:
        return slim_filter_for_client(base)

    d8 = PIPELINE_STEP_DEFS[7]
    steps = list(base.steps)
    concl_req = IncidentConclusionRequest(
        intent_table=req.intent_table,
        filter_summary=base.filter_summary,
        symptom_search=base.symptom_search,
        slow_requests=base.slow_requests,
        error_correlation=base.error_correlation,
        workflow_trace=base.workflow_trace,
        client_logs=base.client_logs,
        caseone_config=base.caseone_config,
        caseone_path=req.caseone_path,
    )
    conclusion = await build_incident_conclusion(concl_req)
    st8: PipelineStepStatus = "error" if conclusion.status == "error" else "ok"
    _log_step(steps, d8, status=st8, summary_lines=conclusion_summary_lines(conclusion))

    overall: str = "ok"
    if conclusion.status == "error":
        overall = "partial"
    if any(s.status == "error" for s in steps):
        overall = "partial" if overall == "ok" else "error"

    out = base.model_copy(
        update={
            "status": overall,  # type: ignore[arg-type]
            "steps": steps,
            "conclusion": conclusion,
            "errors": list(base.errors) + list(conclusion.errors),
        }
    )
    return slim_filter_for_client(out)


def slim_filter_for_client(resp: PipelineResponse) -> PipelineResponse:
    """Убрать тяжёлые срезы из JSON для клиента."""
    if resp.filter is None:
        return resp
    slim = resp.filter.model_copy(
        update={"time_window_lines": [], "slow_time_window_lines": []}
    )
    return resp.model_copy(update={"filter": slim})
