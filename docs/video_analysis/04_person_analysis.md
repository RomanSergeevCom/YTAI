# 04. Person Analysis — Анализ людей в кадре

## Что делает

Определяет позу тела (стоит, сидит, жестикулирует), эмоции на лице (улыбка, серьёзность, удивление), количество и расположение лиц — для понимания "что делают люди в кадре".

## Библиотеки

### MediaPipe (поза + лицо + руки)
- https://github.com/google-ai-edge/mediapipe
- GitHub Stars: ~28,000
- Лицензия: Apache-2.0
- Разработчик: Google
- Работает на CPU, быстрый

### DeepFace (эмоции)
- https://github.com/serengil/deepface
- GitHub Stars: ~16,000
- Лицензия: MIT
- 7 эмоций: angry, disgust, fear, happy, sad, surprise, neutral

### Альтернатива: InsightFace
- https://github.com/deepinsight/insightface
- GitHub Stars: ~24,000
- Более точный face detection + recognition

## Как работает

### MediaPipe Pose
- Детектирует 33 ключевые точки тела (плечи, локти, запястья, бёдра, колени...)
- По расположению точек определяет: стоит, сидит, наклонился, поднял руку
- Работает покадрово, ~30ms на кадр (CPU)

### MediaPipe Face Mesh
- 468 точек лица (контуры глаз, бровей, рта, носа)
- Определяет: куда смотрит, открыт ли рот, поднял ли брови
- Позволяет вычислить: eye-line direction, head tilt

### DeepFace
- CNN классификатор эмоций по лицу
- Вход: crop лица, выход: вероятности 7 эмоций
- Быстрый, но может ошибаться на мелких лицах

## Применимость к YTAI

**Полезно (7/10)** — для интервью контента.

### Что можно извлечь:

| Метрика | Как используется |
|---------|-----------------|
| **Pose: сидит/стоит** | Interview = сидит; property tour = стоит/идёт |
| **Жестикуляция** | Момент с активной жестикуляцией → эмоциональный пик |
| **Эмоция: happy** | Лучшие моменты для Shorts / thumbnail |
| **Эмоция: surprise** | Потенциальные hook-моменты |
| **Face count** | 0 = B-roll, 1 = solo interview, 2 = dialogue |
| **Eye direction** | Смотрит в камеру vs на собеседника |

### Пример на YTCR01 (интервью с агентом):
```
scene_001.jpg → faces: 1, emotion: neutral, pose: sitting, looking: camera
scene_003.jpg → faces: 2, emotion: [happy, neutral], pose: [sitting, sitting]
scene_015.jpg → faces: 1, emotion: surprise, pose: sitting, gesturing: true
  → ^^^ потенциальный hook-момент!
scene_030.jpg → faces: 0
  → B-roll (подтверждает CLIP)
```

### Ограничения:
- **Мелкие лица**: если человек далеко (establishing shot) — не детектируется
- **Профиль**: MediaPipe лучше работает с фронтальным лицом
- **Driving footage**: нет лиц → модуль пропускает (это нормально, CLIP уже определил тип)

## Вход / Выход

### Вход
- Keyframe images: `Setup/Frames/{clip_id}/scene_NNN.jpg`
- Только кадры где YOLO нашёл `person_count > 0` (оптимизация)

### Выход
```json
{
  "scene_idx": 3,
  "faces": [
    {
      "face_idx": 0,
      "bbox": [120, 50, 350, 320],
      "emotion": "happy",
      "emotion_scores": {"happy": 0.72, "neutral": 0.20, "surprise": 0.05},
      "head_pose": {"yaw": -5.2, "pitch": 2.1, "roll": 0.8},
      "looking_at_camera": true
    }
  ],
  "face_count": 1,
  "dominant_emotion": "happy",
  "body_pose": "sitting",
  "is_gesturing": false
}
```

## Пример кода

```python
import mediapipe as mp
from deepface import DeepFace
import cv2

mp_face = mp.solutions.face_detection
mp_pose = mp.solutions.pose

def analyze_person(image_path):
    """Analyze faces and body pose in a keyframe."""
    img = cv2.imread(image_path)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Face detection + emotion
    faces = []
    try:
        analysis = DeepFace.analyze(img, actions=["emotion"], enforce_detection=False, silent=True)
        if isinstance(analysis, list):
            for face in analysis:
                faces.append({
                    "emotion": face["dominant_emotion"],
                    "emotion_scores": {k: round(v, 2) for k, v in face["emotion"].items()},
                    "bbox": [face["region"]["x"], face["region"]["y"],
                             face["region"]["x"] + face["region"]["w"],
                             face["region"]["y"] + face["region"]["h"]],
                })
    except Exception:
        pass

    # Body pose
    pose_label = "unknown"
    with mp_pose.Pose(static_image_mode=True) as pose:
        results = pose.process(rgb)
        if results.pose_landmarks:
            # Simple sitting vs standing heuristic:
            # If hip Y > 0.6 of image height → sitting
            hip_y = results.pose_landmarks.landmark[mp_pose.PoseLandmark.LEFT_HIP].y
            pose_label = "sitting" if hip_y > 0.55 else "standing"

    return {
        "faces": faces,
        "face_count": len(faces),
        "dominant_emotion": faces[0]["emotion"] if faces else None,
        "body_pose": pose_label,
    }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| MediaPipe Pose (CPU) | ~30ms/кадр |
| DeepFace emotion (CPU) | ~100-200ms/кадр |
| Всего на кадр | ~150-250ms |
| 50 кадров (1 клип) | ~10 сек |
| 40 проектов (~2000 кадров) | ~7 мин |

Оптимизация: запускать только на кадрах где `person_count > 0` (от YOLO) → пропускаем ~40% B-roll кадров.

## Зависимости

```bash
pip install mediapipe      # ~30MB
pip install deepface       # ~20MB + скачает модели при первом запуске (~100MB)
# OpenCV уже установлен
```

## Приоритет

**Core** — face_count и emotion полезны для поиска "лучших моментов" и подтверждения B-roll/interview классификации. Быстрый модуль с минимальными зависимостями.
