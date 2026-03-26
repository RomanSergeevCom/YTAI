# 14. Content Density — Монтажный темп и энергетика

## Что делает

Агрегирует данные всех модулей для вычисления **монтажного темпа** (cuts per minute), **энергетической кривой** видео, **визуальной сложности** и **ритма** — для понимания динамики видео и сравнения между проектами.

## Библиотека

Не требует отдельных библиотек — агрегация данных из всех модулей + numpy/matplotlib для визуализации.

## Как работает

### Metrics:

**Cuts per minute (CPM):**
```
CPM = total_scenes / video_duration_minutes
```
- < 3 CPM: медленный темп (документальный, лекция)
- 3-8 CPM: нормальный (интервью + B-roll)
- 8-15 CPM: быстрый (динамичный контент)
- \> 15 CPM: очень быстрый (shorts, trailers)

**Energy curve:**
Для каждого 30-секундного окна вычисляется "энергия":
```python
energy = (
    scene_change_rate * 0.3 +    # Кол-во склеек в окне
    speech_energy * 0.3 +         # Громкость речи
    motion_magnitude * 0.2 +      # Движение камеры
    emotion_intensity * 0.2       # Эмоциональность (happy/surprise)
)
```

**Visual complexity:**
- Среднее количество объектов на кадр (YOLO)
- Разнообразие shot types (CLIP)
- Частота смены локаций

## Применимость к YTAI

**Нишевое (3/10)** — для аналитики и сравнения.

### Когда полезно:
- **Сравнение видео**: "это видео на 40% быстрее среднего для канала"
- **Поиск пиков**: "самый энергичный момент на 12:30 — кандидат для Short"
- **Отладка ритма**: "первые 5 минут слишком медленные — нужно добавить B-roll cuts"
- **Benchmark**: средний CPM по каналу, оптимальный темп для retention

### Пример на YTCR01:
```
Total: 47 scenes / 15 min = 3.1 CPM (нормально для интервью)

Energy curve:
  00:00-00:30: ████████░░ 0.80  (intro + establishing)
  00:30-01:00: ██░░░░░░░░ 0.20  (slow interview start)
  01:00-01:30: ████░░░░░░ 0.40
  ...
  05:00-05:30: ██████████ 1.00  (peak: emotional moment + B-roll burst)
  ...
  14:30-15:00: ███████░░░ 0.70  (outro)

→ Peak energy at 05:00 = potential Short candidate
→ Dip at 00:30-01:00 = consider adding B-roll inserts
```

## Вход / Выход

### Вход
- Результаты всех модулей (scenes, CLIP, YOLO, audio, motion)

### Выход
```json
{
  "project_id": "YTCR01",
  "clip_id": "C5402",
  "density": {
    "total_scenes": 47,
    "duration_min": 15.1,
    "cuts_per_minute": 3.1,
    "tempo_label": "normal",
    "broll_ratio": 0.35,
    "interview_ratio": 0.60,
    "transition_ratio": 0.05,
    "avg_scene_duration_sec": 19.3,
    "shortest_scene_sec": 2.1,
    "longest_scene_sec": 133.5,
    "unique_locations": 5,
    "avg_objects_per_scene": 2.3,
    "energy_curve": [
      {"time_sec": 0, "energy": 0.80},
      {"time_sec": 30, "energy": 0.20},
      {"time_sec": 60, "energy": 0.40}
    ],
    "peak_energy_sec": 300,
    "energy_dips": [30, 420]
  }
}
```

## Пример кода

```python
import numpy as np

def compute_content_density(scenes_data, clip_duration_sec):
    """Compute content density metrics from all module results."""
    n_scenes = len(scenes_data)
    duration_min = clip_duration_sec / 60

    cpm = n_scenes / duration_min if duration_min > 0 else 0

    # B-roll ratio
    broll_count = sum(1 for s in scenes_data if s.get("is_broll", False))
    broll_ratio = broll_count / n_scenes if n_scenes > 0 else 0

    # Scene durations
    durations = [s["duration_sec"] for s in scenes_data]

    # Energy curve (30-sec windows)
    window_sec = 30
    n_windows = int(clip_duration_sec / window_sec) + 1
    energy_curve = []
    for w in range(n_windows):
        t_start = w * window_sec
        t_end = t_start + window_sec
        # Count scenes in this window
        window_scenes = [s for s in scenes_data
                        if s["start_sec"] < t_end and s["end_sec"] > t_start]
        scene_rate = len(window_scenes) / (window_sec / 60)  # scenes per min
        energy = min(scene_rate / 10, 1.0)  # normalize
        energy_curve.append({"time_sec": t_start, "energy": round(energy, 2)})

    tempo = "slow" if cpm < 3 else "normal" if cpm < 8 else "fast" if cpm < 15 else "very_fast"

    return {
        "total_scenes": n_scenes,
        "duration_min": round(duration_min, 1),
        "cuts_per_minute": round(cpm, 1),
        "tempo_label": tempo,
        "broll_ratio": round(broll_ratio, 2),
        "avg_scene_duration_sec": round(np.mean(durations), 1) if durations else 0,
        "shortest_scene_sec": round(min(durations), 1) if durations else 0,
        "longest_scene_sec": round(max(durations), 1) if durations else 0,
        "energy_curve": energy_curve,
    }
```

## Производительность

Мгновенно — чистая агрегация данных. <100ms на проект.

## Зависимости

```bash
# Уже установлено: numpy
# Опционально для графиков: pip install matplotlib
```

## Приоритет

**Nice-to-have** — аналитический инструмент, не влияет на B-roll поиск. Полезно для понимания ритма видео и сравнения между проектами.
