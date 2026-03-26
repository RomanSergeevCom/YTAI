# 05. Scene Classification — Классификация сцены/локации

## Что делает

Определяет контекст сцены: локацию (офис, улица, ресторан, пустыня), настроение (formal, casual, energetic), время суток (day, night, golden hour), и тип контента — через второй проход CLIP с другой таксономией.

## Библиотека

- **CLIP** — тот же, что в модуле 02 (переиспользуем загруженную модель)
- Дополнительно: **Places365** (https://github.com/CSAILVision/places365) — специализированная модель для классификации мест (365 категорий)
- GitHub Stars: ~1,700, MIT

## Как работает

Модуль 02 отвечает на вопрос "**что это за тип съёмки?**" (interview, B-roll, driving).
Модуль 05 отвечает на вопрос "**где это и какое настроение?**" (офис, вечер, деловой).

Используется тот же CLIP, но с другими текстовыми промптами — фокус на окружении, а не на типе кадра.

### Три измерения:
1. **Location** — физическое место
2. **Mood/Atmosphere** — визуальное настроение
3. **Time of day** — по освещению

## Применимость к YTAI

**Хорошо подходит (8/10)** — для поиска B-roll по контексту.

### Таксономия Location:
```python
LOCATIONS = [
    # Outdoor urban
    "modern city street with skyscrapers",
    "residential neighborhood with houses",
    "highway or major road with traffic",
    "parking lot or garage",
    "construction site",

    # Outdoor nature
    "desert landscape with sand",
    "lake or waterfront",
    "park or garden with trees",
    "beach or coastline",

    # Indoor professional
    "modern office with desks and computers",
    "meeting room or conference room",
    "co-working space or cafe",
    "real estate agency or showroom",

    # Indoor residential
    "luxury apartment living room",
    "modern kitchen with appliances",
    "bathroom with fixtures",
    "bedroom with bed and furniture",
    "balcony or terrace with city view",

    # Indoor commercial
    "restaurant or dining area",
    "coffee shop or cafe interior",
    "hotel lobby or reception",
    "shopping mall or retail store",
]
```

### Таксономия Mood:
```python
MOODS = [
    "professional and formal business setting",
    "casual and relaxed atmosphere",
    "luxurious and upscale environment",
    "energetic and dynamic scene",
    "calm and peaceful scenery",
    "busy and crowded urban scene",
]
```

### Таксономия Time of Day:
```python
TIME_OF_DAY = [
    "bright daylight outdoor scene",
    "golden hour warm sunset lighting",
    "blue hour twilight sky",
    "nighttime with artificial lights",
    "indoor artificial lighting",
]
```

### Пример на YTCR01:
```
scene_000.jpg:
  location: "lake or waterfront" (0.82)
  mood: "calm and peaceful" (0.77)
  time: "bright daylight" (0.90)

scene_003.jpg:
  location: "modern office with desks" (0.85)
  mood: "professional and formal" (0.80)
  time: "indoor artificial lighting" (0.88)

scene_015.jpg:
  location: "luxury apartment living room" (0.79)
  mood: "luxurious and upscale" (0.74)
  time: "bright daylight" (0.65)
```

## Вход / Выход

### Вход
- Keyframe images (те же что в модуле 02)
- Модель CLIP уже загружена (переиспользуем)

### Выход
```json
{
  "scene_idx": 0,
  "location": "lake_waterfront",
  "location_full": "lake or waterfront",
  "location_confidence": 0.82,
  "mood": "calm_peaceful",
  "mood_confidence": 0.77,
  "time_of_day": "daylight",
  "time_confidence": 0.90
}
```

## Пример кода

```python
# Переиспользуем модель CLIP из модуля 02
# model и preprocess уже загружены

LOCATIONS = [
    "modern city street with skyscrapers",
    "lake or waterfront",
    "modern office with desks and computers",
    "luxury apartment living room",
    "restaurant or coffee shop interior",
    "desert landscape with sand",
    "highway or road with traffic",
]

LOCATION_LABELS = [
    "city_street", "lake_waterfront", "office",
    "apartment_interior", "restaurant", "desert", "highway",
]

MOODS = [
    "professional and formal", "casual and relaxed",
    "luxurious and upscale", "energetic and dynamic",
    "calm and peaceful", "busy and crowded",
]

MOOD_LABELS = [
    "formal", "casual", "luxury", "energetic", "calm", "busy",
]

def classify_scene_context(image_path, model, preprocess, device):
    """Classify location, mood, and time of day."""
    image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)

    def get_best(labels, texts):
        text_tokens = clip.tokenize(texts).to(device)
        with torch.no_grad():
            logits, _ = model(image, text_tokens)
            probs = logits.softmax(dim=-1).cpu().numpy()[0]
        idx = probs.argmax()
        return labels[idx], round(float(probs[idx]), 3)

    location, loc_conf = get_best(LOCATION_LABELS, LOCATIONS)
    mood, mood_conf = get_best(MOOD_LABELS, MOODS)

    return {
        "location": location,
        "location_confidence": loc_conf,
        "mood": mood,
        "mood_confidence": mood_conf,
    }
```

## Производительность

Практически **бесплатный** — CLIP уже загружен, это просто дополнительные forward pass'ы:

| Метрика | Значение |
|---------|---------|
| Доп. время на кадр | ~10-20ms (MPS) |
| 50 кадров | ~1 сек |
| 40 проектов | ~1 мин |

## Зависимости

Те же что в модуле 02 (CLIP, torch). Никаких дополнительных.

## Ценность для B-roll поиска

Позволяет искать по контексту:
```bash
# Найди кадры с озером на закате
search --location lake_waterfront --time golden_hour

# Найди роскошные интерьеры
search --location apartment_interior --mood luxury

# Найди деловые кадры для YTCG
search --mood formal --channel YTCG
```

## Приоритет

**Core** — минимальные дополнительные затраты (CLIP уже загружен), значительно обогащает метаданные для поиска.
