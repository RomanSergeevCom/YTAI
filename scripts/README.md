# YTAI Scripts — YouTube AI Pipeline v3.0

Автоматизация продакшена YouTube-видео: от сырых файлов камеры до готового таймлайна в Premiere Pro.

## Быстрый старт

```bash
# 1. Подготовка (init + extract audio + DJI sync)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT"

# 2. Транскрипция
source ~/YTAI/environment/.venv_transcribe/bin/activate
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
    --project "$PROJECT" -n 2 -y

# 3. Premiere: открыть UXP плагин → Select Project → Build Ingest → Build Assembly
```

## Структура

```
scripts/
├── run_pipeline.py                      ← главный скрипт (01_prepare)
│
├── 01_prepare/                          ← Фаза 1: подготовка
│   ├── 01_prepare_spec.md
│   ├── 0102_extract_audio/
│   │   ├── 0102_extract_audio.py        ← WAV из каждого MP4
│   │   └── 0102_extract_audio_spec.md
│   ├── 0103_sync_dji_audio/              ← legacy metadata-based sync
│   │   ├── 0103_sync_dji_audio.py
│   │   └── 0103_sync_dji_audio_spec.md
│   └── 0105_multiwindow_sync_dji/       ← текущий sync (multi-window correlation)
│       ├── 0105_multiwindow_sync_dji.py ← cross-correlation + spanning
│       └── 0105_multiwindow_sync_dji_spec.md
│
├── 02_transcribe/                       ← Фаза 2: транскрипция
│   └── 020101_transcribe/
│       ├── transcribe_project.py        ← Whisper + pyannote pipeline
│       ├── ingest_json.py               ← генерация ingest.json для UXP
│       └── 020101_transcribe_spec.md
│
├── 05_editing/                          ← Фаза 3: монтаж в Premiere
│   ├── 0500_uxp/                        ← UXP плагин Premiere Pro
│   │   ├── index.js                     ← оркестратор (Ingest/Assembly/Review/Screens)
│   │   ├── src/ingest/                  ← импорт медиа + таймлайн
│   │   ├── src/assembly/                ← сборка по pre_edit_brief.json
│   │   ├── src/review/                  ← complement (неиспользованное)
│   │   ├── src/screens/                 ← screen cues overlay
│   │   ├── src/shared/                  ← общие утилиты
│   │   ├── tests/                       ← 186 тестов (npm test)
│   │   └── 0500_uxp_spec.md
│   ├── 0501_brief/                      ← генерация pre_edit_brief.json (Claude)
│   └── 0504_screen_cues/                ← генерация PNG оверлеев
│
└── environment/                         ← виртуальные окружения
    └── .venv_transcribe/
```

## Запуск по фазам

### 01_prepare — Подготовка

```bash
# Полный pipeline (init → extract audio → DJI sync)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT"

# Только отдельные стадии
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only init
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only extract_audio
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only sync_dji

# DJI sync напрямую (multi-window cross-correlation)
python ~/YTAI/scripts/01_prepare/0105_multiwindow_sync_dji/0105_multiwindow_sync_dji.py \
    --project "$PROJECT"

# Dry run
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --dry-run
```

**Вход:** Папка с MP4 + (опционально) DJI WAV в `99_Pipeline/DJI_Audio/`
**Выход:** v3.0 структура с `Source/Video/`, `Source/Audio/`, extracted WAVs

### 02_transcribe — Транскрипция

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Полная транскрипция
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
    --project "$PROJECT" -n 2 -y

# Только ingest.json (перегенерация)
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
    --project "$PROJECT" --stages 6

# Dry run
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
    --project "$PROJECT" --dry-run
```

**Вход:** v3.0 структура после prepare
**Выход:** transcript.json, SRT, XLSX, ingest.json, premiere_transcript.json

### 05_editing — Premiere Pro

```bash
# UXP плагин — запускается из Premiere Pro
# 1. Открыть .prproj
# 2. Window → Extensions → YTAI
# 3. Select Project Folder → Build Ingest → Build Assembly

# Screen Cues PNGs (перед Build Screen Cues)
python ~/YTAI/scripts/05_editing/0504_screen_cues/generate_screen_cues_png.py \
    --brief "$PROJECT/01_Media/Source/Setup/{CODE}_pre_edit_brief.json"

# Тесты UXP
cd ~/YTAI/scripts/05_editing/0500_uxp && npm test
```

**Вход:** ingest.json (из transcribe), pre_edit_brief.json (из Claude/0501_brief)
**Выход:** Premiere секвенции (Ingest, Assembly, Review, Screen Cues)

## Scene-aware проекты (v1.2.0+)

Если видео организованы в scene-папки (`01_Interview/`, `02_Car/`, `03_Coffee/` внутри `Source/Video/`):

- **DJI sync** → Audio зеркалит структуру Video + XML с N sequences
- **ingest.json** → клипы получают поле `scene`
- **UXP Ingest** → создаёт отдельную секвенцию на каждую сцену
- **Flat проекты** → всё работает как раньше (backward compatible)

## Зависимости

| Зависимость | Установка | Используется |
|-------------|-----------|-------------|
| Python 3.11+ | — | Все скрипты |
| ffmpeg / ffprobe | `brew install ffmpeg` | 01_prepare, 02_transcribe |
| whisper (large-v3) | pip (venv_transcribe) | 02_transcribe |
| pyannote.audio | pip (venv_transcribe) | 02_transcribe |
| torch (MPS) | pip (venv_transcribe) | 02_transcribe |
| Node.js 18+ | — | 05_editing тесты |
| Premiere Pro 25.6+ | — | 05_editing UXP |

## Спецификации

| Файл | Описание |
|------|----------|
| `01_prepare/01_prepare_spec.md` | Фаза подготовки: init, extract, DJI sync |
| `01_prepare/0102_extract_audio/0102_extract_audio_spec.md` | Извлечение аудио |
| `01_prepare/0103_sync_dji_audio/0103_sync_dji_audio_spec.md` | Синхронизация DJI |
| `02_transcribe/020101_transcribe/020101_transcribe_spec.md` | Транскрипция + ingest |
| `05_editing/0500_uxp/0500_uxp_spec.md` | UXP плагин Premiere |
