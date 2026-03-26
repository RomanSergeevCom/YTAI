# 13. Keyframe Selection — Выбор лучшего кадра

## Что делает

Выбирает **лучший представительный кадр** из каждой сцены на основе мульти-сигнального скоринга: резкость, композиция, отсутствие blink/blur, эстетическая привлекательность. Для thumbnail-кандидатов и визуальной превью в библиотеке.

## Библиотека

- Агрегация результатов модулей 11 (face framing) + 12 (quality)
- Дополнительно: **Katna** (https://github.com/keplerlab/katna, 391 stars, MIT) — специализированная библиотека для smart keyframe extraction
- Без обязательных новых зависимостей

## Как работает

### Подход 1: Multi-signal scoring (рекомендуемый)
Из каждой сцены извлекаем 3-5 кадров (не один). Каждый оценивается:

```python
score = (
    quality_score * 0.3 +          # Резкость, экспозиция (модуль 12)
    composition_score * 0.25 +     # Правило третей, лицо (модуль 11)
    no_blink_score * 0.2 +         # Глаза открыты (MediaPipe)
    aesthetic_score * 0.15 +       # CLIP "aesthetically pleasing photo"
    motion_blur_score * 0.1        # Отсутствие motion blur
)
```

Кадр с наивысшим score → best_keyframe.

### Подход 2: Katna
```python
from Katna.video import Video
vd = Video()
images = vd.extract_video_keyframes(filepath="video.mp4", no_of_frames=5)
```
Katna автоматически выбирает визуально разнообразные, резкие кадры. Но менее гибкая.

## Применимость к YTAI

**Полезно (6/10)** — для thumbnail и визуальной превью.

### Сценарии:
- **Thumbnail candidates**: автоматически выбрать 5 лучших кадров из видео для thumbnail
- **B-roll preview**: в библиотеке показать самый репрезентативный кадр каждой сцены
- **Social media**: автовыбор кадров для Instagram/Twitter превью

### Пример:
```
scene_003 (interview, 2:30):
  frame@2:35 → score: 0.45 (blink detected)
  frame@2:38 → score: 0.82 (sharp, good composition, eyes open)  ← BEST
  frame@2:41 → score: 0.71 (slight motion blur)
```

## Вход / Выход

### Вход
- Видеофайл + таймкоды сцен (от PySceneDetect)
- Результаты модулей 11, 12

### Выход
```json
{
  "scene_idx": 3,
  "best_keyframe": {
    "path": "Frames/C5402/scene_003_best.jpg",
    "timestamp_sec": 158.4,
    "score": 0.82,
    "scores": {
      "quality": 0.90,
      "composition": 0.85,
      "no_blink": 1.0,
      "aesthetic": 0.65,
      "no_motion_blur": 0.80
    }
  },
  "thumbnail_candidate": true
}
```

## Пример кода

```python
import cv2

def select_best_keyframe(video_path, start_sec, end_sec, n_candidates=5):
    """Select the best keyframe from a scene by multi-signal scoring."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    timestamps = [start_sec + i * (end_sec - start_sec) / (n_candidates + 1)
                  for i in range(1, n_candidates + 1)]

    best_score = -1
    best_frame = None
    best_ts = None

    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
        ret, frame = cap.read()
        if not ret:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Quality score
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharp_score = min(sharpness / 200, 1.0)

        exposure = gray.mean() / 255.0
        expo_score = 1.0 - abs(exposure - 0.5) * 2

        score = sharp_score * 0.6 + expo_score * 0.4

        if score > best_score:
            best_score = score
            best_frame = frame
            best_ts = ts

    cap.release()
    return best_frame, best_ts, best_score
```

## Производительность

| Метрика | Значение |
|---------|---------|
| 5 кадров/сцена | ~100ms (чтение + scoring) |
| 50 сцен | ~5 сек |
| 40 проектов | ~3 мин |

## Зависимости

```bash
# Уже установлено: opencv-python
# Опционально: pip install Katna  (~50MB)
```

## Приоритет

**Nice-to-have** — улучшает качество превью в библиотеке. Базовый keyframe (середина сцены) обычно достаточно хорош.
