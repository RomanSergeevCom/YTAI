# Video Analysis Pipeline — B-roll Library

## Цель

Автоматический визуальный анализ всех видеопроектов YTAI (40+ проектов, 4 канала) для создания поисковой B-roll библиотеки. Система анализирует каждый видеофайл, определяет типы кадров, объекты, настроение, цветовую палитру и сохраняет результаты в SQLite базу с полнотекстовым поиском.

## Архитектура

```
Video files (MP4)
  │
  ├── [1] PySceneDetect ──→ границы сцен + тип перехода
  │
  ├── [2] FFmpeg ──→ keyframes (1 кадр на сцену)
  │
  ├── [3] CLIP ──→ тип кадра (interview/broll/driving/aerial)
  │
  ├── [4] YOLOv8 ──→ объекты (person, car, building, food)
  │
  ├── [5] MediaPipe ──→ позы, эмоции, жесты, количество лиц
  │
  ├── [6] OpenCV ──→ палитра цветов, яркость, температура
  │
  ├── [7] Optical Flow ──→ движение камеры (pan/tilt/zoom/static)
  │
  ├── [8] EasyOCR ──→ текст на экране
  │
  ├── [9] pyAudioAnalysis ──→ речь/музыка/тишина
  │
  └── [10-14] Агрегация ──→ AV-sync, face framing, quality, keyframe selection, density
         │
         ▼
  SQLite DB (~/.ytai/broll.db)
  + FTS5 полнотекстовый поиск
  + CLI / Web UI
```

## 14 модулей анализа

### Core (приоритет 1 — 80% ценности)

| # | Модуль | Библиотека | Что извлекает | Файл |
|---|--------|-----------|---------------|------|
| 1 | Shot Detection | PySceneDetect | Границы сцен, тип перехода (cut/fade) | [01_shot_detection.md](01_shot_detection.md) |
| 2 | Shot Classification | CLIP (OpenAI) | Тип кадра: interview, broll, driving, aerial | [02_shot_classification.md](02_shot_classification.md) |
| 3 | Object Detection | YOLOv8 (Ultralytics) | Объекты, количество, bounding boxes | [03_object_detection.md](03_object_detection.md) |
| 4 | Person Analysis | MediaPipe + DeepFace | Поза, эмоции, жесты, количество лиц | [04_person_analysis.md](04_person_analysis.md) |
| 5 | Scene Classification | CLIP | Локация, настроение, время суток | [05_scene_classification.md](05_scene_classification.md) |

### Extended (приоритет 2 — визуальный стиль + аудио)

| # | Модуль | Библиотека | Что извлекает | Файл |
|---|--------|-----------|---------------|------|
| 6 | Color Analysis | OpenCV + sklearn | Палитра, яркость, температура, насыщенность | [06_color_analysis.md](06_color_analysis.md) |
| 7 | Camera Motion | OpenCV optical flow | Статика/панорама/наезд/отъезд/tracking | [07_camera_motion.md](07_camera_motion.md) |
| 8 | OCR / Text | EasyOCR | Текст на экране, нижние трети, титры | [08_ocr_text.md](08_ocr_text.md) |
| 9 | Audio Analysis | pyAudioAnalysis + Silero VAD | Речь/музыка/тишина, громкость | [09_audio_analysis.md](09_audio_analysis.md) |
| 10 | Audio-Visual Sync | Модули 1+9 | B-roll detection (видео без речи) | [10_audio_visual_sync.md](10_audio_visual_sync.md) |

### Nice-to-have (приоритет 3 — продвинутая аналитика)

| # | Модуль | Библиотека | Что извлекает | Файл |
|---|--------|-----------|---------------|------|
| 11 | Face Framing | MediaPipe + OpenCV | Screen time %, правило третей, линия взгляда | [11_face_framing.md](11_face_framing.md) |
| 12 | Quality Metrics | OpenCV | Размытость, шум, стабильность изображения | [12_quality_metrics.md](12_quality_metrics.md) |
| 13 | Keyframe Selection | Мульти-сигнал | Лучший кадр для thumbnail из каждой сцены | [13_keyframe_selection.md](13_keyframe_selection.md) |
| 14 | Content Density | Агрегация | Монтажный темп (cuts/min), энергетическая кривая | [14_content_density.md](14_content_density.md) |

## Дополнительные документы

| Файл | Содержание |
|------|-----------|
| [database_schema.md](database_schema.md) | SQLite схема: таблицы, FTS5, индексы, запросы |
| [output_schema.md](output_schema.md) | JSON-формат полного выхода на сцену |
| [dependencies.md](dependencies.md) | Все Python-зависимости + установка + размеры моделей |
| [tools_comparison.md](tools_comparison.md) | TouchDesigner vs Python — почему выбран Python |
| [broll_library.md](broll_library.md) | B-roll библиотека: CLI, Web UI, интеграция с пайплайном |

## Порядок реализации

### Phase 1: Core B-roll Library (2-3 дня)
```
04_video_analysis/
    01_extract_frames.py    ← PySceneDetect + FFmpeg keyframes
    02_detect_scenes.py     ← scene boundary wrapper
    05_find_broll.py        ← CLIP classification + YOLOv8
    06_generate_visual_brief.py ← SQLite index builder
    broll_search.py         ← CLI + Web UI
    templates/search.html   ← browser UI
```

### Phase 2: Extended Analysis (+2 дня)
- Color analysis, camera motion, OCR, audio analysis
- Каждый модуль добавляется независимо

### Phase 3: Advanced (+2 дня)
- Face framing, quality metrics, keyframe selection, content density
- Semantic search (vector embeddings)

## Производительность (оценка)

| Этап | Скорость | 15-мин клип | 40 проектов |
|------|----------|-------------|-------------|
| PySceneDetect | ~5x realtime | ~3 мин | ~2-3 часа |
| FFmpeg keyframes | мгновенно | <1 сек/кадр | ~5 мин |
| CLIP (Apple MPS) | ~0.05 сек/кадр | ~2.5 сек | ~5 мин |
| YOLOv8 (CPU) | ~0.3 сек/кадр | ~15 сек | ~20 мин |
| **Итого Core** | | ~5 мин | **~3-4 часа** |

Полный анализ всего архива: запустил на ночь — утром готово.

## Интеграция с YTAI

### Входные данные (уже есть)
- `{project}/01_Media/Source/Video/{scene}/*.MP4` — видеофайлы
- `{project}/01_Media/Source/Setup/{CODE}_ingest.json` — метаданные клипов
- `{project}/01_Media/Source/Setup/{CODE}_Claude4_assembly.json` — транскрипты

### Выходные данные (создаём)
- `{project}/01_Media/Source/Setup/Frames/{clip_id}/` — keyframes
- `{project}/01_Media/Source/Setup/visual_metadata.json` — результат анализа
- `~/.ytai/broll.db` — центральный поисковый индекс

### Pipeline hook
Добавляется в `scripts/run_pipeline.py` как phase `video_analysis` после transcribe.

## Стек

Полностью локальный, бесплатный, macOS-совместимый:
- **Python 3.10+** — основной язык
- **PySceneDetect** — scene detection (BSD-3)
- **OpenAI CLIP** — zero-shot classification (MIT)
- **Ultralytics YOLOv8** — object detection (AGPL-3.0)
- **MediaPipe** — pose/face/hand estimation (Apache-2.0)
- **DeepFace** — emotion recognition (MIT)
- **OpenCV** — color analysis, optical flow, quality (Apache-2.0)
- **EasyOCR** — text detection (Apache-2.0)
- **pyAudioAnalysis** — audio classification (Apache-2.0)
- **Silero VAD** — voice activity detection (MIT)
- **SQLite + FTS5** — database + full-text search (built-in)
- **FFmpeg** — frame extraction (уже установлен)
