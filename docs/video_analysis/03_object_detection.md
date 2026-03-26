# 03. Object Detection — Детекция объектов

## Что делает

Находит и идентифицирует конкретные объекты на каждом кадре: люди, машины, мебель, еда, электроника и т.д. Выдаёт список объектов с координатами и уверенностью.

## Библиотека

- **Ultralytics YOLOv8** — https://github.com/ultralytics/ultralytics
- GitHub Stars: ~55,000
- Лицензия: AGPL-3.0 (для коммерческого — Enterprise лицензия)
- Активнейшее развитие (обновления ежедневно)
- 80 предобученных классов объектов (COCO dataset)
- Работает на Apple Silicon MPS

## Как работает

YOLO (You Only Look Once) анализирует кадр за один проход нейросети:
1. Делит изображение на сетку
2. Для каждой ячейки предсказывает: есть ли объект, какой класс, где границы (bounding box)
3. Non-Maximum Suppression убирает дубли
4. Результат: список `[class, confidence, x1, y1, x2, y2]`

### Модели (от быстрой к точной):
| Модель | Размер | Скорость (CPU) | Точность (mAP) |
|--------|--------|---------------|----------------|
| YOLOv8n (nano) | 6 MB | ~80ms/кадр | 37.3 |
| YOLOv8s (small) | 22 MB | ~130ms/кадр | 44.9 |
| YOLOv8m (medium) | 52 MB | ~300ms/кадр | 50.2 |

Рекомендация: **YOLOv8n** — для B-roll каталогизации достаточно, скорость важнее точности.

## Применимость к YTAI

**Хорошо подходит (7/10)** — полезное дополнение к CLIP.

### Главная ценность: person_count
YOLO точно считает людей в кадре → ключевой сигнал для разделения interview vs B-roll:
- 1-2 person → вероятно interview
- 0 person → чистый B-roll
- 5+ person → crowd/event footage

### Полезные классы COCO для YTAI:

| Класс | Применение в YTAI |
|-------|-------------------|
| person | Кол-во людей, interview vs B-roll |
| car, bus, truck | Driving footage, street scenes |
| chair, couch, dining table | Interior (apartment tour) |
| tv, laptop, cell phone | Office, tech content |
| cup, bottle, bowl, fork | Food/coffee scenes (YTCG) |
| potted plant | Interior декор |
| book | Office/study scenes |
| bicycle, motorcycle | Street scenes |
| airplane, boat | Travel content |

### Чего НЕ знает YOLO (нужен CLIP):
- "Dubai skyline" — видит только "building" (generic)
- "real estate tour" — видит "person + couch" (no context)
- "driving POV" — видит "car" (doesn't understand POV)
- Настроение, локацию, тип съёмки

### Пример на YTCR01:
```
scene_000.jpg → person: 0, car: 0                    → B-roll (lake landscape)
scene_001.jpg → person: 1 (0.96)                     → Interview (talking head)
scene_002.jpg → person: 0, car: 2, truck: 1          → B-roll (driving/street)
scene_003.jpg → person: 2 (0.95, 0.91), chair: 2     → Interview (two people)
scene_004.jpg → person: 0, building: 0               → B-roll (skyline, YOLO may not detect buildings well)
scene_005.jpg → person: 1, couch: 1, tv: 1, cup: 1   → Interior tour OR interview
```

## Вход / Выход

### Вход
- Keyframe images: `Setup/Frames/{clip_id}/scene_NNN.jpg`
- Параметры: confidence threshold (default 0.4), model size (default "n")

### Выход
```json
{
  "scene_idx": 3,
  "objects": ["person", "person", "chair", "laptop"],
  "objects_unique": ["person", "chair", "laptop"],
  "person_count": 2,
  "detections": [
    {"class": "person", "confidence": 0.95, "bbox": [120, 50, 450, 680]},
    {"class": "person", "confidence": 0.91, "bbox": [500, 60, 780, 670]},
    {"class": "chair", "confidence": 0.82, "bbox": [100, 400, 300, 700]},
    {"class": "laptop", "confidence": 0.75, "bbox": [350, 350, 500, 450]}
  ]
}
```

## Пример кода

```python
from ultralytics import YOLO
from collections import Counter

# Загрузка модели (6MB, скачивается автоматически)
model = YOLO("yolov8n.pt")

def detect_objects(image_path, conf_threshold=0.4):
    """Detect objects in a single keyframe."""
    results = model.predict(image_path, conf=conf_threshold, verbose=False)

    detections = []
    for r in results[0].boxes:
        cls_id = int(r.cls[0])
        detections.append({
            "class": model.names[cls_id],
            "confidence": round(float(r.conf[0]), 3),
            "bbox": [int(x) for x in r.xyxy[0].tolist()],
        })

    objects = [d["class"] for d in detections]
    return {
        "objects": objects,
        "objects_unique": sorted(set(objects)),
        "person_count": objects.count("person"),
        "detections": detections,
    }

# Batch processing
def analyze_keyframes(frames_dir):
    """Analyze all keyframes in a directory."""
    from pathlib import Path
    results = {}
    for frame in sorted(Path(frames_dir).glob("scene_*.jpg")):
        results[frame.stem] = detect_objects(str(frame))
    return results
```

## Производительность

| Метрика | YOLOv8n (CPU) | YOLOv8n (MPS) |
|---------|--------------|---------------|
| Скорость | ~80ms/кадр | ~15ms/кадр |
| Модель | 6 MB | 6 MB |
| RAM | ~200 MB | ~200 MB |
| 50 кадров (1 клип) | ~4 сек | ~0.75 сек |
| 40 проектов (~2000 кадров) | ~3 мин | ~30 сек |

YOLOv8 — самый быстрый из всех модулей. Практически бесплатный по времени.

## Зависимости

```bash
pip install ultralytics
# Включает: ultralytics + opencv + torch (если не установлен)
# Модель yolov8n.pt: 6 MB (скачивается при первом запуске)
```

## Продвинутое использование

### Кастомные классы
Если 80 классов COCO недостаточно, можно:
1. Использовать **YOLOv8-world** (open-vocabulary detection) — текстовые промпты как в CLIP
2. Дообучить на своих данных (нужна разметка)

### Tracking (для видео, не keyframes)
```python
# Отслеживание объектов через видео
results = model.track(source="video.mp4", tracker="bytetrack.yaml")
```
Полезно для: подсчёта уникальных людей, определения screen time.

## Приоритет

**Core** — дополняет CLIP person_count'ом и списком объектов для поиска. Быстрый, лёгкий, почти не добавляет времени обработки.
