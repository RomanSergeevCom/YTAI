# 050105_assembly_uxp — Specification v1.8.0

UXP-плагин для Adobe Premiere Pro: **Ingest** + **Assembly** + **Review** в одной панели.

**Вход:**
- INGEST: `{project}_ingest.json` (из 020101_transcribe)
- ASSEMBLY: `{project}_edit_brief.json` (из 050202_claude_kb)
- REVIEW: `{project}_edit_brief.json` (тот же файл, обратный фильтр)

**Выход (Premiere Pro):**
- INGEST: бины `00_Source/`, `01_Sequence/`, `02_Transcripts/`, секвенция `{project}_1_Ingest`
- ASSEMBLY: секвенция `{project}_2_Assembly` (V1 only, trimmed, colored clips + colored Chapter markers)
- REVIEW: секвенция `{project}_3_Review` (V1 only, unused segments, colored by cut category)

---

## Архитектура

```
index.html (UI — sp-button, status dots, log panels)
index.js (оркестратор — state, UI helpers, pipelines)
├── src/shared/
│   ├── constants.js      ← LABEL_COLOR_INDEX, MARKER_COLOR_INDEX, MARKER_TYPE_*, TICKS_PER_SECOND, REVIEW_COLOR_MAP
│   ├── utils.js          ← parseTimecode, tickSec, fmtTime, escapeHtml
│   ├── logger.js         ← Logger class (buffer + onLog callback + debug bundle)
│   └── clipActions.js    ← applyColorToItem(), applyColorByIndex(), setSourceInOut(), clearSourceInOut(), cleanExistingSequence()
├── src/ingest/
│   ├── ingestLoader.js   ← parseIngest(), generateSummary()
│   ├── binManager.js     ← createBinStructure(), BIN_NAMES
│   ├── timelineBuilder.js ← buildIngestSequence(), findProjectItemByName()
│   ├── transcriptImporter.js ← importTranscripts()
│   └── lutManager.js     ← copyLutsToCreativeFolder(), applyLumetriToClips()
├── src/assembly/
│   ├── briefParser.js    ← parseBrief() — парсер edit_brief.json (Format A + B)
│   ├── projectScanner.js ← findSourceBin(), buildClipMap(), validateIngestState()
│   └── assemblyBuilder.js ← buildAssemblySequence(), sortSegments() (uses clipActions)
└── src/review/
    └── reviewBuilder.js  ← buildReviewSequence(), sortReviewSegments(), getReviewCategory(), computeComplement(), computeClipOffsets(), subtractBriefFromRange(), createGapSegment()
```

### Принцип: нулевая связанность

INGEST, ASSEMBLY и REVIEW модули **не импортируют друг друга**. Единственная точка пересечения — `00_Source` бин в Premiere проекте (INGEST создаёт, ASSEMBLY и REVIEW читают). Assembly и Review используют общие утилиты из `src/shared/clipActions.js`.

---

## INGEST Pipeline (6 шагов)

1. **Clean** — удалить старые бины и секвенцию
2. **Bins** — создать `00_Source`, `01_Sequence`, `02_Transcripts`
3. **Sequence** — импорт клипов → `{project}_1_Ingest` (все клипы целиком на V1)
4. **Transcripts** — импорт SRT и premiere_transcript.json
5. **LUTs** — копирование .cube в Adobe Creative, применение Lumetri
6. **Activate** — сохранение проекта + валидация (V1 count, resolution, transcripts, Lumetri)

### Формат входа (ingest.json)
```json
{
  "project_name": "YTAI_Edit",
  "media": { "width": 3840, "height": 2160, "fps": 25, "sample_rate": 48000 },
  "clips": [{ "clip_id": "C5402", "filename": "C5402.MP4", "path": "/abs/...", "duration": 156.0 }],
  "files": { "transcript_json": "...", "transcript_srt": "...", "transcript_xlsx": "..." },
  "source_folder": "/abs/Interview"
}
```

---

## ASSEMBLY Pipeline (6 шагов)

1. **Backup** — сохранение проекта
2. **Scan** — поиск клипов в `00_Source` бине → `clipMap = { filename: ProjectItem }`
3. **Build** — `buildAssemblySequence()` (V1 only, USE=TRUE, block≠99, pre-trimmed, per-segment colors)
4. **Markers** — маркеры в 4 транзакциях: создание → покраска → смена типа на Chapter
5. **Activate** — открытие секвенции + сохранение + валидация
6. **Captions** — `importCaptionsSrt()` — import `{project}_2_Assembly_captions.srt` в 02_Transcripts

### Формат входа (edit_brief.json)

```json
{
  "segments": [{
    "segment_id": "seg_001", "source_file": "C5403.MP4",
    "tc_in": "00:00.0", "tc_out": "01:11.6",
    "block": 1, "block_name": "Hook", "color": "Green",
    "use": "TRUE", "is_chapter": "TRUE",
    "speaker": "Speaker 1", "transcript": "...",
    "broll_note": "...", "notes": "..."
  }],
  "project": { "project_name": "YTAI_Edit", "fps": 25, "create_assembly_sequence": true }
}
```

---

## REVIEW Pipeline (6 шагов)

1. **Backup** — сохранение проекта
2. **Scan** — поиск клипов в `00_Source` бине → `clipMap` + получение `clipDurations` из Ingest секвенции
3. **Build** — `buildReviewSequence()` (V1 only, complement approach: Ingest минус Assembly, sorted by sourceFile + tc_in, colored by category)
4. **Markers** — Chapter маркеры по границам source files + per-segment маркеры с [CUT]/[ALT]/[SKIP] prefix
5. **Activate** — открытие секвенции + сохранение + валидация
6. **Captions** — `importCaptionsSrt()` — import `{project}_3_Review_captions.srt` в 02_Transcripts

### REVIEW — Ingest минус Assembly (complement approach)

Алгоритм Review v2: для каждого клипа вычисляет complement Assembly диапазонов в пределах [0, clipDuration]. Внутри complement сохраняет brief use=FALSE сегменты (с их metadata), а щели заполняет synthetic gap сегментами.

| | Assembly (`_2_Assembly`) | Review (`_3_Review`) |
|---|---|---|
| **Фильтр** | `use=TRUE AND block≠99` | Complement: `[0, clipDuration] \ Assembly` |
| **Сортировка** | block ASC, brief order | source_file ASC, tc_in ASC |
| **Цвета** | по блокам (из поля `color`) | по категории отказа (REVIEW_COLOR_MAP) |
| **Маркеры Chapter** | по блокам (is_chapter) | по границам source files |
| **Маркеры Segment** | speaker/transcript/notes | [CUT]/[ALT]/[SKIP] + speaker/transcript/notes |
| **Captions import** | Да (Step 6) | Да (Step 6) |

### Clip Durations

| Источник | Метод | Fallback |
|---|---|---|
| **UXP** | `getClipDurationsFromIngest()` — TrackItems из `{project}_1_Ingest` V1 | `getClipDurationsFromBrief()` — max(outSec) per sourceFile |
| **Python** | `load_clip_duration()` — per-clip transcript JSON `duration` field | `get_clip_durations_from_brief()` — max(tc_out) per source_file |

### Gap сегменты

Synthetic сегменты для участков complement, не покрытых brief:
- `_isGap: true`, `block: 0`, `priority: 1`, `use: false`
- Category = SKIP (Purple) — автоматически через `getReviewCategory()`
- `MIN_GAP_DURATION = 0.3s` — щели меньше пропускаются

### REVIEW_COLOR_MAP — цвета по категориям

| Категория | Условие | Clip Label | Marker Color | Значение |
|---|---|---|---|---|
| **CUT** | `block=99` | Red (6) | Red (1) | Явно вырезано LLM (шум, ошибки, повторы) |
| **ALT** | `use=FALSE`, `priority=2` | Yellow (15) | Yellow (4) | Альтернативный дубль, может пригодиться |
| **SKIP** | `use=FALSE`, block≠99, priority≠2 | Purple (8) | Magenta (2) | Не выбрано, без явной причины — кандидат на ревью |

### REVIEW sequence design — Positional Layout (Ingest mirror)

Review timeline имеет ту же длину, что и Ingest (все клипы end-to-end в алфавитном порядке). Assembly блоки = пустые места (gaps) на таймлайне. Редактор видит ГДЕ и СКОЛЬКО вырезано хронологически.

| Track | Содержание |
|-------|-----------|
| **V1** | Complement сегменты на абсолютных позициях (clipOffset + inSec), Assembly = пустые gaps |
| **A1** | Аудио из тех же клипов (наследуется автоматически) |

**Размещение:** `createOverwriteItemAction` на абсолютных позициях. Assembly НЕ ТРОНУТ.

**Clip Offsets:** `computeClipOffsets(clipDurations)` — клипы в алфавитном порядке:
```
C5402.MP4: offset=0,     duration=156.0
C5403.MP4: offset=156.0, duration=79.2
C5404.MP4: offset=235.2, duration=121.44
Total Ingest = 356.64s
```

**Timeline Position:** `seg._timelinePosition = clipOffsets[sourceFile] + inSec`

**Тайлинг:** Assembly + Review = Total Ingest duration (без пересечений, без пропусков)

### Два типа маркеров в Review

1. **Source file markers** — один на группу сегментов одного клипа
   - `name` = `"Source: C5402.MP4"` (имя source file)
   - `duration` = сумма длительностей review-сегментов этого клипа
   - `color` = из первого сегмента клипа (по REVIEW_COLOR_MAP)
   - `type` = Chapter

2. **Segment markers** — один на каждый сегмент
   - `name` = `"[CUT] seg_007"` / `"[ALT] seg_002"` / `"[SKIP] seg_008"`
   - `duration` = 0 (point marker)
   - `comment` = speaker | transcript | notes | cut reason
   - `color` = из REVIEW_COLOR_MAP по категории
   - `type` = Chapter

---

### Обязательные поля edit_brief.json для Assembly

| Поле | Тип | Назначение | Пример |
|------|-----|-----------|--------|
| `segment_id` | string | Уникальный ID сегмента | `"seg_001"` |
| `source_file` | string | Имя файла (ключ для clipMap) | `"C5403.MP4"` |
| `tc_in` | string | Timecode начала (MM:SS.s или HH:MM:SS.s) | `"00:00.0"` |
| `tc_out` | string | Timecode конца | `"01:11.6"` |
| `block` | number | Номер блока (99 = исключён) | `1` |
| `block_name` | string | Название блока (для маркеров) | `"Hook"` |
| `color` | string | Цвет блока (Green/Blue/Orange/Cyan/Yellow/Red/Magenta/Purple) | `"Green"` |
| `use` | string | `"TRUE"` = включить в Assembly | `"TRUE"` |
| `is_chapter` | string | `"TRUE"` = создать Chapter marker с duration на весь блок | `"TRUE"` |

### Поля color и is_chapter: как они работают

**`color`** — определяет цвет **И** клипа на таймлайне, **И** маркера блока:
- Клип: `LABEL_COLOR_INDEX[color]` → `createSetColorLabelAction(idx)` перед вставкой
- Маркер: `MARKER_COLOR_INDEX[color]` → `createSetColorByIndexAction(idx)` после создания
- Один source file может иметь разные цвета в разных блоках (per-segment application)
- Допустимые значения: `Green`, `Blue`, `Orange`, `Cyan`, `Yellow`, `Red`, `Magenta`, `Purple`

**`is_chapter`** — определяет где создаётся Chapter marker с duration:
- `"TRUE"` → создаётся маркер с `name=block_name`, `duration=длительность_всего_блока`
- Ставить на **первый** сегмент каждого блока
- Дополнительно для КАЖДОГО сегмента создаётся point marker (duration=0) с комментарием (speaker, transcript, broll_note, notes)

### ASSEMBLY sequence design

| Track | Содержание |
|-------|-----------|
| **V1** | USE=TRUE сегменты, sorted by block → brief order, pre-trimmed, per-segment colored |
| **A1** | Аудио из тех же клипов (наследуется автоматически) |

- Только `use=TRUE` и `block≠99`
- Сортировка: по block → brief order внутри блока (НЕ по tc_in)
- Цвета: per-segment, применяются **перед каждым insert** (не bulk)
- Маркеры: Chapter type, цвет = цвет блока (из поля `color`)

---

## Система цветов клипов

### Ключевое ограничение Adobe UXP API

> `createSetColorLabelAction` изменяет цвет **ProjectItem** в bin, но **существующие TrackItems на таймлайне НЕ обновляются**.
> Только **НОВЫЕ** TrackItems (при `createSequenceFromMedia` / `createInsertProjectItemAction`) наследуют текущий цвет.
> (Feature request DVAPR-4217788 для `trackItem.setColorLabel()`)

### Решение: per-segment color application

Цвет применяется к ProjectItem **непосредственно перед** каждой вставкой клипа на таймлайн. Это позволяет одному и тому же source file иметь разные цвета в разных блоках.

```
Порядок для каждого сегмента (clipActions.js — shared):
1. applyColorToItem(rawItem, seg.color)     ← меняет цвет ProjectItem в bin (Assembly)
   applyColorByIndex(rawItem, colorIdx)     ← меняет цвет по индексу (Review)
2. setSourceInOut(clipItem, inTime, outTime)  ← обрезка
3. createInsertProjectItemAction(rawItem)     ← вставка → наследует текущий цвет
4. clearSourceInOut(clipItem)                 ← сброс для повторного использования
```

### Пример с разделяемым файлом

```
seg_001: C5403.MP4 → set Green(13) → insert → TrackItem = Green ✓
seg_003: C5402.MP4 → set Blue(9)   → insert → TrackItem = Blue  ✓
seg_004: C5403.MP4 → set Blue(9)   → insert → TrackItem = Blue  ✓  (тот же файл, другой цвет!)
seg_005: C5404.MP4 → set Orange(7) → insert → TrackItem = Orange ✓
```

### LABEL_COLOR_INDEX — цвета клипов в bin/timeline (0-15)

| Имя | Индекс | Premiere Name |
|-----|--------|---------------|
| Green | 13 | GREEN |
| Blue | 9 | BLUE |
| Orange | 7 | MANGO |
| Cyan | 10 | TEAL |
| Yellow | 15 | YELLOW |
| Red | 6 | ROSE |
| Magenta | 11 | MAGENTA |
| Purple | 8 | PURPLE |

---

## Система маркеров

### Ключевые ограничения Adobe UXP API (подтверждено 2026-03-09)

> **`createAddMarkerAction(name, type, start, dur, comment)`** — параметр `type` **ИГНОРИРУЕТСЯ**.
> Маркеры всегда создаются как **Event** type, независимо от переданного значения.
> Для смены типа нужно использовать **`marker.createSetTypeAction(typeURI)`** отдельной транзакцией.

> **`marker.createSetColorAction()`** — **НЕ СУЩЕСТВУЕТ** в реальном API.
> Правильный метод: **`marker.createSetColorByIndexAction(colorIdx)`**.
> (Подтверждено через API discovery: `Marker methods: [..., createSetColorByIndexAction, ...]`)

### Реальные методы маркера (API discovery 2026-03-09)

```
Getters: getColor, getColorIndex, getComments, getDuration, getName, getUrl, getTarget, getType, getStart
Actions: createSetColorByIndexAction, createSetNameAction, createSetDurationAction, createSetTypeAction, createSetCommentsAction
```

### Реальные методы markersOwner (API discovery 2026-03-09)

```
getMarkers, createRemoveMarkerAction, createMoveMarkerAction, createAddMarkerAction
addEventListener, removeEventListener, dispatchEvent, constructor
```

### 4 транзакции маркеров (createAssemblyMarkers)

```
TRANSACTION 1: createAddMarkerAction × N       ← создать все маркеры (Event type по умолчанию)
     ↓ (если batch fail → fallback: individual markers)
TRANSACTION 2: markersOwner.getMarkers()        ← прочитать созданные маркеры
TRANSACTION 3: createSetColorByIndexAction × N  ← покрасить маркеры (отдельно!)
TRANSACTION 4: createSetTypeAction × N          ← сменить Event → Chapter (отдельно!)
```

Каждая транзакция обёрнута в try/catch. Если транзакция 3 или 4 падает — маркеры остаются (просто белые Event вместо цветных Chapter).

### MARKER_COLOR_INDEX — цвета маркеров (0-7, другая палитра!)

| Имя | Индекс |
|-----|--------|
| Green | 0 |
| Red | 1 |
| Magenta | 2 |
| Orange | 3 |
| Yellow | 4 |
| Blue | 6 |
| Cyan | 7 |

> Палитра маркеров (0-7) **ОТЛИЧАЕТСЯ** от палитры клипов (0-15).
> Нет White (index 5 отсутствует). Typo "MAGNETA" в реальном Premiere API.

### Типы маркеров

| Константа | Значение | Назначение |
|-----------|----------|-----------|
| `MARKER_TYPE_CHAPTER` | `'com.adobe.premiereMarkers.chapter'` | Adobe URI для создания/установки Chapter |
| `MARKER_TYPE_COMMENT` | `'com.adobe.premiereMarkers.comment'` | Adobe URI для создания/установки Comment |
| `ppro.Marker.MARKER_TYPE_CHAPTER` | `"Chapter"` | **Display name** — НЕ для API! |

### Два типа маркеров в Assembly

1. **Block markers** — один на блок, с `is_chapter="TRUE"` в первом сегменте блока
   - `name` = `block_name` (например "Hook", "Government Vision")
   - `duration` = сумма длительностей всех сегментов блока
   - `color` = цвет блока (из `MARKER_COLOR_INDEX`)
   - `type` = Chapter (через `createSetTypeAction`)

2. **Segment markers** — один на каждый сегмент с комментарием
   - `name` = `segment_name` или `segment_id`
   - `duration` = 0 (point marker)
   - `comment` = speaker | transcript | broll_note | notes
   - `color` = цвет сегмента (из `MARKER_COLOR_INDEX`)
   - `type` = Chapter (через `createSetTypeAction`)

### Cast: когда нужен

| Операция | Cast нужен? | Объект |
|----------|------------|--------|
| `createSetColorLabelAction` | НЕТ | raw ProjectItem |
| `createSetInOutPointsAction` | ДА | ClipProjectItem.cast() |
| `createClearInOutPointsAction` | ДА | ClipProjectItem.cast() |
| `createInsertProjectItemAction` | НЕТ | raw ProjectItem |
| `createOverwriteItemAction` | НЕТ | raw ProjectItem (Review: positional overwrite) |
| `createSetColorByIndexAction` | НЕТ | Marker object |
| `createSetTypeAction` | НЕТ | Marker object |

---

## Вертикальные зависимости (порядок выполнения)

### Внутри ASSEMBLY Pipeline

```
buildAssembly() [index.js]
│
├─ Step 1: project.save()
│
├─ Step 2: validateIngestState() [projectScanner.js]
│  ├─ findSourceBin()        ← ищет "00_Source" в проекте
│  ├─ buildClipMap()          ← сканирует bin → { filename: ProjectItem }
│  └─ validateClips()         ← все source_file из brief найдены?
│
├─ Step 3: buildAssemblySequence() [assemblyBuilder.js]
│  ├─ sortSegments()          ← block order, brief order внутри блока
│  ├─ cleanExistingSequence() ← удалить старую секвенцию
│  ├─ FOR EACH segment:
│  │   ├─ applyColorToItem()      ← цвет ПЕРЕД вставкой (per-segment!)
│  │   ├─ setSourceInOut()        ← обрезка (cast required)
│  │   ├─ insert (first: createSequenceFromMedia, rest: createInsertProjectItemAction)
│  │   └─ clearSourceInOut()      ← сброс для повторного использования
│  └─ V1 verification            ← read back TrackItems
│
├─ Step 4: createAssemblyMarkers() [index.js]
│  ├─ ppro.Markers.getMarkers(seq)  ← static API (единственный рабочий способ!)
│  ├─ TRANSACTION 1: createAddMarkerAction × N       ← создать маркеры (Event по умолчанию)
│  ├─ markersOwner.getMarkers()                      ← прочитать созданные маркеры
│  ├─ TRANSACTION 2: createSetColorByIndexAction × N  ← покрасить маркеры
│  └─ TRANSACTION 3: createSetTypeAction × N          ← Event → Chapter
│
├─ Step 5: setActiveSequence() + save() + validateAssemblyBuild()
│
└─ Step 6: importCaptionsSrt() [index.js]
   ├─ Ищет {project}_2_Assembly_captions.srt рядом с brief
   ├─ Если найден → project.importFiles([srtPath], true, transcriptsBin, false)
   └─ SRT появляется в 02_Transcripts bin → editor перетаскивает на Caption track
```

### Внутри Step 4: маркеры (порядок критически важен!)

```
1. Рассчитать blockInfo: { blockId → { name, startSec, durationSec, color } }
   ↓
2. Построить markerList: [{ name, type, startSec, durationSec, comment, markerColor }]
   ├─ Block markers (is_chapter=TRUE): name=blockName, dur=blockDuration
   └─ Segment markers: name=segmentName, dur=0 (point)
   ↓
3. TRANSACTION 1: createAddMarkerAction для каждого в markerList
   (type parameter ignored — все создаются как Event)
   ↓
4. markersOwner.getMarkers() → allMarkers[]
   ↓
5. Построить nameColorMap: { markerName → MARKER_COLOR_INDEX[color] }
   ↓
6. TRANSACTION 2: marker.createSetColorByIndexAction(colorIdx) для каждого
   ↓
7. TRANSACTION 3: marker.createSetTypeAction(MARKER_TYPE_CHAPTER) для каждого
```

### Внутри REVIEW Pipeline

```
buildReview() [index.js]
│
├─ Step 1: project.save()
│
├─ Step 2: validateIngestState() [projectScanner.js] + getClipDurationsFromIngest() [index.js]
│  ├─ findSourceBin()        ← ищет "00_Source" в проекте
│  ├─ buildClipMap()          ← сканирует bin → { filename: ProjectItem }
│  ├─ validateClips()         ← все source_file из brief найдены?
│  ├─ getClipDurationsFromIngest() ← TrackItems из _1_Ingest V1 → { filename: durationSec }
│  └─ fallback: getClipDurationsFromBrief() ← max(outSec) per sourceFile
│
├─ Step 3: buildReviewSequence(clipDurations) [reviewBuilder.js]
│  ├─ sortReviewSegments(segments, clipDurations) ← complement approach:
│  │   ├─ computeComplement()          ← [0, clipDur] \ Assembly ranges
│  │   ├─ subtractBriefFromRange()     ← complement \ brief use=FALSE
│  │   └─ createGapSegment()           ← synthetic gaps for uncovered areas
│  ├─ cleanExistingSequence()  ← удалить старую _3_Review секвенцию
│  ├─ computeClipOffsets(clipDurations) ← { offsets, ingestDuration }
│  ├─ seg._timelinePosition = clipOffsets[sourceFile] + inSec
│  ├─ FOR EACH segment (sorted by _timelinePosition):
│  │   ├─ getReviewCategory()       ← 'cut' | 'alt' | 'skip'
│  │   ├─ applyColorByIndex()       ← цвет из REVIEW_COLOR_MAP (per-segment!)
│  │   ├─ setSourceInOut()          ← обрезка (cast required)
│  │   ├─ overwrite (first: createSequenceFromMedia, rest: createOverwriteItemAction @_timelinePosition)
│  │   └─ clearSourceInOut()        ← сброс для повторного использования
│  └─ totalDuration = ingestDuration  ← длина = вся Ingest секвенция
│
├─ Step 4: createReviewMarkers() [index.js]
│  ├─ Source file markers: Chapter на границах клипов
│  ├─ Segment markers: [CUT]/[ALT]/[SKIP] + context
│  └─ 4 транзакции: create → read back → colors → types
│
├─ Step 5: setActiveSequence() + save() + validateReviewBuild()
│
└─ Step 6: importCaptionsSrt() [index.js]
   ├─ Ищет {project}_3_Review_captions.srt рядом с brief
   ├─ Если найден → project.importFiles([srtPath], true, transcriptsBin, false)
   └─ SRT появляется в 02_Transcripts bin → editor перетаскивает на Caption track
```

### INGEST → ASSEMBLY/REVIEW зависимость

```
INGEST Pipeline
├─ importFiles(paths) → создаёт ProjectItems в 00_Source bin
└─ Premiere Project State (00_Source bin содержит клипы)
    │
    ↓  (нет прямого import между модулями!)
    │
ASSEMBLY Pipeline                    REVIEW Pipeline
├─ findSourceBin() → "00_Source"     ├─ findSourceBin() → "00_Source"
├─ buildClipMap() → { filename: PI } ├─ buildClipMap() → { filename: PI }
└─ buildAssemblySequence()           └─ buildReviewSequence()
```

---

## Горизонтальные зависимости (внешние модули)

### Pipeline-уровень (между скриптами YTAI)

```
020101_transcribe
├── transcript.json ──→ 050202_claude_kb ──→ edit_brief.json ─┬─→ 050105 ASSEMBLY
├── ingest.json    ──→ 050105 INGEST                          └─→ 050105 REVIEW (обратный фильтр)
└── per_clip/*.json ──→ generate_assembly_captions.py
                         + edit_brief.json
                         ↓
                        {project}_2_Assembly_captions.srt ──→ 050105 ASSEMBLY (Step 6: auto-import)
                        {project}_3_Review_captions.srt   ──→ 050105 REVIEW   (Step 6: auto-import)

Filename = единый ключ:
  020101: clips[].filename = "C5402.MP4"
  050105 INGEST: importFiles() → 00_Source/"C5402.MP4"
  050202: segments[].source_file = "C5402.MP4"
  050105 ASSEMBLY: clipMap["C5402.MP4"]
  050105 REVIEW: clipMap["C5402.MP4"] (те же клипы, другие сегменты)

Color:
  050105 ASSEMBLY: segments[].color → LABEL_COLOR_INDEX → клип + MARKER_COLOR_INDEX → маркер
  050105 REVIEW: getReviewCategory() → REVIEW_COLOR_MAP → { labelIdx, markerIdx }
```

### Модуль-уровень (внутри 050105)

```
index.js (оркестратор)
├── ЧИТАЕТ: src/shared/constants  ← LABEL_COLOR_INDEX, MARKER_COLOR_INDEX, MARKER_TYPE_*, REVIEW_COLOR_MAP
├── ЧИТАЕТ: src/shared/logger     ← Logger
├── ЧИТАЕТ: src/shared/utils      ← fmtTime, escapeHtml
├── ЧИТАЕТ: src/assembly/briefParser      ← parseBrief()
├── ЧИТАЕТ: src/assembly/projectScanner   ← validateIngestState()
├── ЧИТАЕТ: src/assembly/assemblyBuilder  ← buildAssemblySequence()
└── ЧИТАЕТ: src/review/reviewBuilder      ← buildReviewSequence(), getReviewCategory(), computeClipOffsets()

assemblyBuilder.js
├── ЧИТАЕТ: premierepro (ppro)
├── ЧИТАЕТ: src/shared/clipActions  ← applyColorToItem, setSourceInOut, clearSourceInOut, cleanExistingSequence
└── НЕ ИМПОРТИРУЕТ: projectScanner, briefParser, index.js

reviewBuilder.js
├── ЧИТАЕТ: premierepro (ppro)
├── ЧИТАЕТ: src/shared/clipActions  ← applyColorByIndex, setSourceInOut, clearSourceInOut, cleanExistingSequence
├── ЧИТАЕТ: src/shared/constants    ← REVIEW_COLOR_MAP
└── НЕ ИМПОРТИРУЕТ: projectScanner, briefParser, assemblyBuilder, index.js

clipActions.js
├── ЧИТАЕТ: premierepro (ppro)
├── ЧИТАЕТ: src/shared/constants  ← LABEL_COLOR_INDEX
└── НЕ ИМПОРТИРУЕТ: assemblyBuilder, reviewBuilder

projectScanner.js
├── ЧИТАЕТ: premierepro (ppro)
└── НЕ ИМПОРТИРУЕТ: assemblyBuilder, reviewBuilder, briefParser

briefParser.js
└── НЕ ИМПОРТИРУЕТ: ничего (чистый парсер)
```

---

## UI Panel (index.html)

```
┌──────────────────────────────────────────┐
│                   Powered by RYA.AE      │  ← branding
├──────────── INGEST ──────────────────────│
│  ● Waiting for ingest JSON...            │  ← status dot + text
│  [Load Ingest JSON] [Debug Ingest]       │
│  Summary panel (hidden until load)       │
│  [Build Ingest] [Copy Logs Path]         │
│  Validation panel (green/yellow/red)     │
├──────────── ASSEMBLY ────────────────────│
│  ● Waiting for edit brief...             │
│  [Load Edit Brief] [Debug Assembly]      │
│  Summary panel (hidden until load)       │
│  [Build Assembly] [Apply Colors] [Logs]  │
│  Validation panel (green/yellow/red)     │
├──────────── REVIEW ──────────────────────│
│  ● Load edit brief first...             │
│  [Build Review] [Debug Review]           │
│  Validation panel (green/yellow/red)     │
├──────────── INGEST LOG ──────────────────│
│  [clear] Scrollable monospace log        │
├──────────── ASSEMBLY LOG ────────────────│
│  [clear] Scrollable monospace log        │
├──────────── REVIEW LOG ──────────────────│
│  [clear] Scrollable monospace log        │
└──────────────────────────────────────────┘
```

### Кнопки Assembly

| Кнопка | Действие |
|--------|----------|
| **Load Edit Brief** | File picker → parseBrief → показать summary |
| **Debug Assembly** | Auto-load DEBUG_BRIEF_PATH → buildAssembly() |
| **Build Assembly** | 6-step pipeline (scan → colors+build → markers → validate → captions) |
| **Apply Colors** | applyAssemblyColors() + buildAssembly() (полный ребилд для обновления таймлайна) |
| **Copy Logs Path** | Скопировать путь к папке логов в clipboard |

### Кнопки Review

| Кнопка | Действие |
|--------|----------|
| **Build Review** | 6-step pipeline (scan → build → markers → validate → captions) — доступна после загрузки edit brief |
| **Debug Review** | Auto-load DEBUG_BRIEF_PATH → buildReview() |

### Debug функции

- **Debug Ingest**: загружает hardcoded `DEBUG_INGEST_PATH` → clean → build → validate → save logs
- **Debug Assembly**: загружает hardcoded `DEBUG_BRIEF_PATH` → buildAssembly() (full pipeline)
- **Debug Review**: загружает hardcoded `DEBUG_BRIEF_PATH` → buildReview() (full pipeline)

---

## Обработка ошибок

### Per-segment (assemblyBuilder.js / reviewBuilder.js)

```
Для каждого сегмента (через clipActions.js):
├─ applyColorToItem/ByIndex() → try/catch → logger.debug (не прерывает build)
├─ setSourceInOut()            → try/catch → returns false (не прерывает build)
├─ Assembly: insert            → try/catch → fallback: createOverwriteItemAction
│  Review:  overwrite @pos     → try/catch → fallback: createInsertProjectItemAction
│                                          → try/catch → logger.error
└─ clearSourceInOut()          → try/catch → logger.debug (не прерывает build)
```

### Markers (index.js)

```
createAssemblyMarkers()
├─ ppro.Markers.getMarkers() → try/catch → return (non-fatal)
├─ TRANSACTION 1 (batch create) → try/catch → fallback: individual markers
│   └─ individual → try/catch → skip marker
├─ markersOwner.getMarkers() → read back created markers
├─ TRANSACTION 2 (colors) → try/catch → skip colors (markers remain white)
│   └─ per-marker → try/catch → skip + debug log with marker name
└─ TRANSACTION 3 (types) → try/catch → skip types (markers remain Event)
    └─ per-marker → try/catch → skip + debug log with marker name
```

### Diagnostics

- **readBack** — `rawItem.getColorLabelIndex()` после `createSetColorLabelAction` (в standalone applyAssemblyColors)
- **V1 verification** — read back всех TrackItems после build (position + duration + name)
- **API discovery** — логирование методов `markersOwner` и `marker[0]` для отладки
- **Marker color log** — `Marker colors: X/Y colored` (сколько маркеров покрашено)
- **Marker type log** — `Marker types: X/Y set to Chapter` (сколько маркеров сменили тип)

---

## Подтверждённые баги Adobe UXP API

| Баг | Описание | Workaround |
|-----|---------|-----------|
| `createSetColorLabelAction` не обновляет таймлайн | Только новые TrackItems наследуют цвет | Per-segment color application перед insert |
| `createAddMarkerAction` игнорирует `type` param | Все маркеры создаются как Event | `createSetTypeAction()` в отдельной транзакции |
| `createSetColorAction` не существует | Метод отсутствует в реальном API маркеров | `createSetColorByIndexAction()` — правильный метод |
| `ppro.Marker.MARKER_TYPE_CHAPTER` = display name | Возвращает "Chapter", не URI | Использовать URI: `'com.adobe.premiereMarkers.chapter'` |
| `MAGNETA` typo в MarkerColor | `ppro.Constants.MarkerColor.MAGNETA` = 2 | Маппинг в `MARKER_COLOR_INDEX` |
| Index 2 отсутствует в ProjectItemColorLabel | Пропуск в палитре клипов | Не использовать индекс 2 |
| Index 5 отсутствует в MarkerColor | Нет White в палитре маркеров | Не использовать индекс 5 |

---

## Тесты

```bash
npm test                    # все 122 тестов
npm run test:ingest         # только ingest
npm run test:assembly       # только assembly
npm run test:review         # только review
```

### Тестовые файлы

```
tests/
├── mocks/premierepro.js       ← полный мок Premiere Pro UXP API
├── ingest/                    ← тесты Ingest модулей
├── assembly/
│   ├── assemblyBuilder.test.js
│   ├── briefParser.test.js
│   ├── constants.test.js      ← включая REVIEW_COLOR_MAP
│   └── projectScanner.test.js
└── review/
    └── reviewBuilder.test.js  ← getReviewCategory, computeComplement, computeClipOffsets, subtractBriefFromRange, createGapSegment, sortReviewSegments (34 теста)
```

Тесты используют mock `tests/mocks/premierepro.js` — полный мок Premiere Pro UXP API:
- `MockClipProjectItem` — createSetColorLabelAction, createSetInOutPointsAction, getColorLabelIndex
- `MockSequence` — getVideoTrack, getMarkers (→ MockMarkersOwner)
- `MockMarkersOwner` — createAddMarkerAction, getMarkers (→ MockMarker[])
- `MockMarker` — createSetColorByIndexAction, createSetTypeAction, createSetNameAction, getName, getType, getColor, getColorIndex
- `MockProject` — lockedAccess, executeTransaction, createSequenceFromMedia
- `MockSequenceEditor` — createInsertProjectItemAction, createOverwriteItemAction

---

## Требования

- Adobe Premiere Pro 25.6.0+
- UXP Manifest Version 5
- Node.js 18+ (для тестов)
