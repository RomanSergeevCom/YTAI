# 01_prepare — Specification v1.0.0

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

Стадии выполняются последовательно. DJI sync — опциональная (требует `--tz-offset`).

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
# Полная фаза prepare
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare

# С DJI sync
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare --tz-offset 4

# Dry run
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only prepare --dry-run

# Отдельные стадии
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only init
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only extract_audio
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only sync_dji --tz-offset 4
```

## Выходная структура

```
{project}/
├── 01_Media/
│   ├── {project}.prproj
│   ├── Assets/                          Music/ SFX/ Graphics/ Stock/ Fonts/
│   └── Source/
│       ├── {project}_Source.prproj
│       ├── Video/                       ← MP4 из корня проекта
│       ├── Audio/                       ← синхронизированные DJI WAV (после sync_dji)
│       ├── LUT/                         ← .cube из SD-карты
│       ├── Transcription/
│       │   ├── {project}_FULL_AUDIO.wav ← конкатенация всех клипов
│       │   └── per_clip/
│       │       └── {clip}/
│       │           ├── {clip}_AUDIO.wav ← 48kHz stereo WAV
│       │           └── {clip}M01.XML    ← XML-сайдкар камеры
│       └── Setup/
│           └── logs/                    ← логи pipeline
├── 99_Pipeline/DJI_Audio/               ← сырые DJI WAV (TX##_MIC###_*)
├── 02_Exports/
├── 03_Shorts/
├── 04_Thumbnail/
├── YouTube/
└── {project}.gdoc
```

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
    │
    └── (all prepared)              → 02_transcribe (следующая фаза)
```

## Логи

```
01_Media/Source/Setup/logs/
├── {project}_run_pipeline_{YYYYMMDD_HHMMSS}.log    ← основной лог
├── {project}_extract_audio_{YYYYMMDD_HHMMSS}.log   ← лог извлечения аудио
└── {project}_sync_dji_audio_{YYYYMMDD_HHMMSS}.log  ← лог DJI синхронизации
```

## Опции

| Флаг | Описание |
|------|----------|
| `--type production` | Полная структура (по умолчанию) |
| `--type footage` | Минимальная (без Assets, Shorts и т.д.) |
| `--tz-offset N` | Часовой пояс для DJI sync (часы от UTC) |
| `--force` | Перезаписать существующие файлы |
| `--dry-run` | Только показать план действий |

## Консольный вывод

После завершения фазы выводится ASCII-дерево проекта (`print_project_tree`), показывающее:
- Иерархию папок v3.0
- Количество и размер файлов в каждой папке
- Содержимое per_clip/ (AUDIO.wav + XML)
- Предупреждение `⚠ needs --tz-offset` для Audio/ при наличии DJI файлов
