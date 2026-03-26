# 06. Color Analysis — Анализ цветовой палитры

## Что делает

Извлекает доминантные цвета кадра, определяет яркость, цветовую температуру (тёплый/холодный) и насыщенность — для поиска B-roll по визуальному стилю и подбора цветово-совместимых кадров.

## Библиотека

- **OpenCV** — https://github.com/opencv/opencv (77K+ stars, Apache-2.0)
- **scikit-learn** — KMeans для кластеризации цветов
- Обе уже установлены (OpenCV через PySceneDetect, sklearn через DeepFace)

## Как работает

1. **Resize кадра** до 200x200 (ускорение, точность не теряется)
2. **KMeans кластеризация** пикселей в цветовом пространстве → 5 доминантных цветов
3. **Конвертация** в HEX для палитры + в HSV для метрик
4. **Метрики**: средняя яркость (V), средняя насыщенность (S), цветовая температура (Hue distribution)

### Цветовая температура:
- Warm: доминируют оранжевые/жёлтые тона (golden hour, тёплый свет)
- Cool: доминируют синие/голубые тона (пасмурно, тень, ночь)
- Neutral: смесь или серые тона

## Применимость к YTAI

**Полезно (6/10)** — для визуальной совместимости B-roll.

### Сценарии использования:
1. **Подбор B-roll по стилю**: "найди кадры с тёплой палитрой как в основном интервью"
2. **Color consistency**: убедиться что вставки B-roll не "выбиваются" из общего цветового решения
3. **Golden hour footage**: найти все кадры снятые на закате/рассвете (warm + определённый уровень яркости)
4. **Тёмные/светлые сцены**: фильтр по яркости для ночных или дневных кадров

### Пример на YTCR01:
```
scene_000.jpg (озеро, закат):
  palette: ["#E67E22", "#2C3E50", "#ECF0F1", "#8E6B3D", "#1A5276"]
  brightness: 0.58
  saturation: 0.45
  temperature: "warm"

scene_001.jpg (интервью в офисе):
  palette: ["#D5D5D5", "#4A4A4A", "#8B7355", "#FFFFFF", "#2C2C2C"]
  brightness: 0.65
  saturation: 0.15
  temperature: "neutral"

scene_002.jpg (driving, город):
  palette: ["#87CEEB", "#F5F5DC", "#696969", "#DCDCDC", "#4682B4"]
  brightness: 0.72
  saturation: 0.30
  temperature: "cool"
```

## Вход / Выход

### Вход
- Keyframe images

### Выход
```json
{
  "scene_idx": 0,
  "color_palette": ["#E67E22", "#2C3E50", "#ECF0F1", "#8E6B3D", "#1A5276"],
  "brightness": 0.58,
  "saturation": 0.45,
  "temperature": "warm",
  "is_dark": false,
  "is_vivid": false
}
```

## Пример кода

```python
import cv2
import numpy as np
from sklearn.cluster import KMeans

def analyze_colors(image_path, n_colors=5):
    """Extract dominant colors and compute brightness/temperature."""
    img = cv2.imread(image_path)
    img_small = cv2.resize(img, (200, 200))

    # KMeans clustering for dominant colors
    pixels = img_small.reshape(-1, 3).astype(float)
    kmeans = KMeans(n_clusters=n_colors, n_init=3, random_state=42)
    kmeans.fit(pixels)
    colors_bgr = kmeans.cluster_centers_.astype(int)
    palette = [f"#{r:02X}{g:02X}{b:02X}" for b, g, r in colors_bgr]

    # Convert to HSV for metrics
    hsv = cv2.cvtColor(img_small, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:,:,0], hsv[:,:,1], hsv[:,:,2]

    brightness = round(float(v.mean()) / 255, 2)
    saturation = round(float(s.mean()) / 255, 2)

    # Temperature: warm (H 0-30, 150-180) vs cool (H 90-130)
    h_mean = float(h.mean())
    if h_mean < 30 or h_mean > 150:
        temperature = "warm"
    elif 80 < h_mean < 130:
        temperature = "cool"
    else:
        temperature = "neutral"

    return {
        "color_palette": palette,
        "brightness": brightness,
        "saturation": saturation,
        "temperature": temperature,
        "is_dark": brightness < 0.35,
        "is_vivid": saturation > 0.55,
    }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Скорость | ~20ms/кадр |
| RAM | минимально (~50MB) |
| 50 кадров | <1 сек |
| 40 проектов | <1 мин |

Самый быстрый модуль — чистый OpenCV + numpy, без нейросетей.

## Зависимости

```bash
# Уже установлены:
# opencv-python (через scenedetect)
# scikit-learn (через deepface или отдельно)
# Нет дополнительных зависимостей
```

## Приоритет

**Extended** — полезно для визуальной совместимости, но не критично для базового B-roll поиска. Добавляется за 30 минут.
