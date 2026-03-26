# Video Analysis (Stage 04) — модели для реализации

Stage 04 сейчас полностью TODO. Вот какие модели и подходы доступны.

---

## Архитектура Stage 04

```
Input: Source/Video/*.MP4
  ↓
Step 1: Extract keyframes (FFmpeg, 1 fps or scene-change)
  ↓
Step 2: Scene/shot detection (PySceneDetect)
  ↓
Step 3: Frame classification (CLIP — B-roll vs. talking head vs. montage)
  ↓
Step 4: Face detection + speaker tracking (YOLO11 / MediaPipe)
  ↓
Step 5: Frame captioning (BLIP-2 — описание кадров)
  ↓
Output: {CODE}_visual_analysis.json
```

---

## 1. Shot Boundary Detection — PySceneDetect

**Что:** Обнаружение границ сцен (hard cuts, fades, dissolves).

**Зачем:** Автоматическое разделение видео на shots для Assembly brief. Сейчас определяется вручную.

```python
from scenedetect import detect, ContentDetector, AdaptiveDetector

# Быстрый content-based detection
scenes = detect("video.mp4", ContentDetector(threshold=27))
# [(FrameTimecode(0:00:00), FrameTimecode(0:00:15)), ...]

# Адаптивный (лучше для интервью с разным освещением)
scenes = detect("video.mp4", AdaptiveDetector())
```

**Размер:** Библиотека, ~5 MB. Использует OpenCV.
**Скорость:** ~100 fps на CPU (30 мин видео → ~30 сек).
**Установка:** `pip install scenedetect[opencv]`

---

## 2. CLIP — B-roll Search по описанию

**Что:** Поиск кадров по текстовому описанию ("desert landscape", "close-up of coffee", "two people talking").

**Зачем:**
- Автоматический подбор B-roll к сегментам brief
- Поле `broll_note: "найди кадр: пустыня на закате"` → CLIP находит лучший кадр

```python
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel

model = CLIPModel.from_pretrained("openai/clip-vit-large-patch14")
processor = CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14")

# Извлечь кадры (1 fps)
frames = extract_frames("video.mp4", fps=1)  # PIL Images

# Поиск по описанию
text = "desert landscape at sunset"
inputs = processor(text=[text], images=frames, return_tensors="pt", padding=True)
outputs = model(**inputs)
scores = outputs.logits_per_text.softmax(dim=-1)

# Top 5 кадров
top_indices = scores[0].argsort(descending=True)[:5]
for idx in top_indices:
    print(f"Frame {idx}: score {scores[0][idx]:.3f}, time {idx}s")
```

**Размер:** 890 MB
**Скорость:** ~200 кадров/сек на MPS (Mac)
**Установка:** `pip install transformers torch pillow`

---

## 3. BLIP — авто-описание кадров

**Что:** Автоматическое описание содержимого кадра на английском.

**Зачем:**
- Генерация `visual_description` для каждого shot в visual analysis JSON
- Помощь Claude при создании brief ("этот кадр: два человека за столом, кофе, тёплое освещение")

```python
from transformers import BlipProcessor, BlipForConditionalGeneration
from PIL import Image

processor = BlipProcessor.from_pretrained("Salesforce/blip-image-captioning-large")
model = BlipForConditionalGeneration.from_pretrained("Salesforce/blip-image-captioning-large")

image = Image.open("frame_0042.jpg")
inputs = processor(image, return_tensors="pt")
caption = model.generate(**inputs, max_length=50)
text = processor.decode(caption[0], skip_special_tokens=True)
# "two men sitting at a table in a restaurant having a conversation"
```

**Размер:** 1.8 GB
**Скорость:** ~5 кадров/сек на MPS
**Установка:** `pip install transformers torch pillow`

---

## 4. YOLO11 — face/person detection

**Что:** Обнаружение лиц и людей в кадре.

**Зачем:**
- Определение talking head vs. B-roll (лицо в кадре → talking head)
- Подсчёт людей в кадре (1 = соло, 2 = интервью, 0 = B-roll)
- Размер лица → крупный/средний/общий план

```python
from ultralytics import YOLO

model = YOLO("yolo11n.pt")  # nano (6 MB) или yolo11s.pt (22 MB)
results = model("frame.jpg")

for box in results[0].boxes:
    cls = int(box.cls)  # 0 = person
    conf = float(box.conf)
    x1, y1, x2, y2 = box.xyxy[0]

    if cls == 0:  # person detected
        face_area = (x2 - x1) * (y2 - y1)
        frame_area = results[0].orig_shape[0] * results[0].orig_shape[1]
        ratio = face_area / frame_area

        if ratio > 0.3:
            shot_type = "close-up"
        elif ratio > 0.1:
            shot_type = "medium"
        else:
            shot_type = "wide"
```

**Размер:** 6-50 MB (nano → large)
**Скорость:** ~100 fps (nano) на MPS
**Установка:** `pip install ultralytics`

---

## 5. MediaPipe — жесты и выражения

**Что:** Отслеживание рук, позы, выражений лица.

**Зачем:**
- Детекция жестов говорящего (активная жестикуляция = энергичный момент)
- Эмоции по выражению лица (улыбка = позитивный сегмент)
- Определение направления взгляда (в камеру vs. в сторону)

```python
import mediapipe as mp

mp_face = mp.solutions.face_mesh
face_mesh = mp_face.FaceMesh(
    max_num_faces=2,
    refine_landmarks=True,
    min_detection_confidence=0.5
)

results = face_mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
if results.multi_face_landmarks:
    for face in results.multi_face_landmarks:
        # 478 landmarks per face
        # Можно определить: улыбку, направление взгляда, открытие рта
        pass
```

**Размер:** ~5 MB
**Скорость:** ~30 fps на CPU
**Установка:** `pip install mediapipe`

---

## Выходной формат: visual_analysis.json

```json
{
  "project": "YTCR01",
  "clips": [
    {
      "filename": "C5402.MP4",
      "shots": [
        {
          "shot_id": 1,
          "start_sec": 0.0,
          "end_sec": 15.3,
          "type": "talking_head",
          "shot_type": "medium",
          "persons": 1,
          "caption": "a man sitting at a table talking to camera",
          "energy": 0.65,
          "smile_score": 0.3
        },
        {
          "shot_id": 2,
          "start_sec": 15.3,
          "end_sec": 22.1,
          "type": "broll",
          "shot_type": "wide",
          "persons": 0,
          "caption": "aerial view of desert dunes at golden hour",
          "energy": 0.0,
          "smile_score": null
        }
      ]
    }
  ]
}
```

**Как используется дальше:**
- Claude читает visual_analysis.json при генерации brief
- `broll_note` в brief ссылается на конкретные shots
- UXP может auto-select B-roll shots по CLIP score
- Review HTML показывает thumbnails + captions

---

## Порядок реализации

1. **PySceneDetect** — shot boundaries (самое полезное, 30 мин работы)
2. **YOLO11 nano** — face/person detection → talking head vs. B-roll (1 час)
3. **CLIP** — B-roll search по описанию (2 часа)
4. **BLIP** — авто-описание кадров (1 час, после CLIP)
5. **MediaPipe** — жесты/эмоции (опционально, для продвинутого анализа)

**Суммарный размер моделей:** ~3 GB
**Время обработки 30 мин видео:** ~2-3 мин (все модели)
