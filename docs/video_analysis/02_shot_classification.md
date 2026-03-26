# 02. Shot Type Classification — Классификация типа кадра

## Что делает

Определяет тип каждого кадра (interview, B-roll, driving POV, aerial, interior tour и т.д.) без предварительного обучения — zero-shot классификация по текстовым описаниям.

## Библиотека

- **CLIP (Contrastive Language-Image Pre-Training)** — https://github.com/openai/CLIP
- GitHub Stars: ~33,000
- Лицензия: MIT
- Разработчик: OpenAI
- Модель: ViT-B/32 (рекомендуемая) или ViT-L/14 (точнее, медленнее)
- Альтернативы:
  - **SigLIP** (Google) — новее, чуть точнее
  - **CLIFS** (https://github.com/johanmodin/clifs, 480 stars) — CLIP-based video search

## Как работает

CLIP обучен на 400 миллионах пар "картинка + текстовое описание" из интернета. Модель понимает визуальные концепции через текст.

### Принцип zero-shot классификации:
1. Вы определяете текстовые метки (таксономию): `["interview talking head", "driving POV", "aerial drone shot"]`
2. CLIP кодирует картинку в вектор (image embedding)
3. CLIP кодирует каждую метку в вектор (text embedding)
4. Cosine similarity между image и каждым text → скоры
5. Метка с наибольшим скором = тип кадра

**Ничего не нужно обучать.** Таксономию можно менять на лету — просто меняете текстовые описания.

## Применимость к YTAI

**Идеально подходит (9/10)** — ядро B-roll библиотеки.

### Таксономия для каналов YTAI

#### Универсальная (все каналы):
```python
SHOT_TYPES = [
    # Interview
    "interview talking head close-up of one person speaking",
    "interview with two people talking to each other",
    "interview medium shot of person at desk or table",

    # B-roll — City / Architecture
    "B-roll establishing shot of city skyline",
    "B-roll exterior of building or skyscraper",
    "B-roll aerial drone shot of city or landscape",

    # B-roll — Movement
    "B-roll driving POV from inside a car on road",
    "B-roll walking through street or market",
    "B-roll tracking shot following a person",

    # B-roll — Interior
    "B-roll interior of apartment or house room tour",
    "B-roll interior of office or meeting room",
    "B-roll interior of restaurant or coffee shop",

    # B-roll — Nature / Landscape
    "B-roll nature landscape desert or lake",
    "B-roll sunset or sunrise sky",

    # B-roll — Close-ups
    "close-up of food or drinks on table",
    "close-up of hands typing on laptop or phone",
    "close-up of document or business card",

    # Technical
    "screen recording or presentation slide",
    "text graphic or title card overlay",
]
```

#### Дополнительно для YTCR (недвижимость):
```python
YTCR_EXTRA = [
    "real estate property swimming pool",
    "real estate luxury bathroom",
    "real estate modern kitchen",
    "construction site or development area",
]
```

#### Дополнительно для YTCG (бизнес/Саудовская Аравия):
```python
YTCG_EXTRA = [
    "Saudi Arabian city or building",
    "traditional Arabic coffee ceremony",
    "business meeting or handshake",
]
```

### Пример результата на YTCR01:
```
scene_000.jpg → "B-roll nature landscape desert or lake" (0.85)
scene_001.jpg → "interview talking head close-up" (0.92)
scene_002.jpg → "B-roll driving POV from inside a car" (0.89)
scene_003.jpg → "interview with two people talking" (0.88)
scene_004.jpg → "B-roll establishing shot of city skyline" (0.91)
scene_005.jpg → "B-roll interior of apartment room tour" (0.78)
```

## Вход / Выход

### Вход
- Keyframe images: `Setup/Frames/{clip_id}/scene_NNN.jpg`
- Таксономия: список текстовых описаний

### Выход
- Для каждого keyframe:
  - `shot_type` — лучшая метка (упрощённая, без "B-roll")
  - `shot_type_full` — полная метка
  - `shot_confidence` — скор (0.0 — 1.0)
  - `shot_top3` — топ-3 метки со скорами
  - `is_broll` — true если тип ≠ interview/talking_head

### Формат выхода (дополняет scenes.json)
```json
{
  "scene_idx": 2,
  "shot_type": "driving_pov",
  "shot_type_full": "B-roll driving POV from inside a car on road",
  "shot_confidence": 0.89,
  "shot_top3": [
    ["driving_pov", 0.89],
    ["walking_street", 0.05],
    ["tracking_shot", 0.03]
  ],
  "is_broll": true
}
```

## Пример кода

```python
import clip
import torch
from PIL import Image

# Загрузка модели (один раз, ~350MB download)
device = "mps" if torch.backends.mps.is_available() else "cpu"
model, preprocess = clip.load("ViT-B/32", device=device)

SHOT_TYPES = [
    "interview talking head close-up of one person speaking",
    "B-roll driving POV from inside a car on road",
    "B-roll establishing shot of city skyline",
    "B-roll aerial drone shot of city or landscape",
    "B-roll interior of apartment or house room tour",
    "close-up of food or drinks on table",
    "screen recording or presentation slide",
]

# Сокращённые названия для БД
SHOT_LABELS = [
    "interview_closeup", "driving_pov", "city_skyline",
    "aerial_drone", "interior_tour", "food_closeup", "screen_recording",
]

def classify_frame(image_path):
    """Classify a single keyframe against shot type taxonomy."""
    image = preprocess(Image.open(image_path)).unsqueeze(0).to(device)
    text = clip.tokenize(SHOT_TYPES).to(device)

    with torch.no_grad():
        logits_per_image, _ = model(image, text)
        probs = logits_per_image.softmax(dim=-1).cpu().numpy()[0]

    results = sorted(zip(SHOT_LABELS, probs), key=lambda x: -x[1])
    return {
        "shot_type": results[0][0],
        "shot_confidence": round(float(results[0][1]), 3),
        "shot_top3": [[label, round(float(score), 3)] for label, score in results[:3]],
        "is_broll": "interview" not in results[0][0],
    }
```

## Производительность

| Метрика | ViT-B/32 (CPU) | ViT-B/32 (MPS) | ViT-L/14 (MPS) |
|---------|---------------|---------------|----------------|
| Скорость | ~0.5 сек/кадр | ~0.05 сек/кадр | ~0.15 сек/кадр |
| Модель | 350 MB | 350 MB | 900 MB |
| RAM | ~1 GB | ~1 GB | ~2 GB |
| 50 кадров (1 клип) | ~25 сек | ~2.5 сек | ~7.5 сек |
| 40 проектов (~2000 кадров) | ~17 мин | ~2 мин | ~5 мин |

Рекомендация: ViT-B/32 на MPS (Apple Silicon) — оптимальный баланс скорости и качества.

## Зависимости

```bash
pip install git+https://github.com/openai/CLIP.git
pip install torch torchvision  # вероятно уже установлены от Whisper

# Модель скачивается автоматически при первом вызове clip.load()
# Размер: ~350MB (ViT-B/32), кешируется в ~/.cache/clip/
```

## Настройка таксономии

### Лучшие практики для текстовых описаний:
1. **Длинные описания точнее коротких**: "B-roll driving POV from inside a car on road" лучше чем "driving"
2. **Добавьте контекст**: "interview talking head close-up of one person speaking" лучше чем "person"
3. **Используйте английский**: CLIP обучен преимущественно на английском
4. **Тестируйте на реальных кадрах**: запустите на 10-20 keyframes, подправьте описания

### Итеративная настройка:
Если CLIP путает interior_tour и interview (оба indoor с людьми):
- Усильте различие: "one person speaking directly to camera" vs "empty room interior with furniture"
- Добавьте негативный контекст через prompt engineering

## Приоритет

**Core** — это ядро B-roll библиотеки. Без классификации типов кадров поиск невозможен.
