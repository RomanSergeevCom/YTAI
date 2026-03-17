# 01_prepare — Specification v1.1.0

Фаза подготовки проекта: создание структуры папок, организация медиафайлов, извлечение аудио, синхронизация DJI.

**Вход:** Папка проекта с сырыми файлами камеры (MP4, XML, WAV, .cube) в корне или подпапках
**Выход:** Полная v3.0 структура с организованными файлами, готовая к транскрипции

---

## Назначение

Фаза Prepare — первый этап YTAI Pipeline (`run_pipeline.py`). Принимает "сырой" проект (файлы с SD-карты, скопированные в папку) и превращает его в организованную v3.0 структуру с извлечённым аудио.

## Стадии

| # | ID | Стадия | Скрипт | Описание |
|---|-----|--------|--------|----------|
| 0101 | `init` | Init folders | встроен в `run_pipeline.py` | Создание папок + организация файлов |
| 0102 | `extract_audio` | Extract audio | `0102_extract_audio.py` | WAV из каждого клипа + FULL_AUDIO |
| 0103 | `sync_dji` | DJI sync | `0103_sync_dji_audio.py` | Синхронизация DJI WAV с видеоклипами |

Стадии выполняются последовательно. DJI sync — опциональная (пропускается если нет DJI файлов). Timezone определяется автоматически.

## Файлы

```
scripts/01_prepare/
├── 01_prepare_spec.md                    ← этот файл
├── 0101_init_folders/
│   └── 0101_init_folders_spec.md
├── 0102_extract_audio/
│   ├── 0102_extract_audio.py
│   └── 0102_extract_audio_spec.md
├── 0103_sync_dji_audio/
│   ├── 0103_sync_dji_audio.py
│   └── 0103_sync_dji_audio_spec.md
└── Archive/
    └── 01_concat_clips.py               ← legacy, не используется
```

## Запуск

```bash
# Полная фаза prepare (timezone auto-detected)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare

# С явным timezone для DJI sync
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare --tz-offset 4

# Dry run
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare --dry-run

# Отдельные стадии
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only init
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only extract_audio
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only sync_dji

# Напрямую (без pipeline)
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT"
python ~/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py --project "$PROJECT"
```

## Выходная структура

### Flat проект (без scene-папок)

```
{project}/
├── 01_Media/
│   ├── {project}.prproj
│   ├── Assets/                          Music/ SFX/ Graphics/ Stock/ Fonts/
│   └── Source/
│       ├── {project}_Source.prproj
│       ├── Video/                       ← MP4 из корня проекта
│       ├── Audio/                       ← синхронизированные DJI WAV (после sync_dji)
│       │   ├── {clip}_TX01.wav
│       │   └── ...
│       ├── LUT/                         ← .cube из SD-карты
│       ├── Transcription/
│       │   ├── {CODE}_FULL_AUDIO.wav    ← конкатенация всех клипов
│       │   ├── captions/                ← *_captions.srt файлы
│       │   ├── transcripts/             ← *_transcript.srt файлы
│       │   └── per_clip/
│       │       └── {clip}/
│       │           ├── {clip}_AUDIO.wav ← 48kHz stereo WAV
│       │           └── {clip}M01.XML    ← XML-сайдкар камеры
│       └── Setup/
│           ├── {CODE}_ingest.json       ← Premiere UXP
│           ├── {CODE}_pre-edit_brief.json ← бриф для Assembly
│           ├── {CODE}_transcript.json   ← транскрипт
│           ├── {CODE}_transcript.xlsx   ← Excel транскрипт
│           ├── screen_cues/             ← PNG оверлеи
│           ├── pre-edit_versions/       ← история версий брифа
│           └── logs/                    ← логи pipeline
├── 99_Pipeline/DJI_Audio/               ← сырые DJI WAV (TX##_MIC###_*)
├── 02_Exports/
├── 03_Shorts/
├── 04_Thumbnail/
├── YouTube/
└── {project}.gdoc
```

### Scene-aware проект (v1.1.0)

Если видео организованы в scene-папки (`^\d{2}_`), структура зеркалится:

```
{project}/
├── 01_Media/Source/
│   ├── Video/
│   │   ├── 01_Interview/              ← сцена 1
│   │   │   ├── RYA-ZVE1-1180.MP4
│   │   │   └── ...
│   │   ├── 02_Car/                    ← сцена 2
│   │   │   └── ...
│   │   └── 03_Coffee/                 ← сцена 3
│   │       └── ...
│   ├── Audio/
│   │   ├── 01_Interview/              ← DJI аудио зеркалит Video
│   │   │   ├── RYA-ZVE1-1180_TX01.wav
│   │   │   └── ...
│   │   ├── 02_Car/
│   │   │   └── ...
│   │   └── 03_Coffee/
│   │       ├── RYA-ZVE1-1167_TX01.wav ← TX01 (mic 1)
│   │       ├── RYA-ZVE1-1167_TX02.wav ← TX02 (mic 2)
│   │       └── ...
│   └── Setup/
│       └── logs/
└── ...
```

Scene-папки определяются regex `^\d{2}_` из `Source/Video/`.

Используйте `--type footage` для минимальной структуры (без Assets, Shorts, Thumbnail, YouTube, .gdoc).

## Связи

```
SD-карта / корень проекта
    │
    ├── *.MP4, *.MOV                → 0101 init → Source/Video/
    ├── *.XML (sidecars)            → 0101 init → per_clip/{clip}/
    ├── TX##_MIC###_*.wav (DJI)     → 0101 init → 99_Pipeline/DJI_Audio/
    ├── *.cube (LUT)                → 0101 init → Source/LUT/
    │
    ├── Source/Video/*.MP4          → 0102 extract → per_clip/{clip}/{clip}_AUDIO.wav
    │                                              → {project}_FULL_AUDIO.wav
    │
    ├── Source/Video/ + DJI_Audio/  → 0103 sync   → Source/Audio/{clip}_TX{N}.wav
    │                                              → Source/Audio/{scene}/{clip}_TX{N}.wav (scene-aware)
    │                                              → 99_Pipeline/DJI_Audio/{CODE}_dji_sync_check.xml (1 or N sequences)
    │
    └── (all prepared)              → 02_transcribe (следующая фаза)
```

## Логи

```
01_Media/Source/Setup/logs/
├── {project_name}_run_pipeline_{YYYYMMDD_HHMMSS}.log    ← основной лог (полное имя)
├── {project_name}_extract_audio_{YYYYMMDD_HHMMSS}.log   ← лог извлечения аудио
└── {project_name}_sync_dji_audio_{YYYYMMDD_HHMMSS}.log  ← лог DJI синхронизации
```

## Опции

| Флаг | Описание |
|------|----------|
| `--type production` | Полная структура (по умолчанию) |
| `--type footage` | Минимальная (без Assets, Shorts и т.д.) |
| `--tz-offset N` | Часовой пояс для DJI sync (часы от UTC). Если не указан — auto-detect |
| `--force` | Перезаписать существующие файлы |
| `--dry-run` | Только показать план действий |

## Консольный вывод

После завершения фазы выводится ASCII-дерево проекта (`print_project_tree`), показывающее:
- Иерархию папок v3.0
- Количество и размер файлов в каждой папке
- Содержимое per_clip/ (AUDIO.wav + XML)
- Предупреждение `⚠ needs --tz-offset` для Audio/ при наличии DJI файлов
