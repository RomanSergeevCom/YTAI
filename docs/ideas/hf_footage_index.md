# Индексация и поиск футажей по текстовому запросу (Stage 04)

Цель: обработать все отснятые видео → построить индекс → искать по запросу типа "пустыня на закате", "два человека за столом", "крупный план кофе".

---

## Архитектура

```
Footage (MP4 files)
    ↓
[1. Frame Extraction] — ffmpeg, 1 fps или scene-change detection
    ↓
[2. Frame Embedding] — SigLIP2 → 1024-dim vector per frame
    ↓
[3. Vector Index] — ChromaDB / FAISS → text-to-image search
    ↓
[4. Rich Captioning] — Qwen2.5-VL-3B → текстовое описание каждого shot
    ↓
[5. Object Detection] — Florence-2 → теги объектов с bbox
    ↓
[6. Full-text Index] — caption + tags → поиск по тексту
    ↓
Search: query → [vector search + text search] → ranked frames с timecodes
```

**Два уровня поиска:**
- **Быстрый (vector):** "desert sunset" → SigLIP embed → nearest frames
- **Точный (text):** "two people talking at a table with coffee" → search captions

---

## Основные модели

### Tier 1: Frame Embedding (backbone поиска)

#### SigLIP2-so400m — РЕКОМЕНДУЕТСЯ
- **HF:** `google/siglip2-so400m-patch14-384`
- **Размер:** 878M params, ~1.7 GB
- **Что:** Image-text contrastive model (лучше CLIP по всем бенчмаркам)
- **Скорость:** 50-80 fps на M3 Max
- **Качество:** Best-in-class для open-vocabulary image-text matching

```python
from transformers import AutoModel, AutoProcessor
import torch

model = AutoModel.from_pretrained("google/siglip2-so400m-patch14-384")
processor = AutoProcessor.from_pretrained("google/siglip2-so400m-patch14-384")

# Embed кадр
image = Image.open("frame_0042.jpg")
inputs = processor(images=image, return_tensors="pt")
with torch.no_grad():
    image_emb = model.get_image_features(**inputs)  # [1, 1024]

# Embed текстовый запрос
inputs = processor(text="desert sunset with golden dunes", return_tensors="pt")
with torch.no_grad():
    text_emb = model.get_text_features(**inputs)  # [1, 1024]

# Similarity
score = torch.cosine_similarity(image_emb, text_emb)
```

#### Альтернативы
| Модель | Размер | Скорость | Качество | Заметки |
|---|---|---|---|---|
| OpenAI CLIP ViT-L/14-336 | 1.7 GB | 80-120 fps | Хорошее | Огромная экосистема |
| Apple DFN5B-CLIP-ViT-H | 2 GB | 40-60 fps | Отличное | Оптимизирован для Apple |
| MetaCLIP-2 Huge | 2 GB | 40-60 fps | Отличное | Мультиязычный (ru queries!) |
| EVA-02 CLIP Large | 1.2 GB | 100+ fps | Хорошее | Самый быстрый |

**Для русских запросов:** MetaCLIP-2 лучше — тренирован на мультиязычных данных.

---

### Tier 2: Rich Captioning (описание кадров)

#### Qwen2.5-VL-3B-Instruct — РЕКОМЕНДУЕТСЯ
- **HF:** `Qwen/Qwen2.5-VL-3B-Instruct`
- **Размер:** 3B params, ~6 GB (bf16), ~3 GB (AWQ 4-bit)
- **Что:** Vision-Language LLM — описывает кадры, отвечает на вопросы, понимает видео
- **Скорость:** 2-5 сек/кадр
- **Качество:** Лучший в своём классе по детализации

```python
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor

model = Qwen2VLForConditionalGeneration.from_pretrained(
    "Qwen/Qwen2.5-VL-3B-Instruct-AWQ",  # 4-bit quantized
    torch_dtype=torch.float16
).to("mps")
processor = AutoProcessor.from_pretrained("Qwen/Qwen2.5-VL-3B-Instruct-AWQ")

messages = [{
    "role": "user",
    "content": [
        {"type": "image", "image": "frame_0042.jpg"},
        {"type": "text", "text": "Describe this frame in detail: setting, people, actions, objects, lighting, camera angle. Be specific and concise."}
    ]
}]

text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = processor(text=[text], images=[image], return_tensors="pt").to("mps")
output = model.generate(**inputs, max_new_tokens=200)
caption = processor.decode(output[0], skip_special_tokens=True)
# "Medium shot of two men seated at a wooden table in a dimly lit restaurant.
#  The man on the left wears a white shirt and gestures with his right hand.
#  Warm tungsten lighting from overhead pendant lamps. Coffee cups on the table.
#  Camera is slightly elevated, eye-level framing."
```

#### Moondream2 — для быстрой массовой обработки
- **HF:** `vikhyatk/moondream2`
- **Размер:** 1.86B params, ~3.7 GB
- **Скорость:** 0.5-1 сек/кадр (2-5x быстрее Qwen)
- **Качество:** Хорошее, менее детальное
- **Бонус:** Встроенный object detection (возвращает bounding boxes)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model = AutoModelForCausalLM.from_pretrained("vikhyatk/moondream2", trust_remote_code=True)
tokenizer = AutoTokenizer.from_pretrained("vikhyatk/moondream2")

answer = model.answer_question(
    model.encode_image(image),
    "Describe what you see.",
    tokenizer
)
```

#### SmolVLM2-2.2B — для видеопонимания
- **HF:** `HuggingFaceTB/SmolVLM2-2.2B-Instruct`
- **Размер:** 2.2B params, ~4.4 GB
- **Что:** Понимает видео как последовательность (не только отдельные кадры)
- **Зачем:** Запросы типа "камера панорамирует пустыню" или "человек встаёт и уходит"

---

### Tier 3: Object Detection (теги объектов)

#### Florence-2-large — РЕКОМЕНДУЕТСЯ (всё-в-одном)
- **HF:** `microsoft/Florence-2-large`
- **Размер:** 770M params, ~1.5 GB
- **Что:** Один model для: captioning, detection, segmentation, OCR
- **Скорость:** 5-15 fps detection, 3-5 fps captioning

```python
from transformers import AutoModelForCausalLM, AutoProcessor

model = AutoModelForCausalLM.from_pretrained("microsoft/Florence-2-large", trust_remote_code=True)
processor = AutoProcessor.from_pretrained("microsoft/Florence-2-large", trust_remote_code=True)

# Object detection
prompt = "<OD>"
inputs = processor(text=prompt, images=image, return_tensors="pt")
output = model.generate(**inputs, max_new_tokens=1024)
result = processor.batch_decode(output, skip_special_tokens=False)[0]
# Возвращает: {objects: [{label: "person", bbox: [x1,y1,x2,y2]}, {label: "table"}, ...]}

# Dense region captioning
prompt = "<DENSE_REGION_CAPTION>"
# → описание каждой области кадра

# OCR (текст в кадре)
prompt = "<OCR>"
# → весь текст в кадре (вывески, субтитры, overlay text)
```

#### Grounding DINO — open-vocabulary detection
- **HF:** `IDEA-Research/grounding-dino-base`
- **Размер:** 341M, ~700 MB
- **Что:** Детекция ЛЮБОГО объекта по текстовому запросу
- **Зачем:** "Найди все кадры где есть фламинго" → Grounding DINO ищет по запросу

```python
from transformers import AutoProcessor, GroundingDinoForObjectDetection

processor = AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-base")
model = GroundingDinoForObjectDetection.from_pretrained("IDEA-Research/grounding-dino-base")

inputs = processor(images=image, text="person. coffee cup. car.", return_tensors="pt")
outputs = model(**inputs)
# → bounding boxes для всех найденных объектов
```

#### YOLO-World — самый быстрый
- **Размер:** 50-200 MB
- **Скорость:** 30-100 fps (!)
- **Зачем:** Пробежать ВСЕ кадры за секунды, потом Grounding DINO для уточнения

---

## Vector Database

### ChromaDB — РЕКОМЕНДУЕТСЯ для старта

```python
import chromadb

client = chromadb.PersistentClient(path="./footage_index")
collection = client.get_or_create_collection(
    name="frames",
    metadata={"hnsw:space": "cosine"}
)

# Добавить кадры
collection.add(
    ids=["YTCR01_C5402_00042"],
    embeddings=[frame_embedding.tolist()],
    metadatas=[{
        "project": "YTCR01",
        "clip": "C5402.MP4",
        "timecode_sec": 42.0,
        "caption": "Two men at a restaurant table...",
        "objects": "person, table, coffee_cup, lamp",
        "shot_type": "medium",
        "scene_type": "indoor_restaurant"
    }]
)

# Поиск по тексту (через SigLIP embedding)
results = collection.query(
    query_embeddings=[text_embedding.tolist()],
    n_results=20,
    where={"project": "YTCR01"}  # фильтр по проекту
)
```

### FAISS — для масштаба (миллионы кадров)

```python
import faiss
import numpy as np

# Создать индекс
dim = 1024  # SigLIP embedding size
index = faiss.IndexFlatIP(dim)  # Inner product (cosine after L2 norm)

# Добавить embeddings
embeddings = np.array(all_frame_embeddings, dtype='float32')
faiss.normalize_L2(embeddings)
index.add(embeddings)

# Поиск
query = np.array([text_embedding], dtype='float32')
faiss.normalize_L2(query)
scores, indices = index.search(query, k=20)
```

**Установка:** `pip install faiss-cpu chromadb`

---

## Формат выходных данных

### footage_index.json (per project)

```json
{
  "project": "YTCR01",
  "indexed_at": "2026-03-26T14:00:00Z",
  "clips": [
    {
      "filename": "C5402.MP4",
      "duration_sec": 156.0,
      "frames_indexed": 156,
      "shots": [
        {
          "shot_id": 1,
          "start_sec": 0.0,
          "end_sec": 15.3,
          "keyframe_sec": 7.5,
          "caption": "Medium shot of two men at a restaurant table. Warm tungsten lighting. The host gestures while speaking. Coffee cups on the table.",
          "objects": ["person", "person", "table", "coffee_cup", "lamp", "menu"],
          "shot_type": "medium",
          "scene_type": "indoor_restaurant",
          "persons_count": 2,
          "has_face": true,
          "is_talking_head": true,
          "embedding_id": "YTCR01_C5402_s001"
        },
        {
          "shot_id": 2,
          "start_sec": 15.3,
          "end_sec": 22.1,
          "keyframe_sec": 18.5,
          "caption": "Wide aerial shot of desert sand dunes at golden hour. No people. Dramatic shadows.",
          "objects": ["sand_dune", "sky"],
          "shot_type": "wide",
          "scene_type": "outdoor_desert",
          "persons_count": 0,
          "has_face": false,
          "is_talking_head": false,
          "embedding_id": "YTCR01_C5402_s002"
        }
      ]
    }
  ]
}
```

---

## Производительность (M3 Max, 36 GB RAM)

### Обработка 1 часа footage (3600 кадров при 1 fps)

| Шаг | Модель | Кадров | Скорость | Время |
|---|---|---|---|---|
| Frame extraction | ffmpeg | 3600 | мгновенно | ~30 сек |
| SigLIP embedding | SigLIP2-so400m | 3600 | 60 fps | ~1 мин |
| Shot detection | PySceneDetect | 3600 | 100 fps | ~30 сек |
| Captioning | Qwen2.5-VL-3B | ~720 (keyframes) | 0.3 fps | ~40 мин |
| Object detection | Florence-2 | ~720 | 8 fps | ~1.5 мин |
| **Итого** | | | | **~43 мин** |

**С Moondream2 вместо Qwen (быстрее, менее детально):**

| Шаг | Модель | Время |
|---|---|---|
| Captioning | Moondream2 | ~12 мин |
| **Итого** | | **~15 мин** |

### Размер на диске

| Данные | На 1 час footage |
|---|---|
| SigLIP embeddings | ~14 MB |
| Captions (текст) | ~500 KB |
| Object tags | ~200 KB |
| Thumbnail JPEGs (320px) | ~300 MB |
| **Итого (без thumbnails)** | **~15 MB** |
| **Итого (с thumbnails)** | **~315 MB** |

### Размер моделей

| Модель | Размер | Обязательная? |
|---|---|---|
| SigLIP2-so400m | 1.7 GB | Да (backbone) |
| Moondream2 | 3.7 GB | Да (fast captions) |
| Florence-2-large | 1.5 GB | Да (detection) |
| **Минимум** | **~7 GB** | |
| Qwen2.5-VL-3B-AWQ | 3 GB | Опционально (rich captions) |
| Grounding DINO | 700 MB | Опционально (targeted search) |
| SmolVLM2-2.2B | 4.4 GB | Опционально (video understanding) |

---

## Минимальный прототип (MVP)

```bash
# Установка
pip install open_clip_torch transformers chromadb torch torchvision Pillow

# 3 модели скачаются автоматически при первом запуске (~7 GB)
```

### Скрипт: `scripts/04_video_analysis/index_footage.py`

```python
"""
Usage:
    python index_footage.py --project /path/to/YTCR01_Arty_Dzis
    python index_footage.py --project /path/to/YTCR01_Arty_Dzis --query "desert sunset"
"""

# Phase 1: Extract frames (ffmpeg, 1 fps)
# Phase 2: Embed all frames (SigLIP2)
# Phase 3: Caption keyframes (Moondream2 fast / Qwen2.5-VL detailed)
# Phase 4: Detect objects (Florence-2)
# Phase 5: Store in ChromaDB
# Phase 6: Search interface (CLI or HTML)
```

---

## Порядок реализации

### Wave 1 — Vector search (1-2 дня)
1. Frame extraction (ffmpeg, 1 fps)
2. SigLIP2 embedding всех кадров
3. ChromaDB index
4. CLI search: `--query "desert"` → top frames с timecodes

### Wave 2 — Rich captions (2-3 дня)
5. Shot boundary detection (PySceneDetect)
6. Moondream2 captioning keyframes
7. Florence-2 object detection
8. Full-text search поверх captions

### Wave 3 — Integration (1 неделя)
9. HTML viewer (как review.html — кликабельные результаты)
10. Интеграция с brief generation (Claude читает visual_analysis.json)
11. UXP plugin: кнопка "Find B-roll" → поиск по описанию → preview в Source Monitor

### Wave 4 — Scale (по необходимости)
12. Batch processing всех проектов
13. Cross-project search ("покажи все закаты из всех проектов")
14. FAISS вместо ChromaDB (если >100K кадров)
15. Video-level understanding (SmolVLM2 для temporal queries)
