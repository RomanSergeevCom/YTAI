# 050202_claude_kb — Specification v1.2.0

Claude Desktop Project Knowledge для создания монтажных брифов.

**Вход:** `{project}_transcript.json` (из 020101_transcribe)
**Выход:** `{project}_edit_brief.json` -> загружается в 050105_assembly_uxp (ASSEMBLY + REVIEW)
**Выход 2:** `{project}_2_Assembly_captions.srt` -> генерируется `generate_assembly_captions.py`
**Выход 3:** `{project}_3_Review_captions.srt` -> генерируется `generate_assembly_captions.py --review`

---

## Назначение

Набор файлов для Claude Desktop Project, который превращает транскрипт видео в структурированный монтажный бриф (JSON). Claude анализирует содержание, определяет блоки/главы, решает что оставить/вырезать, назначает цвета и маркеры.

## Файлы

| Файл | Назначение | Куда загружать |
|------|-----------|---------------|
| `INSTRUCTIONS.md` | Custom Instructions Claude Desktop | -> Custom Instructions |
| `editing_rules.md` | Правила монтажа + цветовая разметка | -> Project Knowledge |
| `output_format.md` | JSON-схема edit_brief.json | -> Project Knowledge |
| `example_input.json` | Пример transcript.json | -> Project Knowledge |
| `example_output.json` | Пример edit_brief.json | -> Project Knowledge |
| `~/YTAI/YTs/YTXX.md` | Профиль канала | -> Project Knowledge |

## Связи

```
020101_transcribe
    |
    +- {project}_transcript.json --> 050202_claude_kb (Claude Desktop)
    |                                     |
    |                                     +- {project}_edit_brief.json
    |                                          |
    |                                          +-->  050105_assembly_uxp (ASSEMBLY: use=TRUE, block≠99)
    |                                          +-->  050105_assembly_uxp (REVIEW: use=FALSE OR block=99)
    |                                          +-->  generate_review.py (HTML ревью)
    |                                          +-->  generate_assembly_captions.py
    |                                                     |
    +- per_clip/{clip_id}_transcript.json ------>          |
                                                          +- {project}_2_Assembly_captions.srt --> 050105 ASSEMBLY (auto-import)
                                                          +- {project}_3_Review_captions.srt   --> 050105 REVIEW   (auto-import)
```

### Генерация Captions (Assembly + Review)

После создания `edit_brief.json`, LLM запускает:
```bash
python generate_assembly_captions.py --brief {project}_edit_brief.json
python generate_assembly_captions.py --brief {project}_edit_brief.json --review
```

Скрипт (единый для обоих режимов):
1. Читает edit_brief + per-clip transcript JSONы (word-level timing)
2. **Assembly**: фильтрует use=TRUE, block!=99, сортирует по block + brief order
3. **Review**: фильтрует use=FALSE OR block=99, сортирует по source_file + tc_in
4. Ремаппит таймкоды слов на соответствующий таймлайн
5. Генерирует `{project}_2_Assembly_captions.srt` или `{project}_3_Review_captions.srt`

UXP плагин (050105_assembly_uxp) автоматически импортирует оба SRT в 02_Transcripts при Build Assembly / Build Review.

### Маппинг полей transcript -> edit_brief

| transcript.json | edit_brief.json | Назначение в Assembly |
|----------------|----------------|----------------------|
| `clips[].filename` | `segments[].source_file` | Ключ для поиска клипа в `00_Source` bin |
| `segments[].start` (seconds) | `tc_in` (MM:SS.s) | Точка входа (pre-trim перед insert) |
| `segments[].end` (seconds) | `tc_out` (MM:SS.s) | Точка выхода |
| `segments[].speaker` | `speaker` | Комментарий в маркере |
| `segments[].text` | `transcript` | Комментарий в маркере |
| `clips[0].media.fps` | `project.fps` | Настройки секвенции |
| `clips[0].media.width` | `project.width` | Настройки секвенции |
| `project` | `project.project_name` | Имя секвенции: `{name}_2_Assembly` |

### Маппинг полей edit_brief -> Assembly UXP

| edit_brief.json | Assembly действие | Примечание |
|----------------|-------------------|-----------|
| `color` | `LABEL_COLOR_INDEX[color]` -> clip label | Per-segment: цвет ставится ПЕРЕД каждой вставкой |
| `color` | `MARKER_COLOR_INDEX[color]` -> marker color | Отдельная палитра! Green=0, Blue=6, Orange=3 |
| `is_chapter="TRUE"` | Chapter marker с `duration=блок` | Только на первом сегменте блока |
| `block_name` | Имя Chapter маркера | "Hook", "Government Vision" и т.д. |
| `use="TRUE"` + `block!=99` | Включается в секвенцию V1 | `use="FALSE"` или `block=99` — пропускается |
| `block` | Порядок на таймлайне | Сегменты сортируются по block, внутри — по порядку в JSON |
| `transcript` + `speaker` + `broll_note` + `notes` | Comment в маркере | Объединяются через " \| " |

### Маппинг полей edit_brief -> Review UXP

| edit_brief.json | Review действие | Примечание |
|----------------|-----------------|-----------|
| `use="FALSE"` OR `block=99` | Включается в Review секвенцию | Инверсия Assembly фильтра |
| `block=99` | Категория **CUT** → Red clip + Red marker | Явно вырезано (шум, ошибки) |
| `priority=2` + `use=FALSE` | Категория **ALT** → Yellow clip + Yellow marker | Альтернативный дубль |
| остальные `use=FALSE` | Категория **SKIP** → Purple clip + Magenta marker | Не выбрано, кандидат на ревью |
| `source_file` | Сортировка → group by source file | Естественный порядок просмотра |
| `tc_in` | Сортировка → tc_in ASC внутри source file | Хронологический порядок |
| `transcript` + `speaker` + `notes` | Comment в маркере | С префиксом [CUT]/[ALT]/[SKIP] |

## Критические поля для Assembly

### `color` (обязательно)
- Контролирует цвет клипа НА ТАЙМЛАЙНЕ и цвет маркера
- Один source file может иметь разные цвета в разных блоках (per-segment application)
- Допустимые значения: `Green`, `Blue`, `Cyan`, `Yellow`, `Orange`, `Red`, `Magenta`, `Purple`

### `is_chapter` (обязательно на первом сегменте блока)
- Ставить `"TRUE"` на ПЕРВЫЙ сегмент каждого блока
- Создаёт Chapter marker с `name=block_name` и `duration=сумма длительностей блока`
- Маркер получает цвет блока (из `MARKER_COLOR_INDEX`)
- Все маркеры — Chapter type (не Event, не Comment)

### `block` + порядок в JSON
- Сегменты сортируются по `block` числу
- Внутри блока — порядок из JSON (НЕ по tc_in!)
- `block=99` исключается из Assembly

### `source_file`
- Должен **точно совпадать** с filename из 00_Source bin
- Единый ключ связи между transcript -> brief -> Premiere Project

## Ключевые отличия от предыдущей версии (0501_claude_kb)

1. **Одна секвенция**: `{project}_2_Assembly` вместо `_FULL` + `_EDIT`
2. **V1 only**: все сегменты на одном видеотреке
3. **track**: всегда `"V1"` (нет `"V2"` для cut)
4. **Feature flags**: `create_assembly_sequence` вместо `create_full_sequence` + `create_edit_sequence`
5. **video_tracks**: 1 вместо 3
6. **Per-segment colors**: один source file может иметь разные цвета в разных блоках
7. **Все маркеры Chapter type**: не Comment, не Event — только Chapter
8. **Colored markers**: маркеры наследуют цвет блока через `MARKER_COLOR_INDEX`
9. **Brief order**: внутри блока порядок определяется JSON, не tc_in
