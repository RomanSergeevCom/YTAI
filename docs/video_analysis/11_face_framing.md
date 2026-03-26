# 11. Face Framing — Анализ кадрирования лица

## Что делает

Определяет как лицо расположено в кадре: соблюдается ли правило третей, куда направлен взгляд (eye-line), какой процент экранного времени занимает каждый спикер (screen time), оптимальна ли композиция.

## Библиотека

- **MediaPipe Face Mesh** — 468 точек лица (уже установлен из модуля 04)
- **OpenCV** — расчёт композиции
- Без дополнительных зависимостей

## Как работает

1. MediaPipe Face Mesh определяет 468 ландмарков на лице
2. По ландмаркам вычисляется:
   - **Центр лица** — координаты (x, y) в процентах от размера кадра
   - **Rule of thirds** — насколько близко глаза к линии 1/3 сверху
   - **Eye-line direction** — куда смотрит (в камеру, влево, вправо, вниз)
   - **Face size** — % от площади кадра (крупный план vs средний)
   - **Head tilt** — наклон головы (yaw, pitch, roll)

### Rule of Thirds:
В профессиональном видео глаза спикера располагаются на верхней линии третей (y ≈ 33%). Отклонение > 10% — плохое кадрирование.

## Применимость к YTAI

**Нишевое (4/10)** — для QC и улучшения кадрирования.

### Когда полезно:
- **Проверка кадрирования** при съёмке: "в 30% кадров глаза ниже линии третей — нужен пересъём"
- **Screen time баланс**: в интервью с 2 спикерами — кто чаще в кадре
- **Thumbnail selection**: кадры где человек смотрит в камеру + правило третей = лучший thumbnail

### Пример:
```
scene_001.jpg:
  eye_y_ratio: 0.31  (близко к 1/3 → хорошо)
  looking_at: "camera"
  face_size: 0.15  (15% кадра → средний план)
  thirds_score: 0.92 (отлично)

scene_025.jpg:
  eye_y_ratio: 0.45  (ниже 1/3 → плохое кадрирование)
  looking_at: "right"
  face_size: 0.08  (8% → общий план)
  thirds_score: 0.55 (слабо)
```

## Вход / Выход

### Выход
```json
{
  "scene_idx": 1,
  "face_framing": {
    "eye_y_ratio": 0.31,
    "eye_x_ratio": 0.45,
    "looking_at": "camera",
    "face_size_ratio": 0.15,
    "head_tilt_degrees": 2.5,
    "thirds_score": 0.92,
    "composition_quality": "good"
  }
}
```

## Пример кода

```python
import mediapipe as mp
import cv2

mp_face_mesh = mp.solutions.face_mesh

def analyze_face_framing(image_path):
    """Analyze face position and composition."""
    img = cv2.imread(image_path)
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2) as face_mesh:
        results = face_mesh.process(rgb)
        if not results.multi_face_landmarks:
            return {"face_framing": None}

        face = results.multi_face_landmarks[0]
        # Eye landmarks: left=33, right=263
        left_eye = face.landmark[33]
        right_eye = face.landmark[263]
        eye_y = (left_eye.y + right_eye.y) / 2
        eye_x = (left_eye.x + right_eye.x) / 2

        # Rule of thirds score (eyes at y=0.33 is ideal)
        thirds_score = 1.0 - min(abs(eye_y - 0.333) / 0.15, 1.0)

        # Face size (bounding box area)
        xs = [lm.x for lm in face.landmark]
        ys = [lm.y for lm in face.landmark]
        face_w = max(xs) - min(xs)
        face_h = max(ys) - min(ys)
        face_size = face_w * face_h

        # Eye direction (nose tip=1 vs eye center)
        nose = face.landmark[1]
        dx = nose.x - eye_x
        if abs(dx) < 0.02:
            looking_at = "camera"
        elif dx > 0:
            looking_at = "right"
        else:
            looking_at = "left"

        return {
            "face_framing": {
                "eye_y_ratio": round(eye_y, 3),
                "eye_x_ratio": round(eye_x, 3),
                "looking_at": looking_at,
                "face_size_ratio": round(face_size, 3),
                "thirds_score": round(thirds_score, 2),
            }
        }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Скорость | ~50ms/кадр |
| Только на кадрах с лицами | ~60% от общего числа |
| 40 проектов | ~3 мин |

## Зависимости

```bash
# Уже установлено из модуля 04:
# mediapipe, opencv-python
```

## Приоритет

**Nice-to-have** — для QC и thumbnail selection. Не критично для B-roll поиска.
