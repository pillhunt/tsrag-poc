"""
PoC: разбор инцидента — диалог + шаги 0–6.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from incident_intent.conclusion_models import (
    IncidentConclusionRequest,
    IncidentConclusionResponse,
)
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
from incident_intent.ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_NUM_CTX
from incident_intent.path_resolve import is_docker_runtime, resolve_host_path
from incident_intent.poc_paths import caseone_dir, incidents_root, temp_dir
from incident_intent.slow_requests import find_slow_requests
from incident_intent.slow_requests_models import SlowRequestsRequest, SlowRequestsResponse
from incident_intent.symptom_search import search_symptoms
from incident_intent.symptom_search_models import SymptomSearchRequest, SymptomSearchResponse

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Incident Intent PoC", version="0.2.0")

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    td = temp_dir()
    co = caseone_dir()
    inc_root = incidents_root()
    incident_dirs = sorted(
        [p.name for p in inc_root.iterdir() if p.is_dir()],
        reverse=True,
    )[:10]

    return {
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        "ollama_model": os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        "ollama_num_ctx": int(os.getenv("OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX))),
        "runtime": "docker" if is_docker_runtime() else "local",
        "paths": {
            "temp_dir": str(td),
            "temp_dir_exists": td.is_dir(),
            "caseone_dir": str(co),
            "caseone_exists": co.is_dir(),
            "incidents_root": str(inc_root),
            "recent_incidents": incident_dirs,
        },
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


@app.post("/api/incident-conclusion", response_model=IncidentConclusionResponse)
async def incident_conclusion_endpoint(
    body: IncidentConclusionRequest,
) -> IncidentConclusionResponse:
    return await build_incident_conclusion(body)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8090")), reload=True)
