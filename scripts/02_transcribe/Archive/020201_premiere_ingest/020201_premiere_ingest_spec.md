# 020201_premiere_ingest — Спецификация

## Обзор

UXP-плагин для Adobe Premiere Pro. Загружает ingest JSON (сгенерированный 020101_transcribe),
создаёт бины, импортирует видео, строит один таймлайн, импортирует SRT и Premiere transcript JSON.

**Панель:** YTAI Ingest
**ID:** com.ytai.ingest.panel
**Версия:** 1.0.0
**Premiere Pro:** >= 25.1.0, UXP Manifest v5

---

## Установка

1. Открыть Premiere Pro > Developer Workspace
2. Load Plugin > выбрать папку `020201_premiere_ingest/`
3. Панель "YTAI Ingest" появится в меню Window > Extensions

---

## Workflow

```
1. Запустить транскрибацию (020101_transcribe)
   → Генерирует {project}_ingest.json внутри {project}_transcription/

2. Открыть Premiere Pro → создать или открыть проект

3. Панель "YTAI Ingest":
   → Load Ingest JSON → выбрать {project}_ingest.json
   → Проверить summary (клипы, resolution, длительность)
   → Build Timeline

4. Результат:
   - 3 бина: 00_Source, 01_Sequence, 02_Transcripts
   - 1 sequence с видео на V1/A1
   - SRT и premiere transcript JSON в бине 02_Transcripts

5. Вручную: Text panel > Import Transcript (UXP API не поддерживает)
```

---

## Pipeline (4 шага)

### Step 1: Create bins

Модуль: `src/binManager.js`

3 бина в корне проекта (в одной транзакции):

| Бин | Назначение |
|---|---|
| `00_Source` | Видеофайлы |
| `01_Sequence` | Таймлайн |
| `02_Transcripts` | SRT, premiere transcript JSON |

### Step 2: Import media + build sequence

Модуль: `src/timelineBuilder.js`

1. `project.importFiles()` — импорт всех видео из `ingest.clips[].path` в `00_Source`
2. `project.createSequenceFromMedia()` из первого клипа — наследует resolution/FPS
3. Для каждого клипа: `createInsertProjectItemAction` на V1/A1 (track 0/0)
4. Клипы размещаются последовательно, целиком, без in/out точек
5. Имя sequence: `{project_name} — Ingest`

### Step 3: Import transcripts

Модуль: `src/transcriptImporter.js`

1. SRT из `ingest.files.transcript_srt` → бин `02_Transcripts`
2. Per-clip premiere transcript JSON из `ingest.clips[].premiere_transcript` → бин `02_Transcripts`
3. Batch import через `project.importFiles()`, fallback — по одному файлу

**Ограничение UXP API:** программно привязать transcript к клипу нельзя.
Пользователь вручную через Text panel > Import Transcript.

### Step 4: Activate sequence

1. `project.setActiveSequence()` + `project.openSequence()`
2. Авто-сохранение debug bundle (log + snapshot + копия ingest JSON)

---

## Ingest JSON контракт

Входной файл: `{transcription_dir}/{project}_ingest.json`

```json
{
    "version": "1.0",
    "type": "ingest",
    "project_name": "Interview",
    "created_at": "2026-03-08T12:00:00Z",
    "media": {
        "width": 3840,
        "height": 2160,
        "fps": 25.0,
        "sample_rate": 48000
    },
    "clips": [
        {
            "clip_id": "C5402",
            "filename": "C5402.MP4",
            "path": "/abs/Interview/C5402.MP4",
            "duration": 156.0,
            "offset": 0.0,
            "premiere_transcript": "/abs/.../C5402_premiere_transcript.json"
        }
    ],
    "files": {
        "transcript_json": "/abs/.../Interview_transcript.json",
        "transcript_srt": "/abs/.../Interview_transcript.srt",
        "transcript_xlsx": "/abs/Interview_transcript.xlsx"
    },
    "source_folder": "/abs/Interview"
}
```

Обязательные поля: `project_name`, `clips[]` (с `clip_id`, `filename`, `path`, `duration`), `media`, `files`.

---

## UI

Тёмная тема (CSS variables), Spectrum sp-button компоненты.

### Секции

1. **Log** — монширный лог с цветами (info=голубой, warn=оранжевый, error=красный), кнопка clear
2. **Load Ingest JSON** — кнопка загрузки, info о файле, summary panel (project, resolution, clips, duration)
3. **Build Timeline** — progress bar, кнопка Build (disabled до загрузки), кнопка Save Log
4. **Status** — точка-индикатор (зелёный=ready, оранжевый=waiting, красный=error)

---

## Модули

### ingestLoader.js

- `parseIngest(jsonString)` — парсинг + валидация всех обязательных полей
- `getUniqueSourceFiles(ingest)` — дедупликация путей к видео
- `generateSummary(ingest)` — текстовая сводка для UI

### binManager.js

- `BIN_NAMES` — константы имён бинов
- `createBinStructure(project, logger)` — создание 3 бинов в транзакции

### timelineBuilder.js

- `buildIngestSequence(project, ingest, sourceBin, sequenceBin, logger)` — полный пайплайн
- `findProjectItemByName(project, name)` — BFS поиск по бинам

### transcriptImporter.js

- `importTranscripts(project, ingest, transcriptsBin, logger)` — импорт SRT + premiere transcript JSON

### logger.js

- `Logger` класс — in-memory буфер, UI callback, file export
- `setIngestInfo()` / `setProjectInfo()` — метаданные для отчёта
- `saveDebugBundle()` — log.txt + debug_snapshot.json + ingest_copy.json
- `saveLogToDataFolder()` — только лог

### utils.js

- `parseTimecode()`, `secondsToTimecode()`, `trackToIndex()`, `colorToLabel()`
- Скопирован из 050205 без изменений

---

## Отличия от 050205 (edit brief)

| | 020201 (Ingest) | 050205 (Edit Brief) |
|---|---|---|
| Входной файл | `_ingest.json` | `_edit_brief.json` |
| Бинов | 3 | 5 |
| Sequences | 1 (один таймлайн) | Много (per segment) |
| Клипы | Целиком (без in/out) | С in/out точками |
| Маркеры | Нет | Да (цветные) |
| SRT импорт | Да | Нет |
| Premiere transcript | Импорт в бин | Не используется |

---

## Тесты

    cd scripts/02_transcribe/020201_premiere_ingest
    npm test

31 тест, 5 suites:
- `ingestLoader.test.js` — 20 тестов (парсинг, валидация, summary, ошибки)
- `binManager.test.js` — 11 тестов (константы, создание бинов, транзакции)

Mock: `tests/mocks/premierepro.js` — полный мок Premiere Pro UXP API с CallRecorder.
Fixture: `tests/fixtures/sample_ingest.json` — 3 клипа, 3840x2160 @ 25fps.

---

## Структура проекта

```
020201_premiere_ingest/
├── manifest.json                    # UXP манифест
├── package.json                     # npm package
├── index.html                       # UI панель
├── index.js                         # Оркестратор
├── src/
│   ├── ingestLoader.js              # Парсер ingest JSON
│   ├── binManager.js                # 3 бина
│   ├── timelineBuilder.js           # Sequence + клипы (без in/out)
│   ├── transcriptImporter.js        # Импорт SRT + transcript JSON
│   ├── logger.js                    # Логирование
│   └── utils.js                     # Утилиты
├── tests/
│   ├── fixtures/
│   │   └── sample_ingest.json       # Тестовые данные
│   ├── mocks/
│   │   └── premierepro.js           # Мок Premiere API
│   ├── ingestLoader.test.js         # 20 тестов
│   └── binManager.test.js           # 11 тестов
└── 020201_premiere_ingest_spec.md   # Эта спецификация
```

---

## Debug bundle

При завершении build (успех или ошибка) автоматически сохраняется:

```
<pluginFolder>/logs/debug_<project>_<timestamp>/
├── log.txt                # Полный лог сессии
├── debug_snapshot.json    # JSON со всем состоянием
├── ingest_copy.json       # Копия загруженного ingest
└── <project>.prproj       # Копия проекта (если доступен)
```
