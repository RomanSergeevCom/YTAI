# 05_editing — LLM Edit Brief Pipeline

Этап автоматизации создания монтажного брифа с помощью Claude Desktop.

**Вход:** `{project}_transcript.json` (из 02_transcribe) — транскрипт с таймкодами, спикерами, confidence
**Выход:** `{project}_edit_brief.json` (структурированный бриф) + `{project}_edit_brief_review.html` (визуальное ревью)

**Нейминг чатов в Claude Desktop:** `{project_name}` (напр. `YTCG37_Hadi_Dawani`)

---

## Пайплайн

```
{project}_transcript.json (из 02_transcribe)
    │
    ├──▶ Claude Desktop Project "YTAI Editing — YTXX"
    │    │ Прикрепить transcript.json + указания ("12 мин", "interview")
    │    │ Claude анализирует → возвращает {project}_edit_brief.json (artifact)
    │    ▼
    │  {project}_edit_brief.json
    │    │
    │    ├──▶ python 0503_review/generate_review.py ──▶ {project}_edit_brief_review.html
    │    │    (HTML ревью с цветами — открыть в браузере, принять решения)
    │    │
    │    ├──▶ python 0504_screen_cues/generate_screen_cues_png.py ──▶ screen_cues/*.png
    │    │    (PNG оверлеи для Screen Cues — до запуска UXP)
    │    │
    │    ├──▶ YTAI UXP панель → ASSEMBLY pipeline
    │    │    Загрузить brief → секвенция {project}_ASSEMBLY
    │    │    V1: USE=TRUE сегменты, trimmed, colored, markers
    │    │
    │    ├──▶ YTAI UXP панель → REVIEW pipeline
    │    │    Загрузить brief → секвенция {project}_3_Review
    │    │    V1: все сегменты целиком, markers
    │    │
    │    └──▶ YTAI UXP панель → SCREEN CUES pipeline
    │         Загрузить brief → секвенция {project}_4_ScreenCues
    │         V1: Assembly copy, V2: PNG overlays, markers, SRT
    │
    └──▶ YTAI UXP панель → INGEST pipeline
         Загрузить ingest.json → импорт клипов, бины, Ingest секвенция
```

---

## Файлы

```
YTAI/
├── YTs/                              # Профили каналов
│   ├── _template.md                  # Шаблон
│   ├── YTCG.md                       # Connect Group Dubai
│   └── YTXX.md                       # Другие каналы
│
scripts/05_editing/
├── 05_editing_spec.md                # Этот документ
├── 0500_uxp/                         # UXP плагин для Premiere (v2.1.0)
│   ├── 0500_uxp_spec.md              # Спецификация
│   ├── manifest.json                 # UXP manifest v5
│   ├── package.json                  # Dependencies + test scripts
│   ├── index.js                      # Оркестратор (4 пайплайна: INGEST/ASSEMBLY/REVIEW/SCREENS)
│   ├── index.html                    # UI панель
│   ├── css/styles.css                # Стили панели
│   ├── src/shared/                   # Общие утилиты
│   │   ├── constants.js              # Цвета, ticks, marker types
│   │   ├── utils.js                  # parseTimecode, tickSec, fmtTime
│   │   ├── logger.js                 # Logger class с buffer + UI callback
│   │   └── clipActions.js            # Shared: applyColor, setSourceInOut, cleanExistingSequence, insertDjiAudio
│   ├── src/ingest/                   # INGEST pipeline модули
│   │   ├── ingestLoader.js           # parseIngest(), generateSummary()
│   │   ├── binManager.js             # createBinStructure(), BIN_NAMES
│   │   ├── timelineBuilder.js        # buildIngestSequence()
│   │   ├── transcriptImporter.js     # importTranscripts()
│   │   └── lutManager.js             # copyLutsToCreativeFolder(), applyLumetriToClips()
│   ├── src/assembly/                 # ASSEMBLY pipeline модули
│   │   ├── briefParser.js            # parseBrief() — парсер edit_brief.json
│   │   ├── projectScanner.js         # findSourceBin(), buildClipMap()
│   │   └── assemblyBuilder.js        # buildAssemblySequence(), sortSegments()
│   ├── src/review/                   # REVIEW pipeline модули
│   │   └── reviewBuilder.js          # buildReviewSequence()
│   ├── src/screens/                  # SCREEN CUES pipeline модули
│   │   ├── screenParser.js           # parseScreens(), formatSrtContent()
│   │   └── screenBuilder.js          # buildScreenCues() — V1 Assembly copy + V2 PNG overlays
│   ├── LUTs/                         # .cube LUT файлы
│   └── tests/                        # Node.js тесты (186 тестов)
│       ├── mocks/premierepro.js      # Мок Premiere Pro UXP API
│       ├── fixtures/                 # Тестовые данные
│       │   ├── sample_ingest.json
│       │   └── sample_brief.json
│       ├── ingest/                   # Тесты ingest модулей
│       │   ├── ingestLoader.test.js
│       │   └── binManager.test.js
│       ├── assembly/                 # Тесты assembly модулей
│       │   ├── briefParser.test.js
│       │   └── assemblyBuilder.test.js
│       ├── review/                   # Тесты review модулей
│       │   └── reviewBuilder.test.js
│       └── screens/                  # Тесты screen cues модулей
│           ├── screenParser.test.js
│           └── screenBuilder.test.js
├── 0501_brief/                       # Claude Desktop Project файлы
│   ├── 0501_brief.md                 # Quick Start guide
│   ├── 0501_brief_spec.md            # Спецификация
│   ├── INSTRUCTIONS.md               # → Custom Instructions (скопировать)
│   └── project_knowledge/            # → Project Knowledge (загрузить)
│       ├── editing_rules.md          # Правила монтажа + цветовая разметка
│       ├── output_format.md          # JSON-схема выхода
│       ├── example_input.json        # Пример входа (v2.13 transcript)
│       └── example_output.json       # Пример выхода (9 сегментов)
├── 0502_assembly/                    # Вспомогательные скрипты Assembly
│   ├── generate_assembly_captions.py # SRT субтитры из edit_brief.json
│   └── generate_assembly_captions_spec.md
├── 0503_review/                      # Вспомогательные скрипты Review
│   └── generate_review.py            # JSON → HTML ревью
├── 0504_screen_cues/                 # Вспомогательные скрипты Screen Cues
│   ├── generate_screen_cues.py       # SRT субтитры для screen cues
│   ├── generate_screen_cues_png.py   # Pillow → PNG оверлеи (запускать до UXP)
│   └── run_generate.command          # Shell launcher для UXP → Terminal (auto-close, ANSI colors)
├── 999_testing_project/              # Тестовые данные
└── Archive/                          # Архивированные версии
    ├── 0501_claude_kb/               # → заменён на 0501_brief
    ├── 050105_assembly_uxp_v1.9.2_20260310/  # v1.9.2 бэкап
    ├── 050202_claude_kb_20260310/    # brief бэкап (заменён на 0505_claude_kb)
    ├── 050203_uxp_premiere_brief/    # → заменён на 0500_uxp
    ├── 050204_uxp_assembly/          # → заменён на 0500_uxp
    └── 020201_premiere_ingest/       # → заменён на 0500_uxp (ingest)
```

---

## Настройка Claude Desktop Project

### Вариант A: Один проект на канал (рекомендуется)

1. Создать Project: **"YTAI Editing — YTCG"**
2. Custom Instructions: вставить содержимое `0501_brief/INSTRUCTIONS.md`
3. Project Knowledge — загрузить файлы:
   - `0501_brief/project_knowledge/editing_rules.md`
   - `0501_brief/project_knowledge/output_format.md`
   - `0501_brief/project_knowledge/example_input.json`
   - `0501_brief/project_knowledge/example_output.json`
   - `YTs/YTCG.md` (профиль канала)

### Вариант B: Один общий проект

1. Project: **"YTAI Editing"**
2. Knowledge: всё кроме профиля канала
3. В каждом чате: прикрепить нужный `YTXX.md` + `transcript.json`

---

## Использование

### Шаг 1: Генерация брифа

В Claude Desktop (проект "YTAI Editing — YTCG"):

```
[прикрепить transcript.json]
Сделай монтажный бриф. Целевая длительность: 12 минут.
```

Claude вернёт JSON как artifact (скачать) + компактный обзор.

### Шаг 2: Ревью

```bash
python ~/YTAI/scripts/05_editing/0503_review/generate_review.py --brief {project}_edit_brief.json
open {project}_edit_brief_review.html
```

HTML показывает:
- Статистику (total/selected duration, segments, blocks)
- YouTube Chapters preview
- Блоки с цветными заголовками (collapsible)
- Каждый сегмент: USE/SKIP badge, transcript, B-roll, notes
- Таблицу скипнутых сегментов с причинами

### Шаг 3: Корректировка (если нужно)

В том же чате Claude:
```
Убери блок 3, он слишком длинный.
Поменяй hook — используй seg_005 вместо seg_001.
Сделай короче — целевая 10 минут.
```

Claude вернёт обновлённый JSON artifact → скачать → перегенерировать HTML.

### Шаг 4: Загрузка в Premiere (YTAI UXP Panel)

`0500_uxp/` — UXP-плагин v2.1.0 для Premiere Pro с четырьмя пайплайнами.

Premiere → Window > Extensions > YTAI Assembly:

**Workflow (v2.0.0+):** Select Project Folder → auto-detect ingest.json + edit_brief.json → чеклист → Build.
Fallback: ручная загрузка файлов (кнопки Load появляются при отсутствии auto-detect).

#### INGEST (auto-detect или загрузить ingest.json)
- Импорт клипов + DJI audio → `00_Source/` (scene-проекты: подбины `{CODE}_{scene}`)
- Создание `{project} — Ingest` секвенции (все клипы целиком на V1)
- Импорт per-scene SRTs → `01_Transcripts/{CODE}_{scene}_transcripts/` (per-scene `_transcript.srt` + `_captions.srt`; general SRTs not imported)
- Копирование LUTs → Adobe Creative + применение Lumetri Color

#### ASSEMBLY (auto-detect или загрузить edit_brief.json)
- **Секвенция:** `{project}_ASSEMBLY`
- **V1:** USE=TRUE сегменты (block ≠ 99), отсортированы по block → tc_in
- **A1:** Камерное аудио (наследуется от V1)
- **A2/A3:** DJI TX аудио (тримменное с теми же in/out, опционально)
- **Trimmed:** обрезка по tc_in/tc_out + tight repositioning
- **Chapter markers:** на `is_chapter="TRUE"` сегментах
- **Comment markers:** speaker + transcript + broll_note + notes
- **Color labels:** по семантике блока

#### REVIEW (auto-detect edit_brief.json)
- **Секвенция:** `{project}_3_Review`
- **V1:** complement (Ingest − Assembly), на абсолютных позициях
- **A2/A3:** DJI TX аудио (тримменное, на абсолютных позициях, опционально)
- **Markers:** [CUT]/[ALT]/[SKIP] + speaker + transcript + notes
- **Color labels:** по категории отказа (CUT=Red, ALT=Yellow, SKIP=Purple)

#### SCREEN CUES (auto-detect edit_brief.json)
- **Секвенция:** `{project}_4_ScreenCues`
- **V1:** Assembly copy (USE=TRUE сегменты, trimmed, как в Assembly)
- **V2:** PNG оверлеи с текстом screen cues (если PNGs сгенерированы)
- **A2/A3:** DJI TX аудио (тримменное, как в Assembly, опционально)
- **Markers:** Orange Comment на позициях screen cues
- **SRT:** генерируется и импортируется в `01_Transcripts/`
- **Sequences at project root** — Premiere UXP API cannot move sequences into bins
- **Pre-req:** нажать [Generate PNGs] в UXP панели (или `python 0504_screen_cues/generate_screen_cues_png.py --brief ...`) до Build

---

## Нейминг файлов

Все файлы YTAI используют `{project}_` префикс:

| Файл | Паттерн | Пример | Этап |
|------|---------|--------|------|
| Транскрипт | `{project}_transcript.json` | `YTAI_Edit_transcript.json` | 02_transcribe |
| Транскрипт XLSX | `{project}_transcript.xlsx` | `YTAI_Edit_transcript.xlsx` | 02_transcribe |
| Папка транскрипции | `{project}_transcription/` | `YTAI_Edit_transcription/` | 02_transcribe |
| Premiere проект | `{project}.prproj` | `YTAI_Edit.prproj` | 02_transcribe |
| Per-clip транскрипт | `{clip}_premiere_transcript.json` | `C5402_premiere_transcript.json` | 02_transcribe |
| Ingest JSON | `{project}_ingest.json` | `YTAI_Edit_ingest.json` | 02_transcribe |
| Монтажный бриф | `{project}_edit_brief.json` | `YTAI_Edit_edit_brief.json` | 05_editing |
| HTML ревью | `{project}_edit_brief_review.html` | `YTAI_Edit_edit_brief_review.html` | 05_editing |
| Assembly SRT | `{project}_assembly_captions.srt` | `YTAI_Edit_assembly_captions.srt` | 05_editing |
| Screen Cues PNGs | `screen_cues/scr_XXX_{type}.png` | `screen_cues/scr_001_full_overlay.png` | 05_editing |
| Assembly JSON | `{CODE}_Claude4_assembly.json` | `YTCG37_Claude4_assembly.json` | 05_editing |
| Assembly Prompt | `{CODE}_Claude4_assembly_prompt.md` | `YTCG37_Claude4_assembly_prompt.md` | 05_editing |
| Per-scene transcript SRT | `{CODE}_{scene}_transcript.srt` | `YTCG37_01_Interview_transcript.srt` | 02_transcribe |
| Per-scene captions SRT | `{CODE}_{scene}_captions.srt` | `YTCG37_01_Interview_captions.srt` | 02_transcribe |
| Screen Cues SRT | `{project}_4_ScreenCues_captions.srt` | `YTAI_Edit_4_ScreenCues_captions.srt` | 05_editing |

`{project}` = поле `project` в transcript.json (напр. `"YTAI_Edit"`).
`{CODE}` = channel+project code (напр. `"YTCG37"`).

Assembly JSON и Prompt хранятся в `Setup/` папке проекта.

---

## Формат {project}_edit_brief.json

Три объекта: `segments[]`, `screens[]` (опционально) и `project{}`.

### segments[]

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| segment_id | string | Да | `seg_001`, `seg_002`... |
| source_file | string | Да | Имя файла (`C5402.MP4`) |
| tc_in | string | Да | Начало `MM:SS.s` |
| tc_out | string | Да | Конец `MM:SS.s` |
| block | int | Да | Номер блока 1-99 (99 = Cut) |
| block_name | string | Да | Название (max 50) |
| use | string | Да | `"TRUE"` / `"FALSE"` |
| segment_name | string | — | Имя сегмента (max 100) |
| speaker | string | — | Спикер |
| transcript | string | — | Текст (max 500) |
| track | string | — | Всегда `"V1"` |
| color | string | — | Cyan/Blue/Green/Yellow/Red/Magenta/Orange/Purple |
| priority | int | — | 1=main, 2=alternative, 9=cut |
| is_chapter | string | — | `"TRUE"` / `"FALSE"` |
| broll_note | string | — | B-roll предложение (max 200) |
| notes | string | — | Заметки (max 500) |

### screens[] (опционально)

| Поле | Тип | Обяз. | Описание |
|------|-----|-------|----------|
| screen_id | string | Да | `scr_001`, `scr_002`... |
| type | string | Да | Тип: `full_overlay`, `half_overlay`, `three_fifths_overlay`, `chapter_bar`, `lower_third` |
| segment_id | string | Да | Привязка к сегменту (`seg_001`) |
| tc_in | string | — | Позиция внутри сегмента (если отличается от начала) |
| title | string | Да | Заголовок (max 100) |
| subtitle | string | — | Подзаголовок (max 100) |
| body | string | — | Дополнительный текст, используйте `\n` для переносов (max 500) |

### project{}

| Ключ | Тип | Описание |
|------|-----|----------|
| project_name | string | Имя проекта |
| fps | float | FPS из clips[0].media |
| width | int | Ширина |
| height | int | Высота |
| sample_rate | int | Audio sample rate |
| video_tracks | int | 1 |
| audio_tracks | int | 4 |
| create_assembly_sequence | bool | Создавать _ASSEMBLY секвенцию |
| create_chapter_markers | bool | true |
| cut_color | string | Цвет для вырезанных (default: Red) |
| _transcription_dir | string | Папка транскрипции |

---

## Цветовая разметка

| Цвет | Hex | Семантика |
|------|-----|-----------|
| Green | #4CAF50 | Hook, Intro, Conclusion, CTA |
| Blue | #4A90D9 | Образование, объяснения |
| Cyan | #00CED1 | Контекст, предыстория |
| Yellow | #E6C619 | Предупреждения |
| Orange | #EDA63B | Личные истории, примеры |
| Red | #E34850 | Риски, опасности / Cut (block 99) |
| Magenta | #E732E7 | Технические процедуры |
| Purple | #9B59B6 | Решения, рекомендации |

---

## Профили каналов

Хранятся в `/Users/romansergeev/YTAI/YTs/`:
- `_template.md` — шаблон для нового канала
- `YTCG.md` — Connect Group Dubai
- `YTXX.md` — другие каналы (YT + 2-4 буквы)

Формат: Markdown с секциями Overview, Target Audience, Content Format, Style & Tone, Unique Patterns, Key Metrics.

Загружается в Claude Desktop Project как Knowledge для контекста канала.
