# B-roll Library — CLI, Web UI и интеграция

## Обзор

B-roll Library — это поисковый интерфейс поверх SQLite базы с результатами визуального анализа. Позволяет быстро найти нужный B-roll кадр по типу, локации, объектам, цвету и другим критериям.

## CLI (broll_search.py)

### Команды

```bash
# ═══════════════════════════════════════════════
# АНАЛИЗ
# ═══════════════════════════════════════════════

# Проанализировать один проект
python scripts/04_video_analysis/broll_search.py analyze \
    "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis"

# Проанализировать все проекты на подключённых дисках
python scripts/04_video_analysis/broll_search.py analyze-all

# Проанализировать только один клип
python scripts/04_video_analysis/broll_search.py analyze \
    "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" --clip C5402

# Указать модули (по умолчанию: core)
python scripts/04_video_analysis/broll_search.py analyze \
    "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" --modules all
    # Варианты: core, extended, all

# ═══════════════════════════════════════════════
# ПОИСК
# ═══════════════════════════════════════════════

# Полнотекстовый поиск (FTS5)
python scripts/04_video_analysis/broll_search.py search "Dubai skyline"
python scripts/04_video_analysis/broll_search.py search "кофейня интерьер"

# Поиск по shot type
python scripts/04_video_analysis/broll_search.py search --type driving_pov
python scripts/04_video_analysis/broll_search.py search --type aerial_drone

# Поиск по локации
python scripts/04_video_analysis/broll_search.py search --location city_street
python scripts/04_video_analysis/broll_search.py search --location desert

# Поиск по объектам
python scripts/04_video_analysis/broll_search.py search --objects "car,building"

# Фильтры
python scripts/04_video_analysis/broll_search.py search "driving" \
    --channel YTCR \
    --mood casual \
    --color-temp warm \
    --quality good \
    --motion pan

# Только B-roll (исключить interview)
python scripts/04_video_analysis/broll_search.py search --broll-only

# Лимит результатов
python scripts/04_video_analysis/broll_search.py search "skyline" --limit 20

# ═══════════════════════════════════════════════
# ОБЗОР
# ═══════════════════════════════════════════════

# Список всех проектов в базе
python scripts/04_video_analysis/broll_search.py projects

# Детали проекта
python scripts/04_video_analysis/broll_search.py info YTCR01

# Статистика базы
python scripts/04_video_analysis/broll_search.py stats

# Все уникальные shot types
python scripts/04_video_analysis/broll_search.py types

# Все уникальные локации
python scripts/04_video_analysis/broll_search.py locations

# ═══════════════════════════════════════════════
# WEB UI
# ═══════════════════════════════════════════════

# Запустить веб-интерфейс на localhost:8080
python scripts/04_video_analysis/broll_search.py serve
python scripts/04_video_analysis/broll_search.py serve --port 9000
```

### Формат вывода поиска

```
Found 12 B-roll scenes matching "driving":

[1] YTCR01 / desert_drive / C5410 @ 00:00 — 05:30 (5:30)
    Type: driving_pov (0.95) | Motion: tracking_forward
    Objects: car, road | Location: highway
    Color: warm | Quality: excellent
    File: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Video/desert_drive/C5410.MP4
    Drive: RYA T7 Black [CONNECTED]

[2] YTCR01 / dubai_driving / C5420 @ 00:00 — 08:15 (8:15)
    Type: driving_pov (0.93) | Motion: tracking_forward
    Objects: car, building, road | Location: city_street
    Color: neutral | Quality: good
    File: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Video/dubai_driving/C5420.MP4
    Drive: RYA T7 Black [CONNECTED]

[3] YTCR01 / al_qudra_lake / C5402 @ 00:45 — 01:02 (0:17)
    Type: driving_pov (0.91) | Motion: tracking_forward
    Objects: car, road, building | Location: highway
    Color: warm | Quality: good
    Drive: RYA T7 Black [CONNECTED]

--- Total: 12 scenes (8:02 of B-roll) across 3 projects ---
```

## Web UI (search.html)

### Функционал

Один HTML файл с inline CSS + JS (без build step), served через Python http.server / FastAPI.

#### Поисковая строка
- Текстовый ввод + кнопка поиска
- Автокомплит по shot types и locations

#### Фильтры (sidebar)
- Канал: [YTCR] [YTCG] [YTRF] [YTXX]
- Тип кадра: dropdown (driving_pov, aerial_drone, interior_tour, ...)
- Локация: dropdown (city_street, office, desert, ...)
- Настроение: dropdown (formal, casual, luxury, ...)
- Объекты: multi-select (person, car, building, ...)
- Цвет: warm / cool / neutral
- Качество: excellent / good / poor
- Движение камеры: static / pan / tracking / handheld
- Только B-roll: checkbox

#### Результаты (grid)
- Thumbnail grid (4 колонки)
- Каждая карточка:
  - Keyframe image
  - Shot type badge (цветной)
  - Проект + клип + таймкод
  - Объекты (tags)
  - Статус диска (connected/offline)
- Клик → модалка с деталями:
  - Полный JSON метаданных
  - Соседние сцены (контекст)
  - Путь к файлу (copy button)
  - Color palette визуализация

#### Статистика (dashboard)
- Всего проектов / клипов / сцен / B-roll
- Breakdown по shot types (pie chart)
- Top locations (bar chart)
- Статус дисков

### Паттерн (как disk_analyzer)

```python
# serve.py — минимальный сервер
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import sqlite3

class SearchHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.serve_html()
        elif self.path.startswith('/api/search'):
            self.handle_search()
        elif self.path.startswith('/api/stats'):
            self.handle_stats()
        elif self.path.startswith('/frames/'):
            self.serve_frame()

    def handle_search(self):
        # Parse query params → SQLite FTS5 query → JSON response
        ...

    def serve_frame(self):
        # Serve keyframe images from project folders
        ...
```

## Интеграция с YTAI Pipeline

### Hook в run_pipeline.py

```python
# Добавить в PHASES после transcribe:
{
    "id": "video_analysis",
    "name": "Visual Analysis",
    "script": "04_video_analysis/broll_search.py",
    "args": ["analyze"],
    "optional": True,
    "description": "Анализ видео: shot detection, classification, objects"
}
```

### Связь с Assembly Brief

При генерации Assembly brief Claude может использовать B-roll библиотеку:

1. Чтение `visual_metadata.json` текущего проекта → автозаполнение `broll_note`
2. Поиск в базе других проектов → "у вас есть driving B-roll из YTCR01/desert_drive"
3. Рекомендации по B-roll вставкам на основе пауз в речи

### Пример интеграции с brief:
```json
{
  "segment_id": "seg_005",
  "block": 3,
  "block_name": "Dubai Market Overview",
  "transcript": "Dubai real estate market has been growing...",
  "broll_note": "Dubai skyline establishing shot",
  "broll_suggestions": [
    {
      "source": "YTCR01/al_qudra_lake/C5402",
      "tc": "00:00-00:12",
      "type": "nature_landscape",
      "confidence": 0.85,
      "from_library": true
    }
  ]
}
```

## Offline дисков

### Поведение при отключённом диске
1. Все метаданные остаются в SQLite (`~/.ytai/broll.db`)
2. Поиск работает полностью
3. Keyframe images недоступны (могут быть закешированы)
4. В результатах: `Drive: RYA T7 Black [OFFLINE]`
5. Путь к файлу показан, но помечен как недоступный

### Кеширование keyframes
Опционально: скопировать keyframes на внутренний диск (200MB на 40 проектов) чтобы Web UI всегда показывал thumbnails.

```bash
# Кеш keyframes на внутренний диск
python broll_search.py cache-frames ~/.ytai/frames/
```

## Файловая структура

```
scripts/04_video_analysis/
    01_extract_frames.py        # PySceneDetect + FFmpeg
    02_detect_scenes.py         # Scene boundary wrapper
    03_detect_emotions.py       # MediaPipe + DeepFace → faces, emotions
    04_detect_gestures.py       # MediaPipe Pose → body pose
    05_find_broll.py            # CLIP + YOLO → shot type + objects
    06_generate_visual_brief.py # SQLite index builder + visual_metadata.json
    broll_search.py             # CLI + Web UI entry point
    database.py                 # SQLite schema + queries
    analyzers/                  # Optional: Extended modules
        color.py                # Module 06
        camera_motion.py        # Module 07
        ocr.py                  # Module 08
        audio.py                # Module 09
        av_sync.py              # Module 10
        face_framing.py         # Module 11
        quality.py              # Module 12
        keyframe.py             # Module 13
        density.py              # Module 14
    templates/
        search.html             # Browser UI
    README.md                   # Updated docs
```
