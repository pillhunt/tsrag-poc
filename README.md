# PoC: разбор инцидента CaseOne

Веб-интерфейс (`static/index.html`) и API для пошагового разбора инцидента: диалог с уточнениями, таблица намерений (Ollama), срез логов, поиск симптомов, долгие запросы, ошибки, workflow/client, конфиг caseone, итоговое заключение LLM.

## Пайплайн

| Шаг | ID | Содержание |
|-----|-----|------------|
| **0** | `intent` | Таблица намерений: дата/время, симптомы, `search_keywords`, `log_search_patterns` (Ollama + парсинг диалога). Дата — **только из текста пользователя**, не из пути к логам. |
| **1** | `filter` | Проверка путей к логам и caseone, рекурсивный список `*.log`, срез по времени → `time_window_lines`. |
| **2** | `symptoms` | Поиск `search_keywords` **только в срезе** (шаг 1). |
| **3** | `slow` | Долгие HTTP/access-запросы в строках среза. |
| **4** | `errors` | Ошибки во всех файлах среза + корреляция с шагом 3. |
| **5** | `workflow_trace` | Анализ `WorkflowTrace.log` (если есть в срезе). |
| **6** | `client_logs` | События клиентских логов в срезе. |
| **7** | `caseone_config` | Индекс json/conf из `caseone_path` (если задан). |
| **8** | `conclusion` | Итоговое заключение LLM по досье. |

В UI одна кнопка **«Обработать инцидент»** вызывает `POST /api/incident/process` (шаги 1–8 подряд, журнал внизу страницы). Отдельные endpoint'ы ниже сохранены для отладки.

HITL (Human-in-the-loop) не реализован.

### Алгоритм шага 0

1. **Ollama** извлекает из описания дату, окно времени, симптомы, ключевые слова, паттерны времени, недостающие поля и уточняющие вопросы.
2. **Диалог:** при необходимости дата и время дополняются из реплик пользователя (без LLM).
3. **Статус:** `complete` или `needs_clarification`.

## Быстрый старт (Docker)

Ollama и PoC поднимаются **одним** `docker-compose.yml`. Модель скачивается сервисом `ollama-init` (том `ollama_data`).

1. Скопируйте переменные: `copy env\docker.env.example env\docker.env` и при необходимости отредактируйте `CASEONE_HOST_DIR`.
2. Создайте сеть (один раз): `docker network create shared-network`
3. Положите папки логов `REN-*` в каталог **`logs/`** в корне репозитория.
4. Из корня проекта:

```powershell
cd D:\Work\AI\tsrag-poc
.\compose.ps1 up --build
```

Linux/macOS: `./compose.sh up --build`

Альтернатива: `docker compose --env-file env/docker.env up --build`

Откройте http://localhost:8090 (порт на хосте — **`TSRAG_PORT`** в `env/docker.env`, по умолчанию `8090`).

**Конфликт имён:** если контейнер `ollama` уже запущен другим проектом, остановите его (`docker rm -f ollama`) или переименуйте `container_name` в compose.

## Запуск локально (Ollama на хосте)

```powershell
cd D:\Work\AI\tsrag-poc
pip install -r requirements.txt
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3.1:8b-instruct-q4_K_M"
python -m uvicorn app:app --host 0.0.0.0 --port 8090
```

Логи для ручного пути: `logs/REN-…` или загрузка zip в диалог → `temp/incidents/<id>/`. Caseone локально: `temp/caseone` (создаётся автоматически).

## Пути и тома (Docker)

| Хост (корень проекта) | В контейнере | Назначение |
|------------------------|--------------|------------|
| `./temp` | `/app/temp` | Загрузки инцидентов, `temp/incidents/<id>`, локальный `temp/caseone` |
| `./logs` | `/app/logs` | Папки `REN-*` для ручного `logs_path` |
| `CASEONE_HOST_DIR` из `env/docker.env` | `/caseone` | Код/конфиги caseone (только чтение) |

**Логи в форме (Docker):** `/app/logs/REN-MSKCASPRO01_2026-04-23` или оставьте путь из диалога (`temp/incidents/<id>` после загрузки архива).

**Caseone в форме (Docker):** только `/caseone` или `/caseone/…` (не Windows-пути).

**Локально:** `logs/…`, `temp/incidents/<id>`, `temp/caseone`.

Проверка после старта: `GET /api/health` — `logs_dir`, список `ren_log_dirs`, `caseone_exists`, настройки Ollama.

Приоритетные файлы в отчётах помечены ★: `RequestLoggingMiddleware.log`, `global.log`, `WorkflowTrace.log`.

## Диалог (основной сценарий UI)

| Метод | Путь |
|-------|------|
| `POST` | `/api/incident/dialog/start` — новый инцидент, опционально файлы |
| `POST` | `/api/incident/dialog/{id}/message` — сообщение / уточнение |
| `POST` | `/api/incident/dialog/{id}/artifacts` — дозагрузка zip/логов |
| `GET` | `/api/incident/dialog/{id}` — состояние диалога |

После шага 0: `POST /api/incident/process` с `intent_table`, `logs_path`, `caseone_path`.

## API (отладка и интеграции)

### `POST /api/intent-table`

```json
{
  "incident_description": "15.05 с 14:00 до 15:30 отчёт долго формировался, в конце таймаут",
  "logs_path": "/app/logs/REN-MSKCASPRO01_2026-05-15",
  "caseone_path": "/caseone"
}
```

### `POST /api/filter-logs` (шаг 1)

Рекурсивный список `*.log` + срез по `log_search_patterns`.

```json
{
  "logs_path": "/app/logs/REN-MSKCASPRO01_2026-05-15",
  "log_search_patterns": ["2026-05-15 14:", "2026-05-15 15:"],
  "caseone_path": "/caseone",
  "recursive": true,
  "max_depth": null
}
```

- `recursive: true` (по умолчанию) — все подкаталоги.
- `max_depth: 0` — только корень `logs_path`; `null` — без ограничения.
- Можно передать путь к одному файлу `.log`.
- Пропускаются служебные каталоги: `.git`, `node_modules`, `bin`, `obj` и т.п.

### `POST /api/symptom-search` (шаг 2) и `POST /api/slow-requests` (шаг 3)

Обязательно передать **`time_window_lines`** из ответа `filter-logs`.

```json
{
  "logs_path": "/app/logs/REN-MSKCASPRO01_2026-05-15",
  "log_search_patterns": ["2026-05-15 14:"],
  "time_window_lines": [
    { "file": "case1.renins.com/global.log", "line_number": 42, "text": "…" }
  ],
  "search_keywords": ["отчёт", "Timeout", "/api/reports"]
}
```

Шаг 3 (slow): дополнительно `min_duration_ms`, `top_n`, `http_access_only`.

### `POST /api/correlate-errors` (шаг 4)

```json
{
  "logs_path": "/app/logs/REN-MSKCASPRO01_2026-05-15",
  "log_search_patterns": ["2026-05-15 14:"],
  "time_window_lines": [],
  "slow_requests": [],
  "correlation_window_sec": 90,
  "global_log_only": false
}
```

Категории ошибок: `incident_intent/error_rules.yaml`.

### `POST /api/incident/process` (шаги 1–8)

```json
{
  "intent_table": {},
  "logs_path": "/app/logs/REN-MSKCASPRO01_2026-05-15",
  "caseone_path": "/caseone",
  "incident_id": "optional-uuid",
  "max_evidence_samples": 20
}
```

Ответ: `steps[]`, `filter_summary`, результаты шагов, `conclusion` (`conclusion_markdown`, `confidence`, …). Тяжёлый срез строк в JSON не дублируется — только `filter_summary`.

Также: `/api/analyze-workflow-trace`, `/api/analyze-client-logs`, `/api/index-caseone-config`, `/api/incident-conclusion`.

## Переменные окружения

### Docker (`env/docker.env`)

| Переменная | Назначение |
|------------|------------|
| `TSRAG_PORT` | Порт PoC на хосте (в контейнере всегда `8090`) |
| `CASEONE_HOST_DIR` | Папка caseone на хосте → mount в `/caseone` |
| `OLLAMA_BASE_URL` | URL Ollama для PoC (`http://ollama:11434` в compose) |
| `OLLAMA_PORT` | Проброс Ollama на хост |
| `OLLAMA_LISTEN` | Bind внутри контейнера ollama |
| `OLLAMA_MODEL` | Модель для `ollama-init pull` и запросов PoC |
| `OLLAMA_TIMEOUT_SEC` | Таймаут HTTP к Ollama |
| `OLLAMA_NUM_CTX` | Размер контекста (`num_ctx`) |
| `CUDA_VISIBLE_DEVICES`, `NVIDIA_VISIBLE_DEVICES` | GPU для сервиса ollama (опционально) |

Логи: каталог `logs/` в проекте, mount задаётся в `docker-compose.yml` (`./logs` → `/app/logs`). Отдельная переменная не нужна.

Шаблон: `env/docker.env.example`.

### Локально (без compose)

| Переменная | По умолчанию |
|------------|----------------|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` |
| `OLLAMA_MODEL` | `llama3.1:8b-instruct-q4_K_M` (~6 GiB RAM; `q6_K` — ≥10 GiB) |
| `OLLAMA_TIMEOUT_SEC` | `1200` |
| `OLLAMA_NUM_CTX` | `8192` (при большом RAM можно `32768`) |
| `PORT` | `8090` (uvicorn) |
| `POC_TEMP_DIR` | `<корень проекта>/temp` |
| `POC_LOGS_MOUNT` | в Docker задаётся compose: `/app/logs` |

Опционально: `POC_PATH_MAP` — доп. правила `host=mount;…` для `resolve_host_path`; `POC_CASEONE_MAX_FILE_BYTES`, `POC_CASEONE_MAX_CONFIG_FILES` — лимиты индекса caseone.

## Структура проекта

```
tsrag-poc/
  app.py                 # FastAPI
  compose.ps1 / compose.sh
  docker-compose.yml
  env/docker.env.example
  incident_intent/       # шаги пайплайна, LLM, парсеры
  logs/                  # REN-* для Docker mount
  static/index.html      # UI
  temp/                  # инциденты и загрузки
```
