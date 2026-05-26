# План: якоря в артефактах → Confluence (Wiki) → playbook или LLM

**Статус:** реализовано в PoC (v1): `artifact_scan`, `confluence_*`, `playbook_gate`, `render_playbook`, шаги 1–11 в `pipeline.py`. UI журнала — без отдельных панелей Confluence (только API/шаги).  
**Контекст PoC:** сейчас шаги 0–8; Wiki/Confluence в коде **нет**. Поиск `search_keywords` идёт только по срезу в памяти (шаг 2 пайплайна).  
**Решение по порядку:** сначала скан **артефактов** (keywords + якоря в двух временных окнах), затем запрос в **Confluence**, затем ветка playbook / полный разбор.

---

## 1. Цель

После шага 0 система должна:

1. Прочитать **загруженные логи** (артефакты) с фильтром по **узкому** и **широкому** временному окну.
2. Найти там **keywords** и **якоря**, в том числе **добавить якоря из логов**, которых не было в тексте жалобы.
3. По объединённому набору искать **готовые статьи в Confluence**.
4. Если статья найдена **и** логи подтверждают сценарий — отдать **playbook** (текст из Confluence + цитаты из логов).
5. Иначе — выполнить **текущий** пайплайн (срез, slow, errors, workflow, client, caseone) и **заключение LLM** (шаг 8 как сейчас).

---

## 2. Термины

| Термин | Определение |
|--------|-------------|
| **Артефакты** | Файлы на диске по `logs_path`: каталог инцидента `temp/incidents/<id>/` или любой подкаталог в `logs/`. |
| **Узкое окно (narrow)** | `incident_date` + `time_window_start` + `time_window_end` из таблицы намерений. |
| **Широкое окно (wide)** | Узкое окно ± `POC_SLOW_WINDOW_PADDING_H` часов (сейчас по умолчанию 1 ч). Используется для тех же границ, что `slow_time_window` в `filter_logs`. |
| **Keywords** | `search_keywords` — широкие подстроки из шага 0 (`таймаут`, `отчёт`). |
| **Якоря (intent)** | `anchors` — узкие метки из шага 0 (API, SQL, exception). Могут быть пустыми или коротким списком. |
| **Якоря (discovered)** | Метки, **извлечённые из логов** на скане (ошибки, `/api/...`, фрагменты из `error_rules.yaml`). |
| **Срез в памяти** | `time_window_lines` / `slow_time_window_lines` — список строк с лимитом; может обрезаться. |
| **Скан артефактов** | Построчное чтение файлов с диска; на выходе счётчики и примеры строк, **без** хранения всего корпуса в RAM. |
| **Confluence / Wiki** | Корпоративная база готовых решений; источник истины — **страницы Confluence**, не папка markdown в репо. |
| **Playbook** | Ответ пользователю: заголовок и тело из страницы Confluence + блок «Подтверждение в логах» + ссылка на страницу. |
| **Playbook gate** | Автоматическое правило: можно ли отдать playbook без полного разбора. |

---

## 3. Что есть в репозитории сейчас (факт)

| Компонент | Есть? |
|-----------|--------|
| Confluence / Atlassian | **Нет** (ни кода, ни зависимости) |
| `httpx` | **Да** (`requirements.txt`) — можно вызывать REST напрямую |
| Фильтр строк по времени | **Да** (`log_scan.py`, `time_window_bounds.py`) |
| Расширенное окно ±1 ч | **Да** (`time_window_utils.DEFAULT_SLOW_PADDING_H`) |
| Классификатор ошибок по строке | **Да** (`error_classifier.py`, `error_rules.yaml`) |
| Поиск keywords в срезе | **Да** (`symptom_search.py`) |
| LLM-заключение | **Да** (`incident_conclusion.py`) |

**Вывод:** Confluence подключаем **новым модулем**; логику времени и ошибок **переиспользуем**, не копируем.

---

## 4. Подключение к Confluence (существующие решения)

### 4.1. Выбранный стек для PoC

| Слой | Решение | Зачем |
|------|---------|--------|
| Клиент API | **[atlassian-python-api](https://atlassian-python-api.readthedocs.io/en/latest/confluence.html)** (`pip install atlassian-python-api`) | Стандарт для Confluence Server и Cloud: CQL, `get_page_by_id`, storage HTML → text; примеры в официальном репозитории `examples/confluence`. |
| HTTP (запасной) | **`httpx`** (уже в проекте) | Прямые вызовы REST, если нужен тонкий контроль или обход бага библиотеки. |
| Конфигурация | **Переменные окружения** | Тот же подход, что `OLLAMA_*` в `ollama_client.py`. |
| Кэш страниц | **Локальный каталог** `temp/confluence_cache/` | PoC не дергает Confluence на каждый якорь; TTL настраивается. |

В репозитории **нет** своего legacy-клиента Confluence — «существующее решение» здесь означает **отраслевой клиент Atlassian**, а не файл в `tsrag-poc`.

### 4.2. Переменные окружения (обязательно описать в `env/docker.env.example`)

| Переменная | Назначение | Пример |
|------------|------------|--------|
| `CONFLUENCE_URL` | Базовый URL (без хвоста `/wiki` если библиотека добавляет сама — зафиксировать в README после первого подключения) | `https://confluence.company.ru` |
| `CONFLUENCE_CLOUD` | `true` / `false` | `false` для Server/Data Center |
| `CONFLUENCE_USERNAME` | Логин (Cloud: email) | `svc-tsrag` |
| `CONFLUENCE_TOKEN` | API token (Cloud) или пароль (Server) | секрет, не в git |
| `CONFLUENCE_PAT` | Альтернатива для Server DC: Personal Access Token | если используется вместо password |
| `CONFLUENCE_SPACE_KEY` | Ограничить поиск одним space | `SUPPORT` |
| `CONFLUENCE_ROOT_PAGE_ID` | Опционально: искать только под деревом страницы | `123456` |
| `CONFLUENCE_CQL_PREFIX` | Доп. фильтр CQL для всех запросов | `label = "incident-playbook"` |
| `CONFLUENCE_TIMEOUT_SEC` | Таймаут HTTP | `60` |
| `CONFLUENCE_CACHE_TTL_SEC` | TTL кэша тел страниц | `3600` |
| `CONFLUENCE_SEARCH_LIMIT` | Макс. страниц в выдаче CQL | `10` |

Если `CONFLUENCE_URL` пуст — шаг Confluence **пропускается** (`skipped`), пайплайн идёт как сейчас (без ошибки).

### 4.3. Режимы аутентификации (явно)

| Режим | Когда | Как |
|-------|--------|-----|
| **Cloud** | `CONFLUENCE_CLOUD=true` | `Confluence(url, username, password=API_TOKEN, cloud=True)` |
| **Server / Data Center** | `CONFLUENCE_CLOUD=false` | `Confluence(url, username, password)` **или** `token=CONFLUENCE_PAT` |

Модуль `confluence_client.py` при старте проверяет: задан URL и (token **или** username+password). Иначе — `ConfluenceNotConfigured`.

### 4.4. Поиск в Confluence (алгоритм v1)

**Вход:** `anchors_for_search[]`, `symptoms[]`, `investigation_goal` (короткая строка).

**Шаги:**

1. Собрать текст запроса: до 20 якорей (самые частые в логах первыми) + первые 3 symptom, обрезка общей длины (например 500 символов).
2. CQL (приоритет):
   - если задан `CONFLUENCE_CQL_PREFIX`:  
     `(CONFLUENCE_CQL_PREFIX) AND (siteSearch ~ "..." OR text ~ "anchor1" OR text ~ "anchor2")`
   - иначе:  
     `siteSearch ~ "..." AND type = page`  
     (`siteSearch` ближе к ручному поиску в UI, чем один только `text ~`)
3. Ограничить `space = KEY` если задан `CONFLUENCE_SPACE_KEY`.
4. Вызвать `confluence.cql(cql, limit=CONFLUENCE_SEARCH_LIMIT)`.
5. Для каждой страницы-кандидата:
   - загрузить body (storage → plain text / markdown упрощённо);
   - посчитать **сколько якорей из `anchors_for_search` встречается в тексте страницы** (`page_anchor_hits`);
   - итоговый score = вес CQL-позиции + `page_anchor_hits`.
6. Вернуть **топ-1** страницу + список runner-up (id, title) для журнала.

**Метаданные страниц (рекомендация для авторов Wiki):**

- Label `incident-playbook` на всех статьях-кандидатах.
- В начале статьи блок **«Якоря»** (список через запятую) — парсить при индексации в кэш для точного матчинга (дополнение к полнотекстовому поиску).

### 4.5. Модуль `incident_intent/confluence_client.py`

Ответственность:

- `get_confluence()` — singleton / фабрика из env;
- `search_playbooks(req: ConfluenceSearchRequest) -> ConfluenceSearchResponse`;
- `get_page_content(page_id) -> ConfluencePage` (из API или кэша);
- `ConfluenceError` — сетевые и 401/403 ошибки; в журнале шага понятный текст.

Зависимость добавить в `requirements.txt`: `atlassian-python-api>=3.41.0` (версию зафиксировать при первом `pip install`).

### 4.6. Эталон для тестов без боевого Confluence

- **Интеграционные тесты** — помечать `@pytest.mark.confluence`, пропускать без env.
- **Unit-тесты** — мок ответа `cql()` JSON из файла `tests/fixtures/confluence_search_sample.json`.
- Статья по сценарию «кнопка / PutProjectType» — завести **реальную страницу** в dev-space Confluence или мок с телом из `golden_set/button_incident.md`.

---

## 5. Порядок пайплайна (без двусмысленности)

Нумерация — **логическая**; в UI журнале можно показывать «Шаг 2», «Шаг 3» с подписями.

```
┌─────────────────────────────────────────────────────────────┐
│ 0. Таблица намерений (как сейчас)                           │
│    + поле anchors[]                                         │
│    + search_keywords[], symptoms[], окно времени            │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Проверка артефактов + границы narrow / wide              │
│    (пути, список *.log, datetime bounds)                    │
│    Опционально: построить срез в памяти для шагов 6–10      │
│    (текущий filter_logs — не удалять)                       │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Скан артефактов (ОБЯЗАТЕЛЬНО до Confluence)              │
│    scan_artifacts: keywords + anchors по файлам на диске    │
│    окна: narrow и wide (отдельные счётчики)                 │
│    + discovered_anchors из ошибок и /api/...                │
│    Выход: ArtifactScanResult (единый для Confluence и gate) │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. Сбор запроса для Confluence                              │
│    anchors_for_search = unique(intent.anchors + discovered) │
│    + symptoms + investigation_goal                          │
│    keywords — для отчёта и ранжирования, не единственный    │
│    сигнал                                                   │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Confluence search (Wiki)                                 │
│    если Confluence не настроен → skipped                    │
└───────────────────────────┬─────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. Playbook gate                                            │
│    use_playbook = правила из §6                             │
└───────────────┬─────────────────────────────┬───────────────┘
                │ ДА                          │ НЕТ
                ▼                             ▼
┌───────────────────────────┐   ┌─────────────────────────────┐
│ 8a. Playbook              │   │ 6–10. Полный разбор         │
│ из Confluence + цитаты    │   │ slow, errors, workflow,     │
│ шаги 6–10 skipped         │   │ client, caseone             │
│ LLM не вызывается         │   │                             │
└───────────────────────────┘   └──────────────┬──────────────┘
                                               ▼
                               ┌─────────────────────────────┐
                               │ 11. LLM заключение (как     │
                               │ сейчас) + confluence_hints  │
                               │ если Wiki нашла, но gate нет│
                               └─────────────────────────────┘
```

**Жёсткие правила:**

- Шаг **2** всегда выполняется до шага **4**, если есть `logs_path` и хотя бы один файл `.log`.
- Результат шага **2** используется и для **запроса в Confluence**, и для **gate** — **второго** полного прохода по диску нет.
- Шаг **1** (срез в памяти) **не заменяет** шаг 2; срез может быть обрезан, скан — источник правды для якорей.

---

## 6. Playbook gate (правила v1)

`use_playbook = true` **только если все** условия выполнены:

| # | Условие |
|---|---------|
| G1 | Confluence настроен и шаг 4 вернул `found=true` |
| G2 | `page_anchor_hits >= CONFLUENCE_PAGE_ANCHOR_MIN` (по умолчанию **2**): столько якорей из `anchors_for_search` найдено **в теле страницы** |
| G3 | `log_anchor_hits >= LOG_ANCHOR_MIN` (по умолчанию **2**): столько якорей из **той же статьи** (или из пересечения статья∩search) найдено в логах на шаге 2 (narrow **или** wide) |
| G4 | Пересечение якорей «статья ∩ логи» не пустое (минимум **1** общий якорь) |

Если G1–G4 не выполнены — `use_playbook=false`, в журнале строка `reason` (например: «в логах только 1 якорь из статьи»).

**Keywords без якорей** не открывают playbook сами по себе.

---

## 7. Шаг 2 — `scan_artifacts` (спецификация)

### 7.1. Модуль

- `incident_intent/artifact_scan.py`
- `incident_intent/artifact_scan_models.py`

### 7.2. Вход

```text
logs_path
incident_date, time_window_start, time_window_end
search_keywords[]
anchors[]
recursive, max_depth (как в filter_logs)
```

### 7.3. Действие

Для каждого файла из `discover_log_files`:

1. Открыть файл построчно.
2. Определить, попадает ли строка в **narrow** и/или **wide** (тот же `TimeSliceFilter` / `line_in_time_window`, что в `log_scan.py`).
3. Если строка в хотя бы одном окне:
   - проверить каждый `search_keyword` → `keyword_hits[narrow|wide][keyword]++`;
   - проверить каждый `anchor` (intent) → `anchor_hits++`;
   - если `classify_error_line` не None → добавить метку в `discovered_anchors`;
   - если в строке есть подстрока `/api/` — извлечь путь (regex), добавить в `discovered_anchors`;
   - сохранить до `ANCHOR_SAMPLE_LINES` примеров на якорь (файл, номер строки, окно, текст до 500 символов).

### 7.4. Выход `ArtifactScanResult`

| Поле | Тип | Смысл |
|------|-----|--------|
| `status` | ok / error / skipped | |
| `narrow_line_count` | int | Строк, прошедших narrow |
| `wide_line_count` | int | Строк, прошедших wide |
| `keyword_hits` | dict | keyword → {narrow, wide} |
| `anchor_hits` | dict | anchor → {narrow, wide} |
| `discovered_anchors` | list[str] | Уникальные, max 30 |
| `samples` | list | Примеры для UI и playbook |
| `errors` | list[str] | |

### 7.5. Лимиты (env)

| Переменная | По умолчанию |
|------------|----------------|
| `POC_ARTIFACT_SCAN_MAX_SAMPLES_PER_ANCHOR` | 3 |
| `POC_ARTIFACT_SCAN_MAX_DISCOVERED_ANCHORS` | 30 |

---

## 8. Шаг 8a — Playbook из Confluence

### 8.1. Содержимое ответа

- `conclusion_markdown` — из шаблона:
  - заголовок страницы;
  - основной текст (из Confluence, без макросов по возможности);
  - блок **«Подтверждение в логах»** — 2–5 цитат из `ArtifactScanResult.samples` (приоритет narrow);
  - ссылка `CONFLUENCE_URL/pages/viewpage.action?pageId=...`;
- `conclusion_source = "confluence"`
- `confluence_page_id`, `confluence_title`, `confluence_url`

### 8.2. Цитаты

- Сначала примеры из **narrow**;
- если для якоря в narrow 0 — одна цитата из **wide** с пометкой: «вне основного окна жалобы».

### 8.3. LLM

- **Не вызывается** в v1 при playbook.
- Опционально фаза 2: `POC_PLAYBOOK_LLM_FORMAT=true` — только переформатирование, без смены фактов.

---

## 9. Полный разбор (если gate = false)

Выполняются **без изменения смысла**:

| Шаг | Модуль | Примечание |
|-----|--------|------------|
| Срез | `filter_logs` | как сейчас |
| Keywords в срезе | `search_symptoms` | оставить; дублирует часть шага 2 — в досье LLM указать оба блока |
| Slow | `find_slow_requests` | wide срез |
| Errors | `correlate_errors` | |
| Workflow / Client / Caseone | без изменений | |
| LLM | `build_incident_conclusion` | в `evidence_bundle` добавить `artifact_scan` и `confluence_candidates` |

---

## 10. Изменения шага 0 (таблица намерений)

1. Поле `IntentTable.anchors: list[str]`.
2. Промпт `intent_table_system.md`: отличие keywords vs anchors.
3. `extractor.py`: парсинг, нормализация (3–120 символов, max 30).
4. Пустые `anchors` **не блокируют** пайплайн — шаг 2 заполнит `discovered_anchors` из логов.

---

## 11. Изменения `pipeline.py`

Новые `PIPELINE_STEP_DEFS` (пример подписей):

| step_id | title_suffix |
|---------|----------------|
| `sources` | Проверка артефактов и границ времени |
| `artifact_scan` | Keywords и якоря в логах (узкое и широкое окно) |
| `confluence` | Поиск решения в Confluence |
| `playbook_gate` | Решение: playbook или полный разбор |
| … | существующие slow, errors, … |
| `conclusion` | Playbook или заключение LLM |

Ветвление после `playbook_gate` — см. §5.

`PipelineResponse` расширить: `artifact_scan`, `confluence_search`, `playbook_gate`, `conclusion_source`.

---

## 12. API (отладка)

| Метод | Путь |
|-------|------|
| POST | `/api/scan-artifacts` |
| POST | `/api/confluence-search` |
| POST | `/api/incident/process` | обновлённый оркестратор |

---

## 13. UI (`static/index.html`)

1. В таблице намерений — колонки/список **Keywords** и **Якоря**.
2. В журнале — шаги `artifact_scan`, `confluence`, `playbook_gate`.
3. Бейдж итога: **«Из Confluence»** / **«Разбор LLM»**.
4. Ссылка на страницу Confluence при playbook.
5. При gate=false и найденной статье — панель «Кандидаты Confluence (не подтверждено)».

---

## 14. Два окна — что куда (таблица)

| Действие | Narrow | Wide |
|----------|--------|------|
| Счётчики keywords/якорей на шаге 2 | да | да |
| Засчитать якорь для gate G3 | да | да (любое из окон) |
| Цитаты в playbook | в первую очередь | если в narrow пусто |
| Срез `time_window_lines` (slow/errors) | узкий срез | `slow_time_window_lines` |
| Confluence-запрос | использует **оба** (частоты якорей суммировать narrow+wide для ранжирования) | |

**Не утверждение:** narrow = следствие, wide = причина.  
**Утверждение:** narrow = время жалобы; wide = запас для длинных операций и хвостов.

---

## 15. Что НЕ делаем в v1

1. Поиск по артефактам **без** фильтра времени (кроме явного `full_corpus` с предупреждением).
2. Playbook без подтверждения якорями в логах (G3–G4).
3. Playbook без загрузки тела страницы из Confluence.
4. Хранение секретов Confluence в репозитории.
5. Замена Confluence папкой markdown в git (только кэш и фикстуры тестов).
6. HITL-утверждение оператором.
7. Индексация всего Confluence offline (только поиск по API + кэш топ-страниц).

---

## 16. Фазы реализации

### Фаза 0 — решения организации

- [ ] URL Confluence (Server или Cloud), service account, space key, label/CQL prefix.
- [ ] Список 3–5 эталонных страниц-playbook для тестов.

### Фаза 1 — шаг 0 + artifact scan (без Confluence)

- [ ] `anchors` в IntentTable и extractor.
- [ ] `artifact_scan.py` + тесты narrow/wide.
- [ ] API `/api/scan-artifacts`.

**Готово:** по тестовым логам видны `discovered_anchors` без Confluence.

### Фаза 2 — Confluence client

- [ ] `confluence_client.py`, env, `requirements.txt`.
- [ ] `confluence_search.py` + кэш.
- [ ] API `/api/confluence-search`.
- [ ] Интеграционный тест с env (опционально).

**Готово:** по якорям из golden_set возвращается страница (боевая или мок).

### Фаза 3 — gate + playbook + pipeline

- [ ] `playbook_gate.py`, `render_playbook.py`.
- [ ] Ветвление в `pipeline.py`.
- [ ] `evidence_bundle` для LLM-пути.

**Готово:** сценарий playbook end-to-end.

### Фаза 4 — UI + README

- [ ] Журнал, бейджи, ссылки.
- [ ] README, `docker.env.example`, диаграмма sequence.

---

## 17. Критерии приёмки

| # | Сценарий | Ожидание |
|---|----------|----------|
| A | Логи + якоря в логах + страница Confluence с теми же якорями | `conclusion_source=confluence`, LLM не вызван, шаги slow–caseone skipped |
| B | Confluence нашла статью, в логах 0 якорей из статьи | полный пайплайн, в досье `confluence_candidates` |
| C | Confluence не настроен | шаг skipped, полный пайплайн |
| D | В жалобе 2 keyword, в логах найдены API/SQL якоря | `discovered_anchors` не пуст; Confluence запрос использует их |
| E | Якорь только в wide | gate может пройти; цитата с пометкой про wide |
| F | Пустые артефакты | шаг 2 error, Confluence не вызывается или skipped, понятная ошибка |

---

## 18. Риски

| Риск | Митигация |
|------|-----------|
| Confluence недоступен из Docker | `host.docker.internal` / VPN; таймаут; fallback на полный разбор |
| CQL не находит то же, что UI | `siteSearch`, label `incident-playbook`, якоря в теле страницы |
| Ложный playbook | gate G2–G4 |
| Медленный скан больших логов | только narrow+wide; без полного корпуса; лимит файлов как сейчас |
| HTML Confluence с макросами | упрощённый strip HTML; фаза 2 — storage XHTML parser |

---

## 19. Связь с текущим README

После реализации обновить таблицу пайплайна в `README.md`:

| Шаг | ID | Содержание |
|-----|-----|------------|
| 1 | `sources` | Пути + срез (как сейчас filter) |
| 2 | `artifact_scan` | Keywords/якоря в артефактах (narrow/wide) |
| 3 | `confluence` | Поиск в Confluence |
| 4 | `playbook_gate` | Ветвление |
| 5–9 | … | slow, errors, … (если gate=false) |
| 10 | `conclusion` | Playbook или LLM |

---

## 20. Открытые вопросы (нужен ответ до фазы 2)

1. **Confluence Server или Cloud?** (влияет на `CONFLUENCE_CLOUD` и auth.)
2. **Space key** и **label/CQL** для playbooks?
3. Нужен ли **корневой page id** (поиск только в поддереве)?
4. Service account уже есть или создаём?

---

*Документ заменяет предыдущий черновик плана с порядком «Wiki рано»; актуальный порядок: **артефакты → Confluence → gate → playbook | LLM**.*
