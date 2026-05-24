# План работ: пункт F (фильтр по времени)

**Контекст:** A и B закрыты для основного UX; `timestamp_parsers.py` уже используется для **корреляции** шагов 4↔5, но **не** для среза шагов 1–2.

**Цель F:** срез по времени инцидента должен работать, если в upload есть CaseOne, nginx, IIS, MSSQL, PostgreSQL — даже когда формат метки **не** `YYYY-MM-DD HH:`.

**Ограничение (как в B):** промпты 0 и 6 **минимально трогаем** — логику форматов и TZ по возможности в **Python**, не в инструкции LLM.

---

## Что мешает сейчас

| # | Проблема | Где |
|---|----------|-----|
| F.1 | Срез = `any(pattern in line)` | `log_scan.line_matches_time`, `time_window_slice` |
| F.1 | Паттерны только `2026-04-23 20:` | `time_window_utils.hour_patterns`, шаг 0 LLM |
| F.1 | nginx `[23/Apr/2026:20:…]`, IIS табы, `23.04.2026` **не попадают** | — |
| F.2 | «20:00» из жалобы ≠ TZ в nginx `+0300` / UTC в PostgreSQL | нигде |
| F.2 | Нет поля «часовой пояс логов» | `IntentTable`, UI |
| F.3 | `timestamp_parsers` — 3 формата, без MSSQL/PG/EU | `timestamp_parsers.py` |
| F.4 | При пустом срезе пользователь не видит **почему** (формат vs пустые логи) | `log_filter.py`, UI |

**Типичная ловушка:** логи на диске есть, шаги 1–2 показывают **0 строк** — patterns шага 0 не совпали с текстом строки.

---

## Принцип решения

Два слоя (можно внедрять по очереди):

```
Жалоба → окно [start, end] + дата (+ TZ)
              │
              ├─► Слой 1 (быстро): больше grep-паттернов под форматы файлов
              │
              └─► Слой 2 (надёжно): parse timestamp → сравнение с окном datetime
```

**Слой 1** — расширить `log_search_patterns` без полного перечитывания архитектуры.  
**Слой 2** — для строк, где grep неоднозначен, или как основной режим после probe.

Probe (разведка) при шагах 1–2: по первым строкам каждого файла определить **домinant timestamp format** → выбрать паттерны или включить parse-режим.

---

## Фаза 1 — мульти-паттерны (1–2 дня, быстрый выигрыш)

### 1.1 Генератор паттернов по дате/часу

Файл: `incident_intent/time_pattern_factory.py` (новый).

Для `incident_date`, `start`, `end` и списка форматов генерировать префиксы на **каждый час** окна:

| format_id | Пример паттерна для 2026-04-23 20:xx |
|-----------|----------------------------------------|
| `iso_space` | `2026-04-23 20:` *(как сейчас)* |
| `iso_t` | `2026-04-23T20:` |
| `nginx` | `[23/Apr/2026:20:` |
| `eu_dot` | `23.04.2026 20:` |
| `eu_dot_short` | `23.04.26 20:` |
| `sql_bracket` | `2026-04-23 20:` / `24:04:23 20:` (MSSQL locale — опционально) |

- [ ] Функция `patterns_for_window(date, start, end, formats) -> list[str]`.
- [ ] Дедупликация; лимит паттернов (например ≤ 48 на окно), иначе warning в `notes`.
- [ ] В `extractor.py`: после `hour_patterns()` **дополнять** LLM-паттерны factory-паттернами для `iso_space` + `nginx` + `eu_dot` по умолчанию.
- [ ] То же для `slow_log_search_patterns`.

**Приёмка:** nginx access.log с `[23/Apr/2026:20:15:30` попадает в срез без смены жалобы.

### 1.2 Probe формата по файлам

Файл: `incident_intent/timestamp_probe.py` (новый).

- [ ] Прочитать до **50 строк** с начала каждого log-файла (и с конца, если файл большой).
- [ ] Подсчитать, какой regex/парсер чаще срабатывает → `file_timestamp_format`.
- [ ] В `SourcesCheck` / ответе filter-logs: `detected_formats: { "nginx/access.log": "nginx", ... }`.
- [ ] Factory использует **объединение** форматов всех файлов инцидента, не только `iso_space`.

**Приёмка:** в UI шагов 1–2 видно «обнаружены форматы: iso_space, nginx».

---

## Фаза 2 — parse-режим среза (2–4 дня)

### 2.1 Расширить `timestamp_parsers.py`

Добавить парсеры (возвращают **timezone-naive datetime в локали логов** или UTC + offset):

| Источник | Формат |
|----------|--------|
| MSSQL ERRORLOG | `YYYY-MM-DD HH:MM:SS.ms` |
| PostgreSQL | `YYYY-MM-DD HH:MM:SS MSK`, `… UTC`, без TZ |
| IIS W3C | `#Fields:` + табличные строки |
| CaseOne middleware | уже ISO |
| Unix epoch в JSON | редко — фаза 3 |

- [ ] `parse_log_timestamp` → registry: список `(name, parser_fn)`.
- [ ] `detect_timestamp_format(line, file_path) -> str | None`.

### 2.2 Фильтр по datetime вместо подстроки

Файл: `log_scan.py`.

```python
def line_in_time_window(
    line: str,
    *,
    file_path: str,
    window_start: datetime,
    window_end: datetime,
    patterns: tuple[str, ...],  # fallback / fast path
    use_parse: bool,
) -> bool:
```

- [ ] **Fast path:** если `line_matches_time(line, patterns)` → True (как сейчас).
- [ ] **Parse path:** если fast miss и `use_parse` → parse; `window_start <= ts <= window_end`.
- [ ] Границы окна: из `incident_date` + `time_window_start/end` (уже есть в таблице намерений).

Заменить вызовы в `iter_lines_in_time_window` и `build_dual_time_window_slices`.

**Приёмка:** строка с временем в **конце** строки (IIS) попадает в срез, хотя grep-паттерн на начало не сработал.

### 2.3 Режим filter в API

`FilterLogsRequest`:

- [ ] `time_filter_mode`: добавить `"parsed"` | `"grep"` | `"auto"` (default **`auto`** = grep + parse fallback).
- [ ] `full_corpus` — без изменений.

**Приёмка:** `auto` даёт не меньше строк, чем чистый grep, на смешанном zip.

---

## Фаза 3 — часовой пояс (2–3 дня)

### 3.1 Модель данных

`IntentTable` / шаг 0 (код, не обязательно LLM):

- [ ] `log_timezone: str | None` — IANA (`Europe/Moscow`) или offset `+03:00`.
- [ ] Env: `POC_DEFAULT_LOG_TZ=Europe/Moscow`.
- [ ] Если в nginx-строке есть `+0300` — **приоритет offset из строки** над default.

### 3.2 Нормализация при сравнении

- [ ] Жалоба пользователя трактуется в `log_timezone` («20:00 вечера» = 20:00 **в TZ логов**).
- [ ] Parsed nginx UTC → convert to `log_timezone` перед сравнением с окном.
- [ ] PostgreSQL `UTC` vs `MSK` — парсить суффикс.

### 3.3 Уточнение пользователю (опционально)

- [ ] Если probe нашёл **разные offset** в одном инциденте → `notes` + один `clarifying_questions` («Логи в UTC или MSK?»).
- [ ] Промпт шага 0 **не менять**; вопрос генерирует код (`extractor` / `dialog_service`).

**Приёмка:** окно 20:00–22:00 MSK не теряет строки nginx с `[...+0300]`.

---

## Фаза 4 — UX и диагностика (1 день)

- [ ] Пустой срез → явное сообщение:
  - «0 строк: паттерны […] не найдены в логах; probe: nginx, iso; попробуйте расширить окно или проверьте дату».
- [ ] UI: блок «Форматы времени в логах» после шагов 1–2.
- [ ] Счётчик `lines_skipped_unparsed` в parse-режиме.
- [ ] README + пункт F в `uni_poc.md` — отметить закрытие по фазам.

---

## Карта файлов

| Файл | Фаза | Действие |
|------|------|----------|
| `time_pattern_factory.py` | 1 | **новый** — мульти-паттерны |
| `timestamp_probe.py` | 1 | **новый** — разведка форматов |
| `timestamp_parsers.py` | 2–3 | расширить registry |
| `log_scan.py` | 2 | `line_in_time_window`, parse mode |
| `time_window_slice.py` | 2 | передача datetime-окна |
| `time_window_utils.py` | 1 | вызывает factory |
| `extractor.py` | 1, 3 | паттерны, TZ notes |
| `log_filter.py` | 1, 4 | probe, diagnostics |
| `log_filter_models.py` | 2–3 | `time_filter_strategy`, TZ |
| `models.py` | 3 | `log_timezone` |
| `static/index.html` | 4 | форматы, пустой срез |
| `tests/test_time_filter.py` | 1–2 | **новый** — fixtures по форматам |

---

## Порядок внедрения

```
Фаза 1.1  мульти-паттерны (iso + nginx + eu)     ← сразу снимает половину «пустой срез»
Фаза 1.2  probe + UI
Фаза 2    parse-режим auto
Фаза 3    TZ (если инциденты nginx/UTC смешанные)
Фаза 4    диагностика
```

Фазы 1 и 2 можно частично параллелить; **TZ (3) — после 2**, иначе parse без TZ даст ложные промахи.

---

## Риски

| Риск | Митигация |
|------|-----------|
| Parse каждой строки медленнее grep | `auto`: grep first; parse only on miss; один проход в dual slice |
| Слишком много паттернов → ложные совпадения | Паттерны с датой+часом; cap на количество |
| LLM генерирует «не те» patterns | Code factory **дополняет/перекрывает** LLM, не только полагается на неё |
| 100k лимит среза (пункт D) | Не меняем в F; в notes писать если truncated |

---

## Чеклист «пункт F закрыт»

- [ ] Срез не пустой для nginx + CaseOne в одном zip при корректной дате/окне.
- [ ] IIS W3C и MSSQL ERRORLOG попадают в срез (parse или patterns).
- [ ] TZ: default + offset из строки; жалоба «20:00–22:00» согласована с nginx `+0300`.
- [ ] Пустой срез объясняется в UI (форматы, patterns, дата).
- [ ] Тесты: ≥1 fixture на формат (iso, nginx, eu_dot, mssql, iis).

---

## Связь с другими пунктами

| Пункт | Связь |
|-------|--------|
| **B** | parse-режим использует тот же `timestamp_parsers` — корреляция 4↔5 станет точнее |
| **D** | лимит 100k строк не снимаем; F может **увеличить** hit rate внутри лимита |
| **G** | после F пункт G «универсально» расширяется на смешанные форматы времени |

---

## Что сознательно не делаем в F

- Полный парсинг **даты без года** в логах (только из жалобы/папки).
- Автоматический NTP / синхронизация часов между серверами.
- Переписывание шага 0 LLM под каждый формат лога — только код и probe.
