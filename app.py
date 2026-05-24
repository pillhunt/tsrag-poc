"""
PoC: таблица намерений (шаг 0 разбора инцидента) + веб-форма.

Запуск локально (Ollama на хосте):
  cd D:\\RAG\\poc
  pip install -r requirements.txt
  set OLLAMA_BASE_URL=http://127.0.0.1:11434
  python -m uvicorn app:app --host 0.0.0.0 --port 8090

Запуск в Docker (сеть shared-network, контейнер tsrag-ollama):
  docker compose up --build
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from incident_intent.extractor import build_intent_table
from incident_intent.log_filter import filter_logs
from incident_intent.log_filter_models import FilterLogsRequest, FilterLogsResponse
from incident_intent.conclusion_models import (
    IncidentConclusionRequest,
    IncidentConclusionResponse,
)
from incident_intent.error_correlation import correlate_errors
from incident_intent.error_correlation_models import (
    CorrelateErrorsRequest,
    CorrelateErrorsResponse,
)
from incident_intent.incident_conclusion import build_incident_conclusion
from incident_intent.slow_requests import find_slow_requests
from incident_intent.slow_requests_models import SlowRequestsRequest, SlowRequestsResponse
from incident_intent.symptom_search import search_symptoms
from incident_intent.symptom_search_models import SymptomSearchRequest, SymptomSearchResponse
from incident_intent.models import IntentTableRequest, IntentTableResponse
from incident_intent.ollama_client import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_NUM_CTX
from incident_intent.path_resolve import (
    is_docker_runtime,
    list_mount_entries,
    resolve_host_path,
)

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="Incident Intent PoC", version="0.1.0")

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> dict:
    rag_mount = os.getenv("POC_RAG_MOUNT", "/rag")
    caseone_mount = os.getenv("POC_CASEONE_MOUNT", "/caseone")
    rag_exists = Path(rag_mount).is_dir()
    caseone_exists = Path(caseone_mount).is_dir()
    ren_folders = list_mount_entries(rag_mount, prefix="REN") if rag_exists else []

    default_logs = None
    if ren_folders:
        default_logs = f"{rag_mount}/{ren_folders[0]}"

    return {
        "ollama_base_url": os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        "ollama_model": os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        "ollama_num_ctx": int(os.getenv("OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX))),
        "runtime": "docker" if is_docker_runtime() else "local",
        "paths": {
            "rag_mount": rag_mount,
            "rag_mount_exists": rag_exists,
            "rag_host_prefix": os.getenv("POC_RAG_HOST_PREFIX", "D:/RAG"),
            "caseone_mount": caseone_mount,
            "caseone_mount_exists": caseone_exists,
            "caseone_host_prefix": os.getenv(
                "POC_CASEONE_HOST_PREFIX",
                "D:/RAG/tsrag/temp/uploads/caseone",
            ),
            "ren_log_folders": ren_folders,
            "default_logs_path": default_logs,
            "default_caseone_path": caseone_mount if caseone_exists else None,
        },
    }


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
