# План работ: пункт E (алгоритм без PoC)

**Контекст:** A, B, F закрыты или частично закрыты для основного pipeline (upload → шаги 0–6).  
**Проблема E:** в «идеальном» разборе есть **workflow**, **клиент**, **конфиг/API**, **правка человеком** — в PoC этого нет, поэтому шаг 6 не может честно отделить «сервер» от «браузера» и не опирается на caseone.

**Цель E:** добавить **кодовые шаги-анализаторы** (не LLM по сырым логам), которые дают факты в досье шага 6 и снижают галлюцинации.

**Ограничение:** промпты 0 и 6 — **минимальные правки** (только «если в досье есть step_workflow — учти»); основная логика в Python.

---

## Что мешает сейчас

| # | Пробел | Сейчас |
|---|--------|--------|
| E.1 | WorkflowTrace | Файл в срезе и в keywords, но нет структуры «начало/конец операции, длительность этапа» |
| E.2 | Client / console | `ClientLogs.log` в discovery, без отдельного разбора обрывов/клиента |
| E.3 | caseone / API / код | `caseone_path` только в контексте LLM шага 0; файлы не читаются |
| E.4 | HITL | Заключение только на просмотр; нельзя сохранить правку инженера |

**Эталон (golden):** [golden_set/button_incident.md](../../golden_set/button_incident.md) — WorkflowTrace отличает быстрые save (~2 с) от долгих `PutProjectType`; client — `ConnectionReset`; вывод «не браузер» опирается на эти факты + SQL/middleware.

---

## Принцип: шаги E1–E3 перед шагом 6

Нумерация в UI/API — **опциональные подшаги** (можно не показывать отдельными кнопками — автозапуск перед шагом 6):

```
Срез (1–2) ──► шаги 3–5 (как сейчас)
        │
        ├─► E1 workflow_trace  ──► JSON: этапы, пары начало/конец, длительности
        ├─► E2 client_logs      ──► JSON: обрывы, таймауты клиента
        └─► E3 caseone_index    ──► JSON: релевантные ключи конфига (без секретов)
        │
        └─► шаг 6 LLM (досье 0–5 + E1–E3)
        │
        └─► E4 HITL (опционально): правка текста заключения
```

Все E1–E3 работают **только по `time_window_lines`** (или подмножеству по имени файла), без повторного полного чтения диска.

---

## E.1 — WorkflowTrace (приоритет 1)

### Задача

Из строк `*WorkflowTrace*.log` в срезе извлечь **клиентские этапы** сохранения/операций и их длительность.

### Формат (типичный CaseOne)

- Строки с `"начало сохранения"`, `"конец"`, имена операций/workflow.
- Иногда JSON или структурированный текст с меткой времени (ISO).

### Модуль

`incident_intent/workflow_trace_analysis.py`

```python
@dataclass
class WorkflowStepEvent:
    timestamp: str | None
    kind: str          # begin | end | message
    label: str         # текст операции
    source_file: str
    line_number: int

@dataclass
class WorkflowTraceSummary:
    events: list[WorkflowStepEvent]
    paired_operations: list[dict]  # label, begin, end, duration_sec
    anomalies: list[str]           # end без begin, > N сек
    conclusions: list[str]
```

### Парсер (эвристики, без LLM)

- [ ] Фильтр строк: `"WorkflowTrace" in file` (регистронезависимо).
- [ ] Regex / подстроки: `начало сохран`, `конец`, `begin`, `end` (конфигурируемый список в `workflow_trace_rules.yaml` или константы).
- [ ] Сопоставление begin/end по **нормализованному label** (обрезка кавычек, lowercase).
- [ ] Порог «долгий этап на клиенте» из env `POC_WORKFLOW_LONG_SEC` (default 30) — для отличия 2 с vs 30 мин (клиент уже закончил, сервер ещё крутится).

### API

- [ ] `POST /api/analyze-workflow-trace`  
  Body: `time_window_lines`, опционально `long_step_sec`.  
  Response: `WorkflowTraceSummary`.

### UI

- [ ] Автовызов при нажатии «Шаг 6» (если в срезе есть WorkflowTrace) или отдельная кнопка «Workflow».
- [ ] Таблица: операция | начало | конец | длительность (с).

### Досье шага 6

```json
"step_workflow_trace": {
  "ran": true,
  "paired_operations": [...],
  "anomalies": [...],
  "prior_conclusions": [...]
}
```

### Приёмка

- [ ] На golden/button_incident срез с WorkflowTrace: видны пары с ~1.5–2 с и отдельно долгие server-side из шага 4.
- [ ] В `not_proven` шага 6 LLM может сослаться на факты E1, а не выдумывать «браузер».

---

## E.2 — Client / console логи (приоритет 2)

### Задача

Показать, были ли **события на стороне клиента** (обрыв, reset, timeout UI), а не только server exceptions.

### Модуль

`incident_intent/client_log_analysis.py`

- [ ] Фильтр: `ClientLogs` в пути файла (и опционально `console`, `browser` в имени).
- [ ] Маркеры (YAML или константы): `ConnectionReset`, `оборвал соединение`, `disconnect`, `SignalR`, `WebSocket`, `таймаут` + client context.
- [ ] Подсчёт по категориям; топ N цитат (обрезка 500 символов).

### API

- [ ] `POST /api/analyze-client-logs` → `ClientLogSummary`.

### Досье шага 6

```json
"step_client_logs": {
  "ran": true,
  "event_count": 3,
  "by_category": {"connection_reset": 2},
  "sample_lines": [...],
  "prior_conclusions": ["Обрывы соединения на клиенте согласуются с долгим ожиданием ответа сервера"]
}
```

### Приёмка

- [ ] Строки с `ConnectionReset` из golden попадают в отчёт E2.
- [ ] Если E2 пусто, шаг 6 в `not_proven` может указать «клиентская сторона по логам не подтверждена».

---

## E.3 — Индекс caseone / конфиг (приоритет 3, пересечение с B.6)

### Задача

Не читать C#-исходники целиком, а дать LLM **релевантные настройки** (таймауты, лимиты) из `caseone_path`.

### Модуль

`incident_intent/caseone_config_index.py`

- [ ] Обход `temp/caseone` (или `caseone_path` из сессии): `appsettings*.json`, `web.config`, `*.config` (лимит размера файла, skip `bin/`).
- [ ] Извлечь пары key → value; **маскировать** connection strings, password, secret, token.
- [ ] Ранжировать по совпадению с `search_keywords` / симптомами из шага 0 (Timeout, RequestLogging, Kestrel, CommandTimeout…).
- [ ] Top 15–20 snippets в досье.

### Когда запускать

- [ ] После шага 0, если `caseone_dir` существует и не пуст.
- [ ] Или лениво перед шагом 6.

### Приёмка

- [ ] В досье есть `step_caseone_config.ran=true` и фрагменты без паролей.
- [ ] Шаги 1–5 **не зависят** от caseone.

*Детальный план дублирует [uni_poc_B_plan.md](./uni_poc_B_plan.md) фазу 4 — реализовать **один раз**, в E только подключить к evidence.*

---

## E.4 — HITL: правка заключения (приоритет 4)

### Задача

Инженер может **отредактировать** `conclusion_markdown` и сохранить финальную версию (без повторного прогона 0–5).

### Модель данных

- [ ] `DialogState` / отдельное поле: `conclusion_draft`, `conclusion_final`, `conclusion_hitl_edited_at`.
- [ ] Или только хранить `user_conclusion_markdown` поверх `llm_conclusion_markdown`.

### API

- [ ] `POST /api/incident-conclusion/save` — тело: `incident_id`, `conclusion_markdown` (правка пользователя).
- [ ] `GET` в диалоге возвращает обе версии для diff (опционально).

### UI

- [ ] После шага 6 — textarea «Правка заключения» + «Сохранить».
- [ ] Подпись: «Исходный текст модели» / «Версия инженера».

### Что не делаем в PoC

- [ ] Повторный вызов LLM с правками как training.
- [ ] Workflow approval / Jira export.

### Приёмка

- [ ] Правка сохраняется в сессии и переживает перезагрузку страницы (если session API уже хранит state).

---

## Интеграция в шаг 6 (промпт)

Минимальное дополнение в `incident_conclusion_system.md` (3–5 строк):

- Если `step_workflow_trace.ran` — различай длительность **на клиенте** (trace) и **на сервере** (шаг 4).
- Если `step_client_logs` пуст — не утверждай «проблема браузера/сети».
- Если `step_caseone_config` — настройки не доказывают причину, только контекст.
- `not_proven` обязан учитывать отсутствие E1/E2.

Код: `build_evidence_payload()` принимает опциональные `workflow_trace`, `client_logs`, `caseone_config` в `IncidentConclusionRequest`.

---

## Карта файлов

| Файл | E# | Действие |
|------|-----|----------|
| `workflow_trace_analysis.py` | E.1 | **новый** |
| `workflow_trace_rules.yaml` | E.1 | **новый** (опционально) |
| `client_log_analysis.py` | E.2 | **новый** |
| `caseone_config_index.py` | E.3 | **новый** (или общий с B) |
| `evidence_bundle.py` | E1–E3 | секции в досье |
| `conclusion_models.py` | E1–E4 | поля запроса/ответа |
| `app.py` | E1–E4 | routes |
| `dialog_service.py` / `dialog_models.py` | E4 | HITL state |
| `static/index.html` | E1–E4 | кнопки / панели |
| `tests/test_workflow_trace.py` | E.1 | fixtures |
| `tests/test_client_logs.py` | E.2 | fixtures |
| `prompts/incident_conclusion_system.md` | E1–E3 | 3–5 строк |

---

## Порядок внедрения

```
E.1 WorkflowTrace     ← максимальная ценность для golden-кейса
E.2 ClientLogs        ← быстро, похоже на error_classifier
E.3 caseone index     ← можно переиспользовать план B.4
E.4 HITL              ← UI, не блокирует E1–E3
Интеграция в шаг 6    ← после E1+E2 (+E3 при наличии)
```

Оценка: E.1 + E.2 + досье ≈ **3–5 дней**; E.4 + UI ≈ **1–2 дня**; E.3 ≈ **1–2 дня**.

---

## Риски

| Риск | Митигация |
|------|-----------|
| Формат WorkflowTrace меняется между версиями CaseOne | Правила в YAML; fallback «сырые» цитаты в samples |
| Ложные пары begin/end | Нормализация label; anomalies в отчёте |
| caseone огромный | Лимит файлов/размера; только config, не .cs |
| HITL раздувает UI | Сначала textarea, без diff |

---

## Чеклист «пункт E закрыт (PoC)»

- [ ] E1: структурированный разбор WorkflowTrace в срезе.
- [ ] E2: отчёт по ClientLogs (обрывы/клиент).
- [ ] E3: индекс конфига caseone в досье шага 6 (без секретов).
- [ ] E4: сохранение правки заключения человеком.
- [ ] Шаг 6 использует E1–E3 в `supported_by` / `not_proven`, не выдумывает клиент/trace.
- [ ] Тесты + обновление golden/README.

---

## Связь с другими пунктами

| Пункт | Связь |
|-------|--------|
| **B** | E1/E2 — те же `time_window_lines`; E3 = B.6 |
| **F** | Без среза WorkflowTrace/Client в окне E1/E2 пусты |
| **D** | Лимиты цитат в досье — те же 20×500 |
| **C.5** | ProjectTypes vs Projects — **вне E**; отдельная задача |

---

## Что сознательно не входит в E

- Полный парсинг C# / IL / decompile caseone.
- Автоматический HAR / login пользователя из логов (только если есть в тексте строки).
- Замена шага 6 на «один LLM по всем логам» — объём и галлюцинации.
