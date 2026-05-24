# План работ: пункт B (привязка к CaseOne / форматам логов)

**Контекст:** пункт A закрыт (пути, Docker, `temp/incidents`).  
**Ограничение:** промпты шагов 0 и 6 **не меняем** — в них остаётся домен CaseOne/CaseMap. Универсальность достигаем **кодом** шагов 1–5 и discovery.

**Цель B:** PoC должен находить долгие запросы и ошибки не только в `RequestLoggingMiddleware.log` + `global.log`, а во **всех релевантных файлах среза** — включая nginx, IIS, MSSQL, PostgreSQL, плюс подготовить задел под json/conf из caseone.

---

## Что мешает сейчас (кратко)

| # | Проблема | Где в коде |
|---|----------|------------|
| B.1 | Discovery знает только `*.log` / `*.txt` и приоритетные имена CaseOne | `log_discovery.py` |
| B.2 | Шаг 4 по умолчанию режет срез по **имени файла** `RequestLoggingMiddleware` | `slow_requests.py`, `slow_request_parser.py`, UI `middleware_only: true` |
| B.2 | Парсер одного формата: `GET; /api/...; …; ms;` | `slow_request_parser.py` |
| B.3 | Шаг 5 по умолчанию `global_log_only=True` | `error_correlation_models.py`, UI |
| B.3 | Баг в тексте выводов: всегда «только global.log» | `error_correlation.py` (`if True`) |
| B.4 | 6 категорий + маркеры под .NET/SQL Server | `error_classifier.py` |
| B.5 | Промпты CaseOne — **оставляем** | `prompts/*.md` |
| B.6 | `caseone_path` не читается шагами 1–6 | весь pipeline |

---

## Принцип решения

Ввести **реестр источников** (source registry): для каждого типа лога — как распознать файл, как вытащить время, как искать долгие запросы, какие правила ошибок применять.

```
Срез (шаги 1–2) — все строки всех файлов в окне
        │
        ├─► Шаг 4: для каждой строки → chain парсеров HTTP/access (без фильтра по имени)
        │
        └─► Шаг 5: для каждой строки всех файлов → detect error → classify (engine + category)
```

Промпты не трогаем: LLM по-прежнему формулирует жалобу в терминах CaseOne; код **не предполагает**, что ответ лежит только в двух файлах.

---

## Фаза 1 — быстрые победы (1–2 дня)

### 1.1 Ошибки во всех файлах среза

- [ ] `global_log_only` по умолчанию → **`false`** (`error_correlation_models.py`, `static/index.html`).
- [ ] Убрать или deprecate `include_other_error_logs` (становится лишним при `global_log_only=false`).
- [ ] Исправить `_build_conclusions`: текст зависит от `req.global_log_only`.
- [ ] Обновить формулировки в `slow_requests.py` («следующий шаг — ошибки **во всех логах среза**»).
- [ ] README: шаг 5 = все файлы среза.

**Приёмка:** ошибка из `nginx/error.log` или `ERRORLOG` в срезе попадает в шаг 5 без смены флагов в UI.

### 1.2 Расширить discovery (имена и суффиксы)

Файл: `log_discovery.py`.

Добавить распознавание (не обязательно отдельный парсер — только **попадание в срез**):

| Тип | Типичные имена / паттерны |
|-----|---------------------------|
| nginx | `access.log`, `error.log`, `*.access.log` |
| IIS | `u_ex*.log`, `httperr*.log`, W3C extended |
| MSSQL | `ERRORLOG`, `ERRORLOG.*`, `SQLAGENT*.OUT` |
| PostgreSQL | `postgresql-*.log`, `pg_log/*` |
| CaseOne | как сейчас + без жёсткой привязки шагов 4–5 к имени |

- [ ] Расширить `_LOG_SUFFIXES` / rolling: `.out`, при необходимости `.jsonl`.
- [ ] `_PRIORITY_LOG_NAMES` → **подсказки сортировки**, не whitelist для шагов 4–5.
- [ ] Опционально: тег `log_kind` в метаданных файла (`app`, `web`, `db`, `unknown`) — эвристика по имени пути.

**Приёмка:** zip с nginx + IIS + SQL логами попадает в шаги 1–2, файлы видны в UI.

---

## Фаза 2 — долгие запросы без привязки к имени (2–3 дня)

### 2.1 Убрать фильтр по имени файла

- [ ] `middleware_only` по умолчанию → **`false`**; в UI переименовать в «только HTTP/access-логи» или убрать галку.
- [ ] Переименовать в API (с алиасом для совместимости): `middleware_only` → `http_access_only` (если true — пропускать строки, где **ни один** access-парсер не сматчился, а не где имя файла не middleware).
- [ ] `is_middleware_log()` — удалить из hot path или оставить только как **hint** для сортировки/приоритета, не filter.

### 2.2 Chain парсеров (новый модуль)

Файл: `incident_intent/http_access_parsers.py` (или каталог `parsers/`).

Каждый парсер: `(line, file) → ParsedSlowRequest | None` + поле `format: str`.

| Парсер | Формат строки | Длительность |
|--------|---------------|--------------|
| `caseone_middleware` | текущий regex `; GET; /api/...; ...; ms;` | ms в конце |
| `nginx_combined` | `$remote - - [$time] "METHOD path HTTP/..." status bytes rt=1.234` | `request_time` / upstream |
| `nginx_json` | JSON access log | поля `request_time`, `upstream_response_time` |
| `iis_w3c` | `#Fields: ... time-taken ...` + строки с табами | `time-taken` (ms) |
| `generic_http_ms` | fallback: METHOD + path + число ms/s в строке | эвристика |

Порядок: специфичные → generic. Первый успешный match wins.

- [ ] В `SlowRequestRow` добавить `log_format: str | None` (для отчёта и шага 6).
- [ ] Статистика: `parsed_by_format: dict[str, int]` в ответе шага 4.
- [ ] Путь `/api/` **не** обязателен в generic-парсере (nginx/IIS часто без `/api`).

**Приёмка:** долгий запрос виден из nginx access.log в том же срезе, без `RequestLoggingMiddleware` в пути.

### 2.3 Зависимость от времени (связь с пунктом F)

Корреляция шаг 5 ↔ шаг 4 использует `parse_log_timestamp` (сейчас только `YYYY-MM-DD HH:MM:SS`).

- [ ] Вынести `timestamp_parsers.py`: registry по `log_kind` / формату.
- [ ] Минимум для фазы 2: nginx `[dd/Mon/yyyy:HH:mm:ss +zzzz]`, IIS W3C date+time, ERRORLOG-style.

Без этого nginx/IIS ошибки и slow requests попадут в отчёт, но **корреляция ±90 с** будет слабой (`unparsed_timestamp_count`).

---

## Фаза 3 — расширение типов ошибок (2–4 дня)

### 3.1 Как расширять (рекомендуемая схема)

**Не раздувать один flat enum в Python.** Два уровня:

1. **`error_engine`** — откуда строка (эвристика по файлу + содержимому):  
   `dotnet_app` | `mssql` | `postgres` | `nginx` | `iis` | `unknown`

2. **`error_category`** — что случилось (общие + engine-specific).

Файл правил: `incident_intent/error_rules.yaml` (или `.json`) — **без LLM**, только grep-маркеры.

```yaml
engines:
  mssql:
    file_hints: ["errorlog", "sqlagent"]
    categories:
      sql_deadlock:
        markers: ["deadlock victim", "1205"]
      sql_pk_duplicate:
        markers: ["PRIMARY KEY", "2627", "duplicate key"]
      sql_timeout:
        markers: ["timeout expired", "-2"]
      sql_connection:
        markers: ["connection forcibly closed", "18456", "login failed"]

  postgres:
    file_hints: ["postgresql", "pg_log"]
    categories:
      pg_deadlock:
        markers: ["deadlock detected", "40P01"]
      pg_unique_violation:
        markers: ["duplicate key value", "23505"]
      pg_statement_timeout:
        markers: ["statement timeout", "57014"]
      pg_connection:
        markers: ["could not connect", "connection refused", "08006"]

  nginx:
    file_hints: ["nginx", "access.log", "error.log"]
    categories:
      nginx_upstream_timeout:
        markers: ["upstream timed out", "504"]
      nginx_connect_refused:
        markers: ["connect() failed", "111"]
      nginx_ssl:
        markers: ["SSL_do_handshake", "certificate"]

  iis:
    file_hints: ["u_ex", "httperr", "w3svc"]
    categories:
      iis_500:
        markers: ["sc-status 500", "HTTP/1.1 500"]
      iis_timeout:
        markers: ["time-taken", "ASP.NET", "Request timed out"]
      iis_502_503:
        markers: ["502", "503", "Bad Gateway"]

  dotnet_app:
    file_hints: ["global.log", "nlog", "serilog"]
    categories:
      concurrency: [...]
      connection: [...]
      generic_error:
        markers: ["Exception", "ERROR", "SqlException", "DbUpdateException"]

generic:
  markers: ["ERROR", "Error", "FAIL", "Fatal", "ошибк"]
  category: generic_error
```

**Порядок классификации:**

1. Определить `error_engine` по пути файла (`infer_engine(path)`).
2. Применить категории этого engine + **generic**.
3. Первая совпавшая категория (приоритет: specific > generic).
4. Если маркер error есть, но категория не совпала → `generic_error`, не `other`.

### 3.2 Обратная совместимость API

- Сохранить старые категории (`sql_deadlock`, …) — они остаются алиасами для `mssql`/`dotnet_app`.
- Добавить поля в `ErrorInWindow`:
  - `error_engine: str`
  - опционально `http_status: int | None` (nginx/IIS)
- `ErrorCategory` Literal расширить или заменить на `str` + валидация по rules file.

### 3.3 Как добавлять новые типы без правки логики

1. Добавить блок в `error_rules.yaml`.
2. При необходимости — `file_hints` для нового engine.
3. Прогнать golden + один fixture на engine.
4. **Промпт шага 6 не менять** — категории приходят в JSON досье; LLM интерпретирует `pg_deadlock` так же, как `sql_deadlock`.

### 3.4 Тесты

- [ ] `tests/fixtures/errors/` — по 3–5 строк на engine (mssql, postgres, nginx, iis, global.log).
- [ ] Unit: `classify_error_line(text, file=...)` → engine + category.
- [ ] Regression: старые категории CaseOne не ломаются.

---

## Фаза 4 — caseone json/conf (опционально, после B.2–B.3)

**Не парсить код.** Только метаданные для шага 6 и подсказок инженеру.

### 4.1 Discovery конфигов

Под `caseone_path` (если задан):

- `*.json`, `*.config`, `appsettings*.json`, `web.config`, `*.yaml`
- Исключить: `bin/`, `node_modules/`, секреты (connection string values **маскировать**)

### 4.2 Шаг 0.5 или блок в evidence bundle

- [ ] `config_index.py`: список файлов + извлечённые **ключи** (timeouts, pool size, `RequestLogging`, Kestrel/IIS limits) — значения без паролей.
- [ ] В `evidence_bundle.py` секция `caseone_config_snippets` (top-N релевантных по keywords из шага 0).
- [ ] Шаги 1–5 **не** зависят от caseone; шаг 6 получает доп. контекст.

**Приёмка:** в досье шага 6 есть «в appsettings найден CommandTimeout=…» без чтения исходников C#.

---

## Карта изменений по файлам

| Файл | Фаза | Действие |
|------|------|----------|
| `log_discovery.py` | 1 | суффиксы, hints, `log_kind` |
| `error_correlation.py` | 1 | default all logs, fix conclusions |
| `error_correlation_models.py` | 1 | defaults |
| `static/index.html` | 1–2 | flags, labels |
| `slow_requests.py` | 2 | убрать filter by filename |
| `slow_request_parser.py` | 2 | → один из chain или rename |
| `http_access_parsers.py` | 2 | **новый** |
| `timestamp_parsers.py` | 2 | **новый** |
| `error_classifier.py` | 3 | load rules, engine inference |
| `error_rules.yaml` | 3 | **новый** |
| `error_correlation_models.py` | 3 | `error_engine`, extended categories |
| `evidence_bundle.py` | 3–4 | engine/category в досье |
| `config_index.py` | 4 | **новый** |
| `prompts/*.md` | — | **не трогаем** |

---

## Порядок внедрения (рекомендуемый)

```
Фаза 1.1  ошибки во всех логах + fix UI text     ← сразу снимает главную боль B.3
Фаза 1.2  discovery nginx/IIS/SQL/postgres
Фаза 2    multi-parser slow requests, no filename filter
Фаза 3    error_rules.yaml + engines
Фаза 2.3  timestamp parsers (можно параллельно с 3)
Фаза 4    caseone config index (по запросу)
```

---

## Риски

| Риск | Митигация |
|------|-----------|
| Шум: в access.log много «200 OK» | Шаг 4 только duration ≥ порога; шаг 5 — только error markers |
| Разные TZ в nginx/IIS | Пункт F: позже явный TZ; пока — рост `unparsed_timestamp_count` в отчёте |
| Взрыв категорий | Engine + category; в UI группировка по engine |
| Старый клиент API | Deprecate flags, не удалять сразу; defaults меняем |

---

## Чеклист «пункт B закрыт»

- [ ] Шаг 4 находит долгие запросы в nginx/IIS/CaseOne middleware **по содержимому строк**, не по имени файла.
- [ ] Шаг 5 ищет ошибки **во всех файлах среза** по умолчанию.
- [ ] Классификатор покрывает mssql, postgres, nginx, iis + старые dotnet-категории через rules file.
- [ ] Discovery подхватывает типичные имена nginx/IIS/SQL/postgres.
- [ ] Промпты 0 и 6 без изменений.
- [ ] (Опционально) caseone json/conf — индекс в досье шага 6.

---

## Связь с другими пунктами uni_poc

- **F (время):** для полной корреляции nginx/IIS нужны парсеры меток времени — часть фазы 2.3.
- **E (WorkflowTrace):** отдельный парсер, не блокирует B; можно добавить как ещё один `log_kind=app_trace`.
- **D (жёсткие числа):** порог slow и ±90 с — отдельная задача; на план B не влияет.
