# YTCR — Структура проекта v3.0

```
YTCR/
│
├── _channel/                                       <- общие ресурсы канала
│   ├── LUTs/
│   ├── templates/
│   └── assets/
│
│
├── YTCR01_Arty_Dzis/
│   │
│   ├── YTCR01_Arty_Dzis.gdoc
│   │
│   │
│   ├── 01_Media/                                   <- ВСЁ ДЛЯ МОНТАЖА
│   │   │
│   │   ├── Source/                                 <- ПАЙПЛАЙН СОЗДАЁТ
│   │   │   │
│   │   │   ├── Video/                             <- MP4 с камеры
│   │   │   │   ├── 20260228_Studio/               <- день 1
│   │   │   │   │   └── FX3/                       <- 161 MP4
│   │   │   │   └── 20260302_Desert/               <- день 2
│   │   │   │       ├── FX3/                       <- 155 MP4
│   │   │   │       └── GoPro/                     <- 42 файла
│   │   │   │
│   │   │   ├── Audio/                             <- DJI синхр. WAV
│   │   │   │   ├── {clip}_TX01.wav
│   │   │   │   └── {clip}_TX02.wav
│   │   │   │
│   │   │   ├── Transcription/                     <- транскрипция
│   │   │   │   ├── {project}_transcript.json
│   │   │   │   ├── {project}_transcript.xlsx
│   │   │   │   ├── {project}_transcript.srt
│   │   │   │   ├── speakers.json
│   │   │   │   ├── diarization.json
│   │   │   │   ├── clip_offsets.json
│   │   │   │   ├── meta.json
│   │   │   │   ├── {project}_FULL_AUDIO.wav
│   │   │   │   ├── {project}.mkv
│   │   │   │   └── per_clip/
│   │   │   │       └── {clip_id}/
│   │   │   │           ├── {clip}_transcript.json
│   │   │   │           ├── {clip}_premiere_transcript.json
│   │   │   │           ├── {clip}_captions.srt
│   │   │   │           ├── {clip}_audio.wav
│   │   │   │           ├── {clip}M01.XML          <- метаданные камеры
│   │   │   │           └── {clip}T01.JPG          <- превью камеры
│   │   │   │
│   │   │   ├── Setup/                             <- ЦЕНТР УПРАВЛЕНИЯ UXP
│   │   │   │   ├── {project}_ingest.json
│   │   │   │   ├── {project}_edit_brief.json
│   │   │   │   ├── {project}_edit_brief_review.html
│   │   │   │   ├── ScreenCues/
│   │   │   │   │   └── scr_001_full_overlay.png
│   │   │   │   └── logs/
│   │   │   │       ├── {project}_transcribe_*.log
│   │   │   │       └── {project}_sync_dji_audio_*.log
│   │   │   │
│   │   │   ├── LUT/                               <- цветокоррекция
│   │   │   │   └── SL3SG3Ctos709.cube
│   │   │   │
│   │   │   └── YTCR01_Arty_Dzis_Source.prproj     <- Ingest проект
│   │   │
│   │   ├── Assets/                                <- МОНТАЖНИК ДОБАВЛЯЕТ
│   │   │   ├── Music/
│   │   │   ├── SFX/
│   │   │   ├── Graphics/
│   │   │   ├── Stock/
│   │   │   └── Fonts/
│   │   │
│   │   └── YTCR01_Arty_Dzis.prproj               <- РАБОЧИЙ ПРОЕКТ
│   │
│   │
│   ├── 02_Exports/                                <- ФИНАЛЬНЫЕ РЕНДЕРЫ
│   │   ├── YTCR01_Arty_Dzis_v1.mp4
│   │   └── xml/
│   │
│   │
│   ├── 03_Shorts/                                 <- SHORTS
│   │   ├── short_01.mp4
│   │   ├── short_01_description.md
│   │   └── ...
│   │
│   │
│   ├── 04_Thumbnail/                              <- ПРЕВЬЮ
│   │   ├── prompts/
│   │   ├── drafts/
│   │   └── thumbnail.png
│   │
│   │
│   ├── YouTube/                                   <- ПАКЕТ ДЛЯ ЗАГРУЗКИ
│   │   ├── video.mp4
│   │   ├── thumbnail.png
│   │   ├── description.txt
│   │   ├── chapters.txt
│   │   └── tags.txt
│   │
│   │
│   └── 99_Pipeline/                               <- СЛУЖЕБНЫЕ ФАЙЛЫ
│       └── DJI_Audio/                             <- оригиналы DJI WAV
│           ├── TX01_MIC037_20260228_*.wav
│           └── TX02_MIC038_20260228_*.wav
│
│
├── YTCR02_Next_Guest/
│   ├── 01_Media/
│   ├── 02_Exports/
│   ├── 03_Shorts/
│   ├── 04_Thumbnail/
│   ├── YouTube/
│   └── 99_Pipeline/
│
└── ...
```

---

## Папки

### 01_Media — всё для монтажа

Контейнер для ВСЕГО, что нужно монтажнику. Разделён на:
- **Source/** — что пайплайн создаёт (видео, аудио, транскрипция, Setup)
- **Assets/** — что монтажник добавляет (музыка, sfx, графика)

Два проекта Premiere:
- `Source/{project}_Source.prproj` — после UXP Ingest (бины, клипы, LUT, captions)
- `{project}.prproj` — рабочая копия для монтажа

```bash
python transcribe_project.py \
  --project ".../YTCR01_Arty_Dzis" -y
```

### 02_Exports — финальные рендеры

Готовое видео. XML-экспорты из Premiere — в подпапке `xml/`.

### 03_Shorts — нарезка

Каждый Short — mp4 + описание.

### 04_Thumbnail — превью

Промпты для генерации, черновики, финальное превью.

### YouTube — пакет для загрузки

Финальное видео, превью, описание, главы, теги.

### 99_Pipeline — служебные файлы

Оригиналы DJI TX/MIC WAV (длинные 30-мин куски). Нужны только для sync скрипта.

---

## Именование

| Что | Формат | Пример |
|---|---|---|
| Эпизод | `{Channel}{NN}_{Hero}` | `YTCR01_Arty_Dzis` |
| Съёмочный день | `{YYYYMMDD}_{Location}` | `20260228_Studio` |
| Premiere (Ingest) | `{EpisodeName}_Source.prproj` | `YTCR01_Arty_Dzis_Source.prproj` |
| Premiere (рабочий) | `{EpisodeName}.prproj` | `YTCR01_Arty_Dzis.prproj` |
| Экспорт | `{EpisodeName}_v{N}.mp4` | `YTCR01_Arty_Dzis_v1.mp4` |
| Short | `short_{NN}.mp4` | `short_01.mp4` |

---

## Маппинг старых файлов

| Было | Стало |
|---|---|
| `20260228/FX3/` | `01_Media/Source/Video/20260228_Studio/FX3/` |
| `20260228/TX01/`, `TX02/` | `99_Pipeline/DJI_Audio/` |
| `20260228/transcription/` | `01_Media/Source/Transcription/per_clip/` |
| `20260302 Desert/` | `01_Media/Source/Video/20260302_Desert/` |
| `20260302 Desert/100GOPRO/` | `01_Media/Source/Video/20260302_Desert/GoPro/` |
| `LUTs/` | `_channel/LUTs/` |
| `ARTEM_STORY_v1.prproj` | `01_Media/YTCR01_Arty_Dzis.prproj` |
| `*.xml` | `02_Exports/xml/` |
| `Auto-Save/` | `01_Media/` (Premiere создаёт автоматически) |
