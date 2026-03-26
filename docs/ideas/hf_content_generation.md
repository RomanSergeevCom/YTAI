# Генерация контента: музыка, изображения, видео

Модели для создания контента — тамбнейлы, фоновая музыка, звуковые эффекты.

---

## 1. Тамбнейлы и B-roll изображения

### FLUX.1-schnell (рекомендуется)

Самая быстрая text-to-image модель на Mac через MLX.

```bash
# Установка
pip install mflux

# Генерация
mflux-generate \
  --model schnell \
  --prompt "Dubai desert sunset, golden dunes, cinematic wide shot, 4K" \
  --width 1920 --height 1080 \
  --steps 4 \
  --output thumbnail.png
```

**Python API:**
```python
from mflux import Flux1, Config

flux = Flux1(model_alias="schnell", quantize=8)
image = flux.generate_image(
    seed=42,
    prompt="Dubai desert sunset, golden dunes, cinematic wide shot",
    config=Config(width=1920, height=1080, num_inference_steps=4)
)
image.save("thumbnail.png")
```

**Размер:** ~12 GB (скачивается один раз)
**Скорость:** ~30 сек на M2 Pro (4 steps)
**Качество:** Отличное для тамбнейлов и B-roll

### SDXL 1.0 (альтернатива)

Больше экосистема (ControlNet, IP-Adapter, LoRA).

```python
from diffusers import StableDiffusionXLPipeline
import torch

pipe = StableDiffusionXLPipeline.from_pretrained(
    "stabilityai/stable-diffusion-xl-base-1.0",
    torch_dtype=torch.float16
).to("mps")

image = pipe("cinematic portrait, warm lighting, interview setup").images[0]
```

**Размер:** ~7 GB
**Скорость:** ~45 сек на M2 Pro
**Плюс:** ControlNet для точного контроля композиции

### Применение в пайплайне

- `Stage 06: Thumbnails` — генерация вариантов тамбнейлов по описанию из brief
- `Stage 05: Screen Cues` — фоновые изображения для overlays (вместо градиентов)
- `Stage 07: Shorts` — обложки для Shorts

---

## 2. Фоновая музыка

### MusicGen-medium (рекомендуется)

```python
from transformers import AutoProcessor, MusicgenForConditionalGeneration

processor = AutoProcessor.from_pretrained("facebook/musicgen-medium")
model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-medium")

inputs = processor(
    text=["upbeat corporate background music, light and positive"],
    padding=True,
    return_tensors="pt"
)

audio = model.generate(**inputs, max_new_tokens=1500)  # ~30 сек

# Сохранить
import scipy
scipy.io.wavfile.write("background.wav", rate=32000, data=audio[0, 0].numpy())
```

**Размер:** 3.3 GB
**Скорость:** ~30 сек для 10 сек музыки (MPS)
**Качество:** Хорошее для фона, не для основного трека

### MusicGen-melody (с мелодией-референсом)

Можно дать аудио-референс → модель создаёт музыку в похожем стиле.

```python
inputs = processor(
    text=["ambient electronic, Dubai vibes, cinematic"],
    audio=reference_audio,  # numpy array или torch tensor
    sampling_rate=32000,
    return_tensors="pt"
)
```

### Stable Audio Open (для длинных треков)

До 47 секунд одним запросом.

```python
from stable_audio_tools import get_pretrained_model
from stable_audio_tools.inference.generation import generate_diffusion_cond

model, model_config = get_pretrained_model("stabilityai/stable-audio-open-1.0")
```

**Размер:** 1.2 GB

### Применение

- Генерация intro/outro музыки для каналов
- Фоновая музыка для B-roll секций
- Музыка для Shorts

**Важно:** Все модели генерируют royalty-free контент, но лицензии нужно проверить для коммерческого использования.

---

## 3. Звуковые эффекты

### AudioGen-medium

```python
from audiocraft.models import AudioGen

model = AudioGen.get_pretrained("facebook/audiogen-medium")
model.set_generation_params(duration=5)  # 5 секунд

descriptions = [
    "car engine starting and driving away",
    "ocean waves on a sandy beach",
    "crowd cheering in a stadium"
]

audio = model.generate(descriptions)
# audio shape: [3, 1, samples]
```

**Размер:** 3.3 GB
**Скорость:** ~15 сек для 5 сек аудио
**Качество:** Хорошее для ambient SFX, хуже для точных звуков

### Применение

- Ambient звуки для B-roll (ветер, трафик, природа)
- Переходные звуки (whoosh, click)
- Заполнение тишины в interview cuts

---

## 4. Видео генерация

### Текущее состояние (2026)

| Модель | Размер | Mac M-series | Практичность |
|---|---|---|---|
| CogVideoX-2b | ~4 GB | Возможно (32GB RAM) | Очень медленно (~5 мин на 4 сек) |
| CogVideoX-5b | ~10 GB | Нет (мало RAM) | Непрактично локально |

**Вердикт:** Видеогенерация пока непрактична для локального Mac. Лучше использовать облачные API (Runway, Kling, Pika) если нужно.

---

## Сводная таблица

| Задача | Модель | Размер | Время | Практичность |
|---|---|---|---|---|
| Тамбнейл | FLUX.1-schnell | 12 GB | 30 сек | Высокая |
| Фон музыка | MusicGen-medium | 3.3 GB | 30 сек/10с | Средняя |
| SFX | AudioGen-medium | 3.3 GB | 15 сек/5с | Средняя |
| Видео | CogVideoX-2b | 4 GB | 5 мин/4с | Низкая |

**Суммарно на диске:** ~22 GB для всех моделей генерации
