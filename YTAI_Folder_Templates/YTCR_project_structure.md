# YTCR — Структура проекта

```
YTCR/
│
├── _channel/                                       ← общие ресурсы канала
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
│   ├── 01_Source/                                  ← ИСХОДНИКИ + ТРАНСКРИПЦИЯ
│   │   │
│   │   ├── 20260228_Studio/                        ← день 1
│   │   │   ├── FX3/                                ← 161 MP4
│   │   │   ├── TX01/                               ← петличка A
│   │   │   ├── TX02/                               ← петличка B
│   │   │   ├── 20260228_Studio_transcript.xlsx     ← скрипт
│   │   │   ├── 20260228_Studio.prproj              ← скрипт: preview
│   │   │   └── 20260228_Studio_transcription/      ← скрипт: полная транскрипция
│   │   │       ├── full_audio.wav
│   │   │       ├── clip_offsets.json
│   │   │       ├── diarization.json
│   │   │       ├── speakers.json
│   │   │       ├── combined_transcript.json
│   │   │       ├── meta.json
│   │   │       ├── lut/
│   │   │       └── per_clip/
│   │   │           ├── C5089/ ... C5251/
│   │   │
│   │   └── 20260302_Desert/                        ← день 2
│   │       ├── FX3/                                ← 155 MP4
│   │       ├── GoPro/                              ← 42 файла
│   │       ├── TX02/
│   │       ├── 20260302_Desert_transcript.xlsx
│   │       ├── 20260302_Desert.prproj
│   │       └── 20260302_Desert_transcription/
│   │
│   │
│   ├── 02_Brief/                                   ← АНАЛИЗ + ПЛАН МОНТАЖА
│   │   ├── speaker_id.json
│   │   ├── topics.json
│   │   ├── content_rating.json
│   │   ├── edit_brief_v1.xlsx
│   │   ├── edit_brief_v1.json
│   │   ├── premiere_markers.json
│   │   ├── premiere_transcript.json
│   │   ├── chapters.txt
│   │   └── description.txt
│   │
│   │
│   ├── 03_Edit/                                    ← МОНТАЖ
│   │   ├── YTCR01_Arty_Dzis.prproj                ← основной проект Premiere
│   │   ├── YTCR01_Arty_Dzis.prin
│   │   ├── Auto-Save/
│   │   └── assets/                                 ← всё кроме исходников
│   │       ├── music/
│   │       ├── sfx/
│   │       ├── graphics/
│   │       ├── stock/
│   │       └── fonts/
│   │
│   │
│   ├── 04_Exports/                                 ← ФИНАЛЬНЫЕ РЕНДЕРЫ
│   │   ├── YTCR01_Arty_Dzis_v1.mp4
│   │   └── xml/
│   │
│   │
│   ├── 05_Shorts/                                  ← SHORTS
│   │   ├── short_01.mp4
│   │   ├── short_01_description.md
│   │   ├── short_02.mp4
│   │   └── ...
│   │
│   │
│   ├── 06_Thumbnail/                               ← ПРЕВЬЮ
│   │   ├── source_frames/
│   │   ├── prompts/
│   │   ├── drafts/
│   │   └── thumbnail.png
│   │
│   │
│   ├── YouTube/                                    ← ПАКЕТ ДЛЯ ЗАГРУЗКИ
│   │   ├── video.mp4
│   │   ├── thumbnail.png
│   │   └── shorts/
│   │
│   │
│   └── logs/                                       ← ЛОГИ СКРИПТОВ
│
│
├── YTCR02_Next_Guest/
│   ├── 01_Source/
│   ├── 02_Brief/
│   ├── 03_Edit/
│   ├── 04_Exports/
│   ├── 05_Shorts/
│   ├── 06_Thumbnail/
│   ├── YouTube/
│   └── logs/
│
└── ...
```

---

## Папки

### 01_Source — исходники + транскрипция

Всё что сняли. Каждый съёмочный день — подпапка (`20260228_Studio/`, `20260302_Desert/`). Внутри: MP4, WAV, и результаты скрипта транскрипции (xlsx, prproj, _transcription/). Скрипт запускается прямо на эту папку — ничего не перемещать.

```bash
python transcribe_project_v2.11.py \
  --project ".../YTCR01_Arty_Dzis/01_Source/20260228_Studio" -y
```

### 02_Brief — анализ + план монтажа

AI-анализ поверх транскрипций: кто говорит, о чём, что оставить. Агрегирует данные из всех съёмочных дней. Сюда же — маркеры для Premiere, субтитры, описание, главы.

### 03_Edit — монтаж

Premiere-проект и всё что нужно для монтажа **кроме исходников**: музыка, sfx, графика, стоковые кадры, шрифты. Исходники остаются в 01_Source — Premiere линкует их оттуда.

### 04_Exports — финальные рендеры

Готовое видео. Все стадии пройдены. XML-экспорты из Premiere — в подпапке `xml/`.

### 05_Shorts — нарезка

Отдельно от основного видео. Каждый Short — mp4 + описание.

### 06_Thumbnail — превью

Стоп-кадры, промпты для генерации, черновики, финальное превью.

### YouTube — пакет для загрузки

Финальное видео, финальное превью, Shorts — копии/линки из 04_Exports, 05_Shorts, 06_Thumbnail. Готово к загрузке в YouTube Studio.

### logs — логи скриптов

Логи транскрипции, AI-анализа, автоматизации.

---

## Именование

| Что | Формат | Пример |
|---|---|---|
| Эпизод | `{Channel}{NN}_{Hero}` | `YTCR01_Arty_Dzis` |
| Съёмочный день | `{YYYYMMDD}_{Location}` | `20260228_Studio` |
| Premiere (монтаж) | `{EpisodeName}.prproj` | `YTCR01_Arty_Dzis.prproj` |
| Premiere (preview) | `{DayName}.prproj` | `20260228_Studio.prproj` |
| Экспорт | `{EpisodeName}_v{N}.mp4` | `YTCR01_Arty_Dzis_v1.mp4` |
| Short | `short_{NN}.mp4` | `short_01.mp4` |

---

## Маппинг текущих файлов

| Сейчас | Куда |
|---|---|
| `20260228/FX3/` | `YTCR01_.../01_Source/20260228_Studio/FX3/` |
| `20260228/TX01/`, `TX02/` | `YTCR01_.../01_Source/20260228_Studio/TX01/`, `TX02/` |
| `20260228/transcription/` | `YTCR01_.../01_Source/20260228_Studio/...transcription/per_clip/` |
| `20260302 Desert/` | `YTCR01_.../01_Source/20260302_Desert/` |
| `20260302 Desert/100GOPRO/` | `YTCR01_.../01_Source/20260302_Desert/GoPro/` |
| `YTCR_transcription/*.xlsx` | удалить (дубликат) |
| `LUTs/` | `_channel/LUTs/` |
| `20260228/ARTEM_STORY_v1.prproj` + `.prin` | `YTCR01_.../03_Edit/` |
| `20260228/YTCR.prproj` + `.prin` | `YTCR01_.../03_Edit/` (backup) |
| `20260228/*.xml` | `YTCR01_.../04_Exports/xml/` |
| `20260228/Auto-Save/` | `YTCR01_.../03_Edit/Auto-Save/` |
