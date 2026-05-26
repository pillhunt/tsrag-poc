"""
Оркестратор пайплайна: filter → скан артефактов → Confluence → gate → анализ или playbook.
"""

from __future__ import annotations

from dataclasses import dataclass

from incident_intent.artifact_scan import scan_artifacts
from incident_intent.artifact_scan_models import ArtifactScanRequest
from incident_intent.caseone_config_index import index_caseone_config
from incident_intent.client_log_analysis import analyze_client_logs
from incident_intent.conclusion_models import IncidentConclusionRequest
from incident_intent.confluence_models import ConfluenceSearchRequest, PlaybookGateRequest
from incident_intent.confluence_search import search_confluence_playbooks
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
    artifact_scan_summary_lines,
    caseone_summary_lines,
    client_summary_lines,
    confluence_summary_lines,
    errors_summary_lines,
    filter_summary_from_response,
    filter_summary_lines,
    gate_summary_lines,
    slow_summary_lines,
    symptom_summary_lines,
    workflow_summary_lines,
)
from incident_intent.playbook_gate import evaluate_playbook_gate
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
    _StepDef(1, "filter", "Проверка артефактов и срез по времени"),
    _StepDef(2, "artifact_scan", "Keywords и якоря в логах (узкое и широкое окно)"),
    _StepDef(3, "confluence", "Поиск решения в Confluence"),
    _StepDef(4, "playbook_gate", "Решение: playbook или полный разбор"),
    _StepDef(5, "symptoms", "Поиск keywords в срезе"),
    _StepDef(6, "slow", "Долгие HTTP-запросы"),
    _StepDef(7, "errors", "Ошибки и корреляция с долгими запросами"),
    _StepDef(8, "workflow_trace", "WorkflowTrace — этапы на клиенте"),
    _StepDef(9, "client_logs", "ClientLogs — события клиента"),
    _StepDef(10, "caseone_config", "Индекс конфигурации caseone"),
    _StepDef(11, "conclusion", "Playbook (Confluence) или заключение LLM"),
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


def _build_artifact_scan_request(
    table: IntentTable, logs_path: str, caseone_path: str | None
) -> ArtifactScanRequest:
    return ArtifactScanRequest(
        logs_path=logs_path,
        caseone_path=caseone_path,
        log_search_patterns=list(table.log_search_patterns or []),
        slow_log_search_patterns=list(table.slow_log_search_patterns or table.log_search_patterns or []),
        incident_date=table.incident_date.value,
        time_window_start=table.time_window_start.value,
        time_window_end=table.time_window_end.value,
        search_keywords=list(table.search_keywords or []),
        anchors=list(table.anchors or []),
        time_filter_mode=table.time_filter_mode,
    )


def _context_lines(filter_resp) -> list:
    slow = filter_resp.slow_time_window_lines
    if slow:
        return slow
    return filter_resp.time_window_lines


def _log_skipped_full_analysis(steps: list[PipelineStepLog], *, reason: str) -> None:
    for defn in PIPELINE_STEP_DEFS[4:10]:
        _log_step(
            steps,
            defn,
            status="skipped",
            summary_lines=[f"Пропущено: {reason}"],
        )


def run_pipeline_sync(req: PipelineRequest) -> PipelineResponse:
    """Шаги 1–10 синхронно; заключение (11) — в run_incident_pipeline."""
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

    d2 = PIPELINE_STEP_DEFS[1]
    scan = scan_artifacts(_build_artifact_scan_request(table, req.logs_path, req.caseone_path))
    st_scan: PipelineStepStatus = "error" if scan.status == "error" else "ok"
    _log_step(steps, d2, status=st_scan, summary_lines=artifact_scan_summary_lines(scan))
    if scan.status == "error":
        errors.extend(scan.errors or ["Шаг 2: ошибка скана артефактов."])

    d3 = PIPELINE_STEP_DEFS[2]
    conf = search_confluence_playbooks(
        ConfluenceSearchRequest(
            anchors=scan.anchors_for_search,
            symptoms=list(table.symptoms or []),
            investigation_goal=table.investigation_goal or "",
            keywords=list(table.search_keywords or []),
        )
    )
    st_conf: PipelineStepStatus = (
        "skipped" if conf.status == "skipped" else "error" if conf.status == "error" else "ok"
    )
    _log_step(steps, d3, status=st_conf, summary_lines=confluence_summary_lines(conf))

    d4 = PIPELINE_STEP_DEFS[3]
    gate = evaluate_playbook_gate(
        PlaybookGateRequest(
            confluence=conf,
            anchors_for_search=scan.anchors_for_search,
            anchor_hits=scan.anchor_hits,
        )
    )
    _log_step(steps, d4, status="ok", summary_lines=gate_summary_lines(gate))

    if gate.use_playbook:
        _log_skipped_full_analysis(
            steps,
            reason="выбран playbook из Confluence",
        )
        return PipelineResponse(
            status="ok",
            steps=steps,
            filter_summary=fs,
            filter=filt,
            artifact_scan=scan,
            confluence_search=conf,
            playbook_gate=gate,
            use_playbook=True,
            errors=errors,
        )

    ctx = _context_lines(filt)
    keywords = list(table.search_keywords or [])

    d5 = PIPELINE_STEP_DEFS[4]
    if not keywords:
        _log_step(
            steps,
            d5,
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
        st_sym: PipelineStepStatus = "error" if sym.status == "error" else "ok"
        _log_step(steps, d5, status=st_sym, summary_lines=symptom_summary_lines(sym))

    d6 = PIPELINE_STEP_DEFS[5]
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
    st6: PipelineStepStatus = "error" if slow.status == "error" else "ok"
    _log_step(steps, d6, status=st6, summary_lines=slow_summary_lines(slow))

    d7 = PIPELINE_STEP_DEFS[6]
    err = correlate_errors(
        CorrelateErrorsRequest(
            logs_path=req.logs_path,
            log_search_patterns=table.log_search_patterns or [],
            time_window_lines=slow_tw,
            slow_requests=slow.slow_requests if slow else [],
        )
    )
    st7: PipelineStepStatus = "error" if err.status == "error" else "ok"
    _log_step(steps, d7, status=st7, summary_lines=errors_summary_lines(err))

    d8 = PIPELINE_STEP_DEFS[7]
    wt = analyze_workflow_trace(WorkflowTraceAnalysisRequest(time_window_lines=ctx))
    _log_step(steps, d8, status="ok", summary_lines=workflow_summary_lines(wt))

    d9 = PIPELINE_STEP_DEFS[8]
    cl = analyze_client_logs(ClientLogAnalysisRequest(time_window_lines=ctx))
    _log_step(steps, d9, status="ok", summary_lines=client_summary_lines(cl))

    d10 = PIPELINE_STEP_DEFS[9]
    co_path = (req.caseone_path or "").strip()
    if not co_path:
        _log_step(steps, d10, status="skipped", summary_lines=["caseone_path не задан — шаг пропущен."])
        cc = None
    else:
        cc = index_caseone_config(
            CaseoneConfigIndexRequest(caseone_path=co_path, search_keywords=keywords)
        )
        st10: PipelineStepStatus = "error" if cc.status == "error" else "ok"
        _log_step(steps, d10, status=st10, summary_lines=caseone_summary_lines(cc))

    return PipelineResponse(
        status="ok",
        steps=steps,
        filter_summary=fs,
        filter=filt,
        artifact_scan=scan,
        confluence_search=conf,
        playbook_gate=gate,
        use_playbook=False,
        symptom_search=sym,
        slow_requests=slow,
        error_correlation=err,
        workflow_trace=wt,
        client_logs=cl,
        caseone_config=cc,
        errors=errors,
    )


async def run_incident_pipeline(req: PipelineRequest) -> PipelineResponse:
    """Полный пайплайн, шаг 11: playbook из Confluence или LLM."""
    from incident_intent.incident_conclusion import build_incident_conclusion
    from incident_intent.pipeline_summaries import conclusion_summary_lines
    from incident_intent.render_playbook import build_playbook_conclusion

    base = run_pipeline_sync(req)
    if base.status == "error" or base.filter is None or base.filter_summary is None:
        return slim_filter_for_client(base)

    d11 = PIPELINE_STEP_DEFS[10]
    steps = list(base.steps)

    if base.use_playbook and base.confluence_search and base.artifact_scan and base.playbook_gate:
        conclusion = build_playbook_conclusion(
            base.confluence_search,
            base.artifact_scan,
            shared_anchors=base.playbook_gate.shared_anchors,
        )
        st11: PipelineStepStatus = "error" if conclusion.status == "error" else "ok"
        _log_step(steps, d11, status=st11, summary_lines=conclusion_summary_lines(conclusion))
    else:
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
            artifact_scan=base.artifact_scan,
            confluence_search=base.confluence_search,
        )
        conclusion = await build_incident_conclusion(concl_req)
        st11 = "error" if conclusion.status == "error" else "ok"
        _log_step(steps, d11, status=st11, summary_lines=conclusion_summary_lines(conclusion))

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
