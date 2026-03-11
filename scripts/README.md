# YTAI Scripts — YouTube AI Pipeline

Автоматизация продакшена YouTube-видео для Connect Group Dubai.

## Структура

```
scripts/
├── 00_init/                   # Инициализация проекта
│   ├── 01_create_template.py
│   └── 02_apply_template.py
│
├── 01_prepare/                # Подготовка сырья
│   ├── 01_concat_clips.py
│   └── 02_extract_audio.py
│
├── 02_transcribe/             # Транскрипция ✅ ГОТОВО
│   └── 01_transcribe_project.py
│
├── 03_speaker_id/             # Идентификация спикеров ✅ ГОТОВО
│   ├── 00_process_all.py
│   ├── 01_extract_speakers.py
│   ├── 02_analyze_speakers.py
│   ├── 03_apply_names.py
│   ├── 04_split_clips.py
│   └── utils/
│
├── 04_video_analysis/         # Анализ видео (эмоции, B-roll)
│   ├── 01_extract_frames.py
│   ├── 02_detect_scenes.py
│   ├── 03_detect_emotions.py
│   ├── 04_detect_gestures.py
│   ├── 05_find_broll.py
│   └── 06_generate_visual_brief.py
│
├── 05_editing/                # Подготовка к монтажу
│   ├── 01_build_master_doc.py
│   ├── 02_chapters.py
│   ├── 03_highlights.py
│   ├── 04_export_premiere_xml.py
│   ├── 05_export_markers.py
│   └── 06_generate_edit_brief.py
│
├── 06_thumbnails/             # Превью + Тайтлы
│   ├── 01_title_generator.py
│   ├── 02_thumbnail_prompts.py
│   └── 03_compose.py
│
├── 07_shorts/                 # Shorts / Reels
│   ├── 01_find_moments.py
│   ├── 02_export_cuts.py
│   └── 03_generate_captions.py
│
└── 08_youtube/                # Подготовка к публикации
    ├── 01_description.py
    ├── 02_chapters.py
    └── 03_tags.py
```

## Полный Workflow

```bash
# 0. Создать проект
python 00_init/02_apply_template.py --target "/Volumes/RYA Blue/YT_Project"

# 1. Подготовка
python 01_prepare/01_concat_clips.py --project "..."
python 01_prepare/02_extract_audio.py --project "..."

# 2. Транскрипция
python 02_transcribe/01_transcribe_project.py --project "..." -n 2

# 3. Идентификация спикеров
python 03_speaker_id/00_process_all.py --project "..."

# 4. Анализ видео
python 04_video_analysis/01_extract_frames.py --project "..."
python 04_video_analysis/03_detect_emotions.py --project "..."

# 5. Подготовка к монтажу
python 05_editing/06_generate_edit_brief.py --project "..."

# 6. Превью
python 06_thumbnails/01_title_generator.py --project "..."

# 7. Shorts
python 07_shorts/01_find_moments.py --project "..."

# 8. YouTube
python 08_youtube/01_description.py --project "..."
```

## Статус реализации

| Папка | Статус |
|-------|--------|
| 00_init | ⏳ Перенести существующие скрипты |
| 01_prepare | ⏳ Перенести существующие скрипты |
| 02_transcribe | ✅ ГОТОВО |
| 03_speaker_id | ✅ ГОТОВО |
| 04_video_analysis | 📋 TODO |
| 05_editing | 📋 TODO |
| 06_thumbnails | 📋 TODO |
| 07_shorts | 📋 TODO |
| 08_youtube | 📋 TODO |

## Требования

```bash
# Python пакеты
pip install openai-whisper pyannote.audio torch requests openpyxl soundfile

# FFmpeg
brew install ffmpeg

# Ollama (для LLM)
brew install ollama
ollama pull llama3.3:70b-instruct-q4_K_M
```

## Быстрый старт

```bash
# Транскрипция
python 02_transcribe/01_transcribe_project.py --project "/path/to/project" -n 2

# Идентификация спикеров
python 03_speaker_id/00_process_all.py --project "/path/to/project" --no-pause
```

См. `QUICKSTART.md` для подробной документации.
