# 08. OCR / Text Detection — Текст на экране

## Что делает

Обнаруживает и распознаёт текст, видимый на экране: титры, нижние трети (lower thirds), слайды презентаций, скриншоты UI, вывески, документы — для поиска кадров с конкретным текстом.

## Библиотека

- **EasyOCR** — https://github.com/JaidedAI/EasyOCR
- GitHub Stars: ~25,000
- Лицензия: Apache-2.0
- Поддержка 80+ языков (включая EN + RU одновременно)
- Альтернатива: **PaddleOCR** (https://github.com/PaddlePaddle/PaddleOCR, 48K stars) — быстрее, но сложнее установка
- Встроенная альтернатива: Apple Vision Framework через PyObjC (нативная, быстрая на macOS)

## Как работает

1. **Text Detection**: нейросеть CRAFT находит области с текстом (bounding boxes)
2. **Text Recognition**: CRNN распознаёт символы внутри каждого bbox
3. Результат: список `[bbox, text, confidence]`

### Особенности:
- Работает с наклонённым текстом
- Поддерживает мультиязычность (EN + RU в одном кадре)
- Может распознавать рукописный текст (с меньшей точностью)

## Применимость к YTAI

**Умеренно полезно (5/10)** — для специфических сценариев.

### Когда полезно:
| Сценарий | Пример |
|----------|--------|
| **Слайды/презентации** | Текст на экране в YTCG (бизнес-контент) |
| **Lower thirds** | Имя + должность спикера |
| **Вывески/указатели** | Название здания, улицы (property tours) |
| **UI/скриншоты** | Screen recording с интерфейсом |
| **Документы** | Показ контракта, лицензии |

### Когда НЕ полезно (большинство наших кадров):
- Чистые интервью (текста нет)
- Driving footage (текст мелкий, нечитаемый)
- Nature B-roll (нет текста)

### Оптимизация: запускать выборочно
Не на всех кадрах, а только на тех, где CLIP определил:
- `screen_recording` или `text_graphic`
- Или где YOLO нашёл `tv` / `laptop` (потенциально экран с текстом)

### Пример на YTCG37:
```
scene_005.jpg (слайд с данными):
  texts: ["Revenue Growth 2024", "45%", "Dubai Market"]
  → Можно найти по запросу "Revenue Growth"

scene_012.jpg (нижний третий):
  texts: ["Hadi Dawani", "CEO, Trading Company"]
  → Идентификация спикера
```

## Вход / Выход

### Вход
- Keyframe images (выборочно — только кадры с вероятным текстом)

### Выход
```json
{
  "scene_idx": 5,
  "ocr_texts": [
    {
      "text": "Revenue Growth 2024",
      "confidence": 0.92,
      "bbox": [[120, 50], [450, 50], [450, 90], [120, 90]],
      "position": "center"
    },
    {
      "text": "45%",
      "confidence": 0.98,
      "bbox": [[200, 150], [300, 150], [300, 220], [200, 220]],
      "position": "center"
    }
  ],
  "has_text": true,
  "text_combined": "Revenue Growth 2024 45% Dubai Market"
}
```

## Пример кода

```python
import easyocr

# Инициализация (скачивает модели ~100MB при первом запуске)
reader = easyocr.Reader(["en", "ru"], gpu=False)

def detect_text(image_path, min_confidence=0.3):
    """Detect and recognize text in a keyframe."""
    results = reader.readtext(image_path)

    texts = []
    for bbox, text, conf in results:
        if conf >= min_confidence:
            # Determine text position (top/center/bottom/lower_third)
            avg_y = sum(p[1] for p in bbox) / 4
            img_h = max(p[1] for p in bbox) + 100  # approximate
            if avg_y < img_h * 0.2:
                position = "top"
            elif avg_y > img_h * 0.75:
                position = "lower_third"
            else:
                position = "center"

            texts.append({
                "text": text.strip(),
                "confidence": round(conf, 3),
                "bbox": [[int(x), int(y)] for x, y in bbox],
                "position": position,
            })

    return {
        "ocr_texts": texts,
        "has_text": len(texts) > 0,
        "text_combined": " ".join(t["text"] for t in texts),
    }
```

## Производительность

| Метрика | CPU | GPU/MPS |
|---------|-----|---------|
| Скорость | ~1-3 сек/кадр | ~0.3-0.5 сек/кадр |
| Модели | ~100 MB (EN+RU) | ~100 MB |
| RAM | ~500 MB | ~500 MB |

**Самый медленный модуль.** Поэтому важна оптимизация — запускать выборочно:
- 40 проектов × ~2000 кадров → ~2000 × 20% с текстом = ~400 кадров
- 400 × 2 сек = ~13 мин (приемлемо)

## Зависимости

```bash
pip install easyocr
# Скачает при первом запуске:
# - CRAFT text detection model (~95MB)
# - Recognition model EN (~50MB)
# - Recognition model RU (~50MB)
# Итого: ~200MB моделей
```

## Приоритет

**Extended** — нишевое применение. Полезно для каналов с много слайдами/UI (YTCG), менее полезно для interview-heavy контента (YTCR).
