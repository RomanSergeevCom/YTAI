# 07. Camera Motion — Определение движения камеры

## Что делает

Определяет тип движения камеры: статика (штатив), панорама (pan left/right), наклон (tilt up/down), наезд/отъезд (zoom), tracking (слежение за объектом), ручная камера (handheld). Для поиска B-roll по типу движения.

## Библиотека

- **OpenCV** — Optical Flow (Farneback / Lucas-Kanade)
- Уже установлен
- Альтернатива: **camera-motion-detector** — https://github.com/antiboredom/camera-motion-detector (специализированный, но менее гибкий)

## Как работает

### Optical Flow (Farneback)
1. Берём два соседних кадра (или начало + конец сцены)
2. Вычисляем вектор смещения каждого пикселя
3. Анализируем паттерн смещений:
   - **Static**: все вектора близки к нулю
   - **Pan**: все вектора горизонтальные, одного направления
   - **Tilt**: все вектора вертикальные, одного направления
   - **Zoom in**: вектора расходятся от центра
   - **Zoom out**: вектора сходятся к центру
   - **Tracking**: вектора разнонаправленные, но плавные
   - **Handheld**: вектора хаотичные, мелкая амплитуда

### Для нашего пайплайна (keyframe-based):
Вместо анализа каждого кадра видео, берём 3-5 кадров из сцены (начало, 25%, 50%, 75%, конец) и анализируем optical flow между ними. Это в ~50x быстрее чем покадровый анализ.

## Применимость к YTAI

**Полезно (7/10)** — для поиска по типу движения.

### Типичные движения камеры в YTAI:

| Тип контента | Типичное движение | Как найти |
|---|---|---|
| Интервью (YTCR/YTCG) | static (штатив) | `--motion static` |
| Property tour (YTCR) | tracking + pan (гимбал) | `--motion tracking` |
| Driving footage (YTCR) | tracking_forward (POV) | `--motion tracking` |
| Dubai skyline (YTCR) | pan (панорама) или static | `--motion pan` |
| Walking (YTCG) | handheld | `--motion handheld` |
| Drone (YTCR) | pan + tilt + zoom | `--motion pan` |

### Пример запроса:
```bash
# Найти все плавные панорамы для B-roll вставки
search --motion pan --type broll

# Найти статичные кадры (для текстовых оверлеев)
search --motion static --min-duration 5

# Найти cinematic tracking shots
search --motion tracking --location city_street
```

## Вход / Выход

### Вход
- Видеофайл (нужно извлечь несколько кадров из каждой сцены)
- Или: 3-5 keyframes из сцены (если уже извлечены)

### Выход
```json
{
  "scene_idx": 4,
  "camera_motion": "pan_right",
  "motion_magnitude": 0.65,
  "motion_stability": 0.85,
  "motion_category": "smooth"
}
```

### Категории motion:
- `static` — камера неподвижна (magnitude < 0.05)
- `pan_left` / `pan_right` — горизонтальное панорамирование
- `tilt_up` / `tilt_down` — вертикальное панорамирование
- `zoom_in` / `zoom_out` — приближение/удаление
- `tracking_forward` — движение вперёд (driving POV)
- `tracking` — слежение за объектом
- `handheld` — ручная камера (стабилизация выше порога)
- `complex` — комбинация нескольких типов

### Motion stability:
- `smooth` (> 0.7) — штатив, гимбал, слайдер
- `moderate` (0.4-0.7) — стабилизированная ручная
- `shaky` (< 0.4) — нестабилизированная ручная

## Пример кода

```python
import cv2
import numpy as np

def analyze_camera_motion(video_path, start_sec, end_sec, sample_count=5):
    """Analyze camera motion type within a scene."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)

    # Sample frames evenly across the scene
    timestamps = np.linspace(start_sec, end_sec, sample_count)
    frames = []
    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
        ret, frame = cap.read()
        if ret:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frames.append(cv2.resize(gray, (320, 240)))
    cap.release()

    if len(frames) < 2:
        return {"camera_motion": "unknown", "motion_magnitude": 0}

    # Compute optical flow between consecutive samples
    flows = []
    for i in range(len(frames) - 1):
        flow = cv2.calcOpticalFlowFarneback(
            frames[i], frames[i+1], None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.1, flags=0
        )
        flows.append(flow)

    # Average flow vectors
    avg_flow = np.mean(flows, axis=0)
    dx = avg_flow[:,:,0].mean()
    dy = avg_flow[:,:,1].mean()
    magnitude = np.sqrt(dx**2 + dy**2)

    # Classify motion type
    if magnitude < 2.0:
        motion = "static"
    elif abs(dx) > abs(dy) * 2:
        motion = "pan_right" if dx > 0 else "pan_left"
    elif abs(dy) > abs(dx) * 2:
        motion = "tilt_down" if dy > 0 else "tilt_up"
    else:
        # Check for zoom (divergent/convergent flow)
        h, w = avg_flow.shape[:2]
        cx, cy = w // 2, h // 2
        # Vectors pointing away from center = zoom in
        radial = avg_flow[cy, cx:, 0].mean()  # right half, x component
        if radial > 1.5:
            motion = "zoom_in"
        elif radial < -1.5:
            motion = "zoom_out"
        else:
            motion = "tracking" if magnitude > 5 else "handheld"

    # Stability: variance of flow magnitudes
    flow_mags = [np.sqrt(f[:,:,0]**2 + f[:,:,1]**2).std() for f in flows]
    stability = 1.0 - min(np.mean(flow_mags) / 10, 1.0)

    return {
        "camera_motion": motion,
        "motion_magnitude": round(float(magnitude), 2),
        "motion_stability": round(float(stability), 2),
        "motion_category": "smooth" if stability > 0.7 else "moderate" if stability > 0.4 else "shaky",
    }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Скорость (5 samples/scene) | ~200ms/сцена |
| RAM | ~100 MB |
| 50 сцен (1 клип) | ~10 сек |
| 40 проектов | ~7 мин |

Основное время — чтение кадров из видео (I/O). Optical flow сам по себе быстрый.

## Зависимости

```bash
# Уже установлено:
# opencv-python (через scenedetect)
# numpy
# Нет дополнительных зависимостей
```

## Приоритет

**Extended** — полезно для поиска "cinematic" B-roll (плавные панорамы, tracking shots). Не критично для базовой библиотеки.
