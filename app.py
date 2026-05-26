"""
PoC: разбор инцидента — диалог + шаги 0–6.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

_APP_DIR = Path(__file__).resolve().parent
load_dotenv(_APP_DIR / "env" / "docker.env")
load_dotenv(_APP_DIR / ".env")

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from incident_intent.caseone_config_index import index_caseone_config
from incident_intent.client_log_analysis import analyze_client_logs
from incident_intent.conclusion_models import (
    IncidentConclusionRequest,
    IncidentConclusionResponse,
)
from incident_intent.e_analysis_models import (
    CaseoneConfigIndexRequest,
    CaseoneConfigIndexResponse,
    ClientLogAnalysisRequest,
    ClientLogAnalysisResponse,
    WorkflowTraceAnalysisRequest,
    WorkflowTraceAnalysisResponse,
)
from incident_intent.artifact_scan import scan_artifacts
from incident_intent.artifact_scan_models import ArtifactScanRequest, ArtifactScanResponse
from incident_intent.confluence_client import confluence_config_summary
from incident_intent.confluence_models import ConfluenceSearchRequest, ConfluenceSearchResponse
from incident_intent.confluence_search import search_confluence_playbooks
from incident_intent.pipeline import run_incident_pipeline
from incident_intent.pipeline_models import PipelineRequest, PipelineResponse
from incident_intent.workflow_trace_analysis import analyze_workflow_trace
from incident_intent.dialog_models import DialogResponse, DialogState
from incident_intent.dialog_service import (
    continue_dialog,
    get_dialog,
    start_dialog,
    upload_artifacts,
)
from incident_intent.error_correlation import correlate_errors
from incident_intent.error_correlation_models import (
    CorrelateErrorsRequest,
    CorrelateErrorsResponse,
)
from incident_intent.extractor import build_intent_table
from incident_intent.incident_conclusion import build_incident_conclusion
from incident_intent.log_filter import filter_logs
from incident_intent.log_filter_models import FilterLogsRequest, FilterLogsResponse
from incident_intent.models import IntentTableRequest, IntentTableResponse
from incident_intent.llm_client import llm_config_summary
from incident_intent.ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_NUM_CTX
from incident_intent.path_resolve import is_docker_runtime, resolve_host_path
from incident_intent.poc_paths import caseone_dir, incidents_root, logs_dir, temp_dir
from incident_intent.slow_requests import find_slow_requests
from incident_intent.slow_requests_models import SlowRequestsRequest, SlowRequestsResponse
from incident_intent.symptom_search import search_symptoms
from incident_intent.symptom_search_models import SymptomSearchRequest, SymptomSearchResponse

STATIC_DIR = _APP_DIR / "static"

app = FastAPI(title="Incident Intent PoC", version="0.2.0")

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    td = temp_dir()
    ld = logs_dir()
    co = caseone_dir()
    inc_root = incidents_root()
    log_mount_dirs = sorted(
        [p.name for p in ld.iterdir() if p.is_dir()],
        key=str.lower,
    )[:10]
    incident_dirs = sorted(
        [p.name for p in inc_root.iterdir() if p.is_dir()],
        reverse=True,
    )[:10]

    llm = llm_config_summary()
    return {
        "llm": llm,
        "ollama_base_url": llm.get("base_url")
        or os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        "ollama_model": llm.get("model") or os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        "ollama_num_ctx": llm.get("num_ctx")
        or int(os.getenv("OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX))),
        "runtime": "docker" if is_docker_runtime() else "local",
        "paths": {
            "temp_dir": str(td),
            "temp_dir_exists": td.is_dir(),
            "logs_dir": str(ld),
            "logs_dir_exists": ld.is_dir(),
            "log_mount_dirs": log_mount_dirs,
            "caseone_dir": str(co),
            "caseone_exists": co.is_dir(),
            "incidents_root": str(inc_root),
            "recent_incidents": incident_dirs,
        },
        "confluence": confluence_config_summary(),
    }


async def _read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for uf in files:
        if not uf.filename:
            continue
        data = await uf.read()
        if data:
            out.append((uf.filename, data))
    return out


@app.post("/api/incident/dialog/start", response_model=DialogResponse)
async def dialog_start(
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> DialogResponse:
    try:
        uploads = await _read_uploads(files)
        return await start_dialog(message, uploads)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/incident/dialog/{incident_id}/message", response_model=DialogResponse)
async def dialog_message(
    incident_id: str,
    message: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> DialogResponse:
    try:
        uploads = await _read_uploads(files)
        return await continue_dialog(incident_id, message, uploads)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/incident/dialog/{incident_id}/artifacts", response_model=DialogResponse)
async def dialog_artifacts(
    incident_id: str,
    files: list[UploadFile] = File(...),
) -> DialogResponse:
    try:
        uploads = await _read_uploads(files)
        if not uploads:
            raise HTTPException(status_code=400, detail="Нет файлов для загрузки.")
        return await upload_artifacts(incident_id, uploads)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/incident/dialog/{incident_id}", response_model=DialogState)
async def dialog_get(incident_id: str) -> DialogState:
    try:
        return get_dialog(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _resolve_request_paths(body: IntentTableRequest) -> IntentTableRequest:
    logs = body.logs_path
    caseone = body.caseone_path
    if logs:
        resolved, _ = resolve_host_path(logs)
        logs = resolved
    if caseone:
        resolved, _ = resolve_host_path(caseone)
        caseone = resolved
    if logs == body.logs_path and caseone == body.caseone_path:
        return body
    return body.model_copy(update={"logs_path": logs, "caseone_path": caseone})


@app.post("/api/intent-table", response_model=IntentTableResponse)
async def intent_table(body: IntentTableRequest) -> IntentTableResponse:
    return await build_intent_table(_resolve_request_paths(body))


@app.post("/api/scan-artifacts", response_model=ArtifactScanResponse)
async def scan_artifacts_endpoint(body: ArtifactScanRequest) -> ArtifactScanResponse:
    return await asyncio.to_thread(scan_artifacts, body)


@app.post("/api/confluence-search", response_model=ConfluenceSearchResponse)
async def confluence_search_endpoint(body: ConfluenceSearchRequest) -> ConfluenceSearchResponse:
    return await asyncio.to_thread(search_confluence_playbooks, body)


@app.post("/api/filter-logs", response_model=FilterLogsResponse)
async def filter_logs_endpoint(body: FilterLogsRequest) -> FilterLogsResponse:
    return await asyncio.to_thread(filter_logs, body)


@app.post("/api/symptom-search", response_model=SymptomSearchResponse)
async def symptom_search_endpoint(body: SymptomSearchRequest) -> SymptomSearchResponse:
    return await asyncio.to_thread(search_symptoms, body)


@app.post("/api/slow-requests", response_model=SlowRequestsResponse)
async def slow_requests_endpoint(body: SlowRequestsRequest) -> SlowRequestsResponse:
    return await asyncio.to_thread(find_slow_requests, body)


@app.post("/api/correlate-errors", response_model=CorrelateErrorsResponse)
async def correlate_errors_endpoint(body: CorrelateErrorsRequest) -> CorrelateErrorsResponse:
    return await asyncio.to_thread(correlate_errors, body)


@app.post("/api/analyze-workflow-trace", response_model=WorkflowTraceAnalysisResponse)
async def analyze_workflow_trace_endpoint(
    body: WorkflowTraceAnalysisRequest,
) -> WorkflowTraceAnalysisResponse:
    return await asyncio.to_thread(analyze_workflow_trace, body)


@app.post("/api/analyze-client-logs", response_model=ClientLogAnalysisResponse)
async def analyze_client_logs_endpoint(
    body: ClientLogAnalysisRequest,
) -> ClientLogAnalysisResponse:
    return await asyncio.to_thread(analyze_client_logs, body)


@app.post("/api/index-caseone-config", response_model=CaseoneConfigIndexResponse)
async def index_caseone_config_endpoint(
    body: CaseoneConfigIndexRequest,
) -> CaseoneConfigIndexResponse:
    return await asyncio.to_thread(index_caseone_config, body)


@app.post("/api/incident/process", response_model=PipelineResponse)
async def incident_process_endpoint(body: PipelineRequest) -> PipelineResponse:
    resolved_logs = body.logs_path
    resolved_co = body.caseone_path
    if resolved_logs:
        resolved_logs, _ = resolve_host_path(resolved_logs)
    if resolved_co:
        resolved_co, _ = resolve_host_path(resolved_co)
    req = body.model_copy(
        update={"logs_path": resolved_logs or body.logs_path, "caseone_path": resolved_co}
    )
    return await run_incident_pipeline(req)


@app.post("/api/incident-conclusion", response_model=IncidentConclusionResponse)
async def incident_conclusion_endpoint(
    body: IncidentConclusionRequest,
) -> IncidentConclusionResponse:
    return await build_incident_conclusion(body)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8090")), reload=True)
