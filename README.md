# PoC: разбор инцидента (шаги 0–6)

Веб-форма принимает описание инцидента и пути к логам/caseone:

- **Шаг 0:** Ollama → таблица намерений: `log_search_patterns` (время) и **`search_keywords`** (содержимое, RU+EN, из описания инцидента).
- **Шаги 1–2:** срез логов по времени → `time_window_lines` (все строки окна, с лимитом).
- **Шаг 3–4:** поиск **только в `time_window_lines`** из шагов 1–2 (повторного чтения логов с диска нет).
- **Шаг 3:** `search_keywords` по срезу.
- **Шаг 4:** долгие HTTP/access-запросы (CaseOne middleware, nginx, IIS и др.) в строках среза.
- **Шаг 5:** ошибки во **всех файлах среза** + привязка по времени к долгим запросам (шаг 4).
- **Шаг 6:** Ollama → итоговое заключение по фактам шагов 0–5 (`conclusion_markdown`, **confidence** по логам, `supported_by`, `not_proven`, `recommended_actions`). HITL не реализован.

## Что делает скрипт (алгоритм шага 0)

1. **Без модели:** из `logs_path` извлекает дату `YYYY-MM-DD` из имени папки (regex).
2. **С моделью (Ollama):** из текста описания извлекает дату, окно времени, симптомы, **`search_keywords`**, цель разбора, паттерны времени, недостающие поля и уточняющие вопросы.
3. **Слияние:** если дата из папки и из текста расходятся — помечает конфликт и просит уточнение.
4. **Статус:** `complete` или `needs_clarification` (если нет даты/окна/симптомов или есть вопросы).

## Запуск в Docker (сеть `shared-network`, контейнер `tsrag-ollama`)

```powershell
cd D:\RAG\poc
docker compose up --build
```

Открыть: http://localhost:8090

Требуется уже запущенный `tsrag-ollama` в сети `shared-network` (из `D:\RAG\tsrag\docker-compose.yaml`).

## Запуск локально (Ollama на хосте)

```powershell
cd D:\RAG\poc
pip install -r requirements.txt
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3.1:8b-instruct-q6_K"
python -m uvicorn app:app --host 0.0.0.0 --port 8090
```

## API

### `POST /api/intent-table`

```json
{
  "incident_description": "15.05 с 14:00 до 15:30 отчёт долго формировался, в конце таймаут",
  "logs_path": "D:\\RAG\\poc\\temp\\incidents\\example-id\\logs",
  "caseone_path": "D:\\RAG\\poc\\temp\\caseone"
}
```

### `POST /api/filter-logs`

Шаги 1–2: рекурсивный список `*.log` + подсчёт строк по `log_search_patterns`.

```json
{
  "logs_path": "D:\\RAG\\poc\\temp\\incidents\\example-id\\logs",
  "log_search_patterns": ["2026-05-15 14:", "2026-05-15 15:"],
  "caseone_path": "D:\\RAG\\poc\\temp\\caseone",
  "recursive": true,
  "max_depth": null
}
```

- `recursive: true` (по умолчанию) — все подкаталоги, например `case1.renins.com\\global.log`.
- `max_depth: 0` — только файлы в корне `logs_path`; `null` — без ограничения.
- Можно передать путь к одному файлу `.log`.

Пропускаются служебные каталоги: `.git`, `node_modules`, `bin`, `obj` и т.п.

### `POST /api/symptom-search` и `POST /api/slow-requests`

Обязательно передать **`time_window_lines`** из ответа `filter-logs` (шаги 1–2).

```json
{
  "logs_path": "D:\\RAG\\poc\\temp\\incidents\\example-id\\logs",
  "log_search_patterns": ["2026-05-15 14:"],
  "time_window_lines": [
    { "file": "host.example.com/global.log", "line_number": 42, "text": "…" }
  ],
  "search_keywords": ["отчёт", "Timeout", "/api/reports"]
}
```

Шаг 4 дополнительно: `min_duration_ms`, `top_n`, `http_access_only` (только строки, распознанные как HTTP/access).

### `POST /api/correlate-errors`

Шаг 5: ошибки во **всех файлах** среза + корреляция с `slow_requests` (±`correlation_window_sec`, по умолчанию 90 с).

```json
{
  "logs_path": "D:\\RAG\\poc\\temp\\incidents\\example-id\\logs",
  "log_search_patterns": ["2026-05-15 14:"],
  "time_window_lines": [],
  "slow_requests": [],
  "correlation_window_sec": 90,
  "global_log_only": false
}
```

Категории задаются в `incident_intent/error_rules.yaml` (MSSQL, PostgreSQL, nginx, IIS, .NET app + `generic_error`).

### `POST /api/incident-conclusion`

Шаг 6: LLM формирует заключение по JSON-досье из результатов предыдущих шагов (без повторного чтения логов).

```json
{
  "intent_table": { },
  "filter_summary": {
    "total_matching_lines": 1200,
    "time_window_line_count": 800,
    "time_window_truncated": false,
    "files_in_window": ["case1.renins.com/global.log"],
    "patterns_used": ["2026-05-15 14:"]
  },
  "symptom_search": null,
  "slow_requests": null,
  "error_correlation": null,
  "max_evidence_samples": 20
}
```

Ответ: `conclusion_markdown`, `confidence` (`high`|`medium`|`low`), `confidence_reason`, `supported_by`, `not_proven`, `recommended_actions`, `raw_llm`.

Обязательно: шаги 1–2 (`filter_summary.time_window_line_count` > 0). Шаги 3–5 опциональны — в досье попадают только если были выполнены (`status: "ok"`).

### Docker: монтирование путей

В `docker-compose.yml` смонтированы:

| Хост (Windows) | Контейнер |
|----------------|-----------|
| `D:/RAG` (`POC_LOGS_HOST_DIR`) | `/rag` |
| `D:/RAG/tsrag/temp/uploads/caseone` (`POC_CASEONE_HOST_DIR`) | `/caseone` |

В форме можно вводить **и Windows-пути** (`D:\RAG\REN-MSKCASPRO01_2026-04-23`), и пути контейнера (`/rag/REN-MSKCASPRO01_2026-04-23`) — приложение преобразует их автоматически.

После `docker compose up --build` откройте http://localhost:8090 — внизу формы в `/api/health` видно, какие тома смонтированы и какие папки `REN-*` доступны.

Если папка называется `REN-MSKCASPRO01_2026-04-23`, а не `REN-MSKCASPRO01` — укажите полное имя (подсказка появится в замечаниях).

Приоритетные файлы в отчёте помечены ★: `RequestLoggingMiddleware.log`, `global.log`, `WorkflowTrace.log`.

## Переменные окружения

| Переменная | По умолчанию |
|------------|----------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` (в Docker: `http://tsrag-ollama:11434`) |
| `OLLAMA_MODEL` | `llama3.1:8b-instruct-q6_K` |
| `OLLAMA_TIMEOUT_SEC` | `1200` |
| `OLLAMA_NUM_CTX` | `32768` — контекст Ollama (`num_ctx`) для шагов 0 и 6 |
| `PORT` | `8090` |
| `POC_LOGS_HOST_DIR` (docker-compose) | `D:/RAG` — каталог логов на хосте, монтируется в `/rag` |
