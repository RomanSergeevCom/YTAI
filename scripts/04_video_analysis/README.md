# 04_video_analysis — Анализ видео (визуальный)

## Скрипты

| Скрипт | Назначение |
|--------|------------|
| `01_extract_frames.py` | Извлечь ключевые кадры |
| `02_detect_scenes.py` | Смена сцен/локаций |
| `03_detect_emotions.py` | Эмоции (улыбки, удивление) |
| `04_detect_gestures.py` | Жесты, движения |
| `05_find_broll.py` | Кадры для B-roll |
| `06_generate_visual_brief.py` | Сводка визуального анализа |

## Вход → Выход
- `01_Raw/ProjectName.mkv`
- ↓
- `03_Analysis/frames/*.jpg`
- `03_Analysis/scenes.json`
- `03_Analysis/emotions.json`
- `03_Analysis/broll.json`
- `03_Analysis/VisualBrief.docx`

## Технологии
- FFmpeg — извлечение кадров
- PySceneDetect — детекция сцен
- Claude Vision — анализ эмоций и контента
