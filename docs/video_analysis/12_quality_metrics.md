# 12. Quality Metrics — Метрики качества изображения

## Что делает

Оценивает техническое качество каждого кадра: резкость (blur/sharpness), уровень шума, экспозиция (переэкспонирован/недоэкспонирован) — для фильтрации некачественных кадров и выбора лучших для thumbnail.

## Библиотека

- **OpenCV** — Laplacian variance, histogram analysis
- Уже установлен, без дополнительных зависимостей

## Как работает

### Sharpness (Laplacian Variance):
```python
# Laplacian = оператор второй производной
# Высокая дисперсия = резкий кадр, низкая = размытый
sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
```
- \> 100: резкий (хороший)
- 50-100: средний
- < 50: размытый (движение камеры, расфокус)

### Exposure:
- Гистограмма яркости: если пик слева → недоэкспонирован, справа → переэкспонирован
- Clipping: % пикселей с яркостью 0 (тень) или 255 (пересвет)

### Noise:
- Разница между оригиналом и Gaussian blur → STD = уровень шума
- Высокий noise → ночная съёмка, высокий ISO

## Применимость к YTAI

**Умеренно полезно (4/10)** — для QC и thumbnail.

### Когда полезно:
- **Фильтрация размытых кадров**: исключить из B-roll библиотеки
- **Thumbnail candidates**: выбрать самые резкие кадры
- **Night/low-light detection**: пометить тёмные/шумные кадры

### Пример:
```
scene_004.jpg: sharpness=156, exposure=0.62, noise=12 → quality: "good"
scene_015.jpg: sharpness=28, exposure=0.45, noise=35  → quality: "poor" (blur + noise)
scene_030.jpg: sharpness=220, exposure=0.85, noise=8   → quality: "excellent"
```

## Вход / Выход

### Выход
```json
{
  "scene_idx": 4,
  "quality": {
    "sharpness": 156.3,
    "exposure": 0.62,
    "noise_level": 12.1,
    "is_overexposed": false,
    "is_underexposed": false,
    "is_blurry": false,
    "quality_score": 0.82,
    "quality_label": "good"
  }
}
```

## Пример кода

```python
import cv2
import numpy as np

def analyze_quality(image_path):
    """Assess image quality: sharpness, exposure, noise."""
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Sharpness (Laplacian variance)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()

    # Exposure (mean brightness 0-1)
    exposure = gray.mean() / 255.0

    # Noise estimation (STD of high-frequency component)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    noise = float(np.std(gray.astype(float) - blur.astype(float)))

    # Composite score
    sharp_score = min(sharpness / 200, 1.0)
    expo_score = 1.0 - abs(exposure - 0.5) * 2  # 0.5 is ideal
    noise_score = max(1.0 - noise / 30, 0)
    quality_score = sharp_score * 0.5 + expo_score * 0.3 + noise_score * 0.2

    return {
        "quality": {
            "sharpness": round(sharpness, 1),
            "exposure": round(exposure, 2),
            "noise_level": round(noise, 1),
            "is_overexposed": exposure > 0.85,
            "is_underexposed": exposure < 0.15,
            "is_blurry": sharpness < 50,
            "quality_score": round(quality_score, 2),
            "quality_label": "excellent" if quality_score > 0.8 else "good" if quality_score > 0.5 else "poor",
        }
    }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Скорость | ~5ms/кадр |
| RAM | минимально |
| 40 проектов | <30 сек |

Самый быстрый модуль (чистый OpenCV + numpy).

## Зависимости

```bash
# Уже установлено: opencv-python, numpy
```

## Приоритет

**Nice-to-have** — полезно для QC, но не критично для B-roll поиска. Добавляется за 15 минут.
