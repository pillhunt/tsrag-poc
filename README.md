# PoC: разбор инцидента CaseOne

Веб-интерфейс (`static/index.html`) и API для пошагового разбора инцидента: диалог с уточнениями, таблица намерений (Ollama), скан артефактов, поиск playbook в **Confluence**, срез логов, долгие запросы, ошибки, workflow/client, конфиг caseone, итог (playbook или LLM).

**План реализации (Confluence + якоря):** [incident_intent/plan/wiki_confluence_anchors_plan.md](incident_intent/plan/wiki_confluence_anchors_plan.md)

**Диаграммы последовательности:**

- **[docs/tsrag-poc-sequence-v2.drawio](docs/tsrag-poc-sequence-v2.drawio)** — актуально: полный пайплайн на одной странице + обзор архитектуры
- [docs/tsrag-poc-sequence.drawio](docs/tsrag-poc-sequence.drawio) — предыдущая версия (шаг 0, фрагменты)

## Пайплайн

| Шаг | ID | Содержание |
|-----|-----|------------|
| **0** | `intent` | Таблица намерений: дата/время, симптомы, `search_keywords`, **`anchors`**, `log_search_patterns` (Ollama). |
| **1** | `filter` | Проверка путей, список `*.log`, срез по времени → `time_window_lines` / `slow_time_window_lines`. |
| **2** | `artifact_scan` | **Скан артефактов на диске:** keywords и якоря в **узком** и **широком** окне; `discovered_anchors` из логов. |
| **3** | `confluence` | Поиск статьи-playbook в Confluence (CQL, `atlassian-python-api`). |
| **4** | `playbook_gate` | Решение: playbook или полный разбор (подтверждение якорями в логах). |
| **5** | `symptoms` | Поиск `search_keywords` в срезе (если не playbook). |
| **6** | `slow` | Долгие HTTP/access-запросы. |
| **7** | `errors` | Ошибки в срезе + корреляция с шагом 6. |
| **8** | `workflow_trace` | `WorkflowTrace.log`. |
| **9** | `client_logs` | Клиентские логи. |
| **10** | `caseone_config` | Индекс json/conf из `caseone_path`. |
| **11** | `conclusion` | **Playbook** (текст Confluence + цитаты логов) **или** заключение LLM. |

В UI кнопка **«Обработать инцидент»** → `POST /api/incident/process` (шаги 1–11, журнал внизу).

Порядок важен: **сначала скан логов (шаг 2), затем обогащение запроса (2b), затем Confluence (шаг 3)** — `anchors_for_search = intent.anchors ∪ discovered_anchors` из логов + symptoms + goal; не только текст жалобы.

HITL не реализован.

### Два временных окна (шаг 2)

| Окно | Границы | Назначение |
|------|---------|------------|
| **Узкое** | `time_window_start`–`end` из таблицы намерений | Жалоба пользователя |
| **Широкое** | ± `POC_SLOW_WINDOW_PADDING_H` (по умолчанию 1 ч) | Долгие операции и хвосты до/после окна |

### Алгоритм шага 0

1. **Ollama** извлекает дату, окно, симптомы, `search_keywords`, **`anchors`**, паттерны времени.
2. **Диалог** дополняет дату/время из реплик пользователя.
3. Статус: `complete` или `needs_clarification`.

## Быстрый старт (Docker)

1. `copy env\docker.env.example env\docker.env` — задайте `CASEONE_HOST_DIR`, при необходимости **Confluence** (`CONFLUENCE_*`).
2. `docker network create shared-network`
3. При необходимости — каталоги с логами в `./logs/` (любые имена)
4. `.\compose.ps1 up --build` → http://localhost:8090 (`TSRAG_PORT`)

## LLM (Ollama или Hugging Face)

Шаги **0** (таблица намерений) и **11** (заключение LLM) вызывают модель через `incident_intent/llm_client.py`.

| Переменная | Назначение |
|------------|------------|
| `LLM_PROVIDER` | `ollama` (по умолчанию) или `hf` |
| `OLLAMA_*` | Локальный Ollama (см. `env/docker.env.example`) |
| `HF_INFERENCE_URL` | **Полный URL** POST-запроса к модели на HF |
| `HF_TOKEN` | Read token с [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) |
| `HF_MODEL` | Имя модели для chat API (для URL `.../models/<id>` можно не задавать) |
| `HF_API_STYLE` | `auto` \| `chat` \| `generate` — формат запроса |
| `HF_TIMEOUT_SEC`, `HF_MAX_NEW_TOKENS` | Таймаут и лимит ответа |

**Примеры `HF_INFERENCE_URL`:**

- Serverless Inference API: `https://api-inference.huggingface.co/models/<org>/<model>`
- OpenAI-совместимый router: `https://router.huggingface.co/v1/chat/completions`
- Dedicated Endpoint (TGI): `https://<id>.endpoints.huggingface.cloud/v1/chat/completions`

Проверка: `GET /api/health` → блок `llm` (`provider`, `configured`, URL/модель).

## Confluence (Wiki)

Клиент: **[atlassian-python-api](https://atlassian-python-api.readthedocs.io/en/latest/confluence.html)** (`pip install atlassian-python-api`).

| Переменная | Назначение |
|------------|------------|
| `CONFLUENCE_URL` | Базовый URL; пусто → шаг 3 **skipped** |
| `CONFLUENCE_CLOUD` | `true` — Cloud (API token), `false` — Server/DC |
| `CONFLUENCE_USERNAME` | Логин / email |
| `CONFLUENCE_TOKEN` | API token (Cloud) или пароль (Server) |
| `CONFLUENCE_PAT` | Personal Access Token (Server/DC, вместо пароля) |
| `CONFLUENCE_SPACE_KEY` | Ограничить space |
| `CONFLUENCE_CQL_PREFIX` | Напр. `label = "incident-playbook"` |
| `CONFLUENCE_SCORE_MIN` | Порог score для playbook (по умолчанию 4) |
| `LOG_ANCHOR_MIN` | Мин. якорей из статьи, найденных в логах (по умолчанию 2) |

Проверка: `GET /api/health` → блок `confluence`.

Рекомендация для авторов статей: label `incident-playbook` и блок **«Якоря:»** со списком API/SQL-меток.

## API (отладка)

| Метод | Путь |
|-------|------|
| `POST` | `/api/scan-artifacts` — шаг 2 без полного пайплайна |
| `POST` | `/api/confluence-search` — шаг 3 |
| `POST` | `/api/filter-logs` — шаг 1 |
| `POST` | `/api/symptom-search` | `/api/slow-requests` | `/api/correlate-errors` |
| `POST` | `/api/incident/process` — шаги 1–11 |

### `POST /api/incident/process`

```json
{
  "intent_table": {},
  "logs_path": "/app/logs/host_2026-05-15",
  "caseone_path": "/caseone"
}
```

Ответ: `steps[]`, `artifact_scan`, `confluence_search`, `playbook_gate`, `use_playbook`, `conclusion` (`conclusion_source`: `confluence` | `llm`), `filter_summary`.

## Переменные окружения

Шаблон: `env/docker.env.example` (Ollama + Confluence + лимиты скана).

### Локально

```powershell
pip install -r requirements.txt
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
python -m uvicorn app:app --host 0.0.0.0 --port 8090
```

## Структура проекта

```
tsrag-poc/
  app.py
  incident_intent/
    artifact_scan.py      # шаг 2
    confluence_client.py  # env, atlassian API
    confluence_search.py  # шаг 3
    playbook_gate.py      # шаг 4
    render_playbook.py    # шаг 11 (playbook)
    pipeline.py
    plan/wiki_confluence_anchors_plan.md
  docs/tsrag-poc-sequence-v2.drawio
  docs/tsrag-poc-sequence.drawio
  env/docker.env.example
  static/index.html
```
