# 01. Shot Detection — Детекция границ сцен

## Что делает

Анализирует видеофайл и находит моменты монтажных склеек (cuts) и переходов (fades, dissolves), разбивая видео на отдельные непрерывные сцены с точными таймкодами.

## Библиотека

- **PySceneDetect** — https://github.com/Breakthrough/PySceneDetect
- GitHub Stars: ~4,600
- Лицензия: BSD-3-Clause
- Активно развивается (обновления еженедельно)
- Альтернатива: **TransNetV2** (https://github.com/soCzech/TransNetV2, 894 stars) — нейросетевой подход, точнее для плавных переходов

## Как работает

### Алгоритмы детекции

**ContentDetector** (основной):
- Сравнивает цветовые гистограммы соседних кадров
- Если разница превышает порог → фиксирует склейку
- Быстрый, работает на CPU
- Лучший выбор для наших видео (резкие переходы между планами)

**AdaptiveDetector**:
- Адаптивный порог, учитывает локальные изменения яркости
- Лучше для driving footage (плавные изменения освещения)

**ThresholdDetector**:
- Детекция fade-in/fade-out по общей яркости кадра

### Процесс
1. Видео загружается покадрово через OpenCV
2. Каждая пара кадров сравнивается по выбранному алгоритму
3. Места с резким изменением → границы сцен
4. Из середины каждой сцены извлекается keyframe (FFmpeg)

## Применимость к YTAI

**Идеально подходит (10/10)**

Типы контента и что PySceneDetect найдёт:

| Тип видео (YTAI) | Что детектируется |
|---|---|
| YTCR — интервью с агентами | Переключение камер (крупный ↔ средний план) |
| YTCR — property tours | Переход между комнатами, вставки экстерьера |
| YTCG — бизнес-контент | Смена слайдов, переход interview ↔ B-roll |
| YTCR — driving footage | Смена локаций, вставки городских кадров |
| Все каналы | Вступление → основной контент → заключение |

**Пример на YTCR01 (al_qudra_lake):**
```
C5402.MP4 (15 мин, интервью + B-roll):
  Сцена 1:  00:00 — 00:12  → Establishing shot озера
  Сцена 2:  00:12 — 02:45  → Интервью крупный план
  Сцена 3:  02:45 — 02:52  → B-roll вставка (машина)
  Сцена 4:  02:52 — 05:30  → Интервью средний план
  Сцена 5:  05:30 — 05:55  → B-roll (интерьер)
  ...47 сцен всего
```

## Вход / Выход

### Вход
- Видеофайл: `{project}/01_Media/Source/Video/{scene}/*.MP4`
- Параметры: threshold (порог чувствительности), min_scene_len (мин. длина сцены)

### Выход
- Список сцен: `[{start_frame, end_frame, start_sec, end_sec, duration_sec}]`
- Keyframes: `{project}/01_Media/Source/Setup/Frames/{clip_id}/scene_NNN.jpg`
- Метаданные: `scenes.json`

### Формат scenes.json
```json
{
  "clip_id": "C5402",
  "filename": "C5402.MP4",
  "total_scenes": 47,
  "total_duration_sec": 905.2,
  "detector": "ContentDetector",
  "threshold": 27.0,
  "scenes": [
    {
      "scene_idx": 0,
      "start_sec": 0.0,
      "end_sec": 12.5,
      "start_frame": 0,
      "end_frame": 312,
      "duration_sec": 12.5,
      "keyframe_path": "Frames/C5402/scene_000.jpg",
      "keyframe_timestamp_sec": 6.25
    }
  ]
}
```

## Пример кода

```python
from scenedetect import open_video, SceneManager, ContentDetector
from scenedetect.scene_manager import save_images
import subprocess

def detect_scenes(video_path, threshold=27.0, min_scene_len=15):
    """Detect scene boundaries and extract keyframes."""
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    scene_manager.detect_scenes(video)
    scenes = scene_manager.get_scene_list()

    results = []
    for i, (start, end) in enumerate(scenes):
        mid_sec = (start.get_seconds() + end.get_seconds()) / 2
        results.append({
            "scene_idx": i,
            "start_sec": round(start.get_seconds(), 3),
            "end_sec": round(end.get_seconds(), 3),
            "duration_sec": round(end.get_seconds() - start.get_seconds(), 3),
            "keyframe_timestamp_sec": round(mid_sec, 3),
        })
    return results

def extract_keyframe(video_path, timestamp_sec, output_path):
    """Extract a single frame at given timestamp using FFmpeg."""
    subprocess.run([
        "ffmpeg", "-ss", str(timestamp_sec),
        "-i", video_path,
        "-vframes", "1", "-q:v", "2",
        output_path
    ], capture_output=True)
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Скорость анализа | ~5x realtime (15 мин видео → ~3 мин) |
| CPU usage | Средний (~40-60% одного ядра) |
| RAM | ~200-500 MB |
| Keyframe extraction | <1 сек на кадр (FFmpeg) |
| 40 проектов | ~2-3 часа |

На Apple Silicon M-серии: примерно такая же скорость (CPU-bound, не GPU).

## Зависимости

```bash
pip install scenedetect[opencv]
# Включает: scenedetect + opencv-python
# Размер: ~50MB (opencv)

# FFmpeg уже установлен в YTAI pipeline
```

## Настройка параметров

| Параметр | Значение | Эффект |
|----------|---------|--------|
| `threshold` | 27.0 (default) | Чувствительность. ↓ = больше сцен, ↑ = меньше |
| `min_scene_len` | 15 кадров (~0.5 сек) | Мин. длина сцены. Фильтрует "мерцание" |

Для наших видео:
- **Интервью**: threshold=30 (меньше ложных срабатываний от движения)
- **Driving/B-roll**: threshold=25 (ловить быстрые вставки)
- **Property tours**: threshold=27 (default, хорошо работает)

## Приоритет

**Core** — без этого модуля ничего не работает. Это фундамент для всех остальных модулей (CLIP, YOLO и т.д. работают на keyframes, которые извлекает этот модуль).
