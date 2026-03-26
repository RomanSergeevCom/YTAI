# 10. Audio-Visual Sync — Корреляция аудио и видео

## Что делает

Объединяет результаты визуального анализа (CLIP, YOLO) и аудио-анализа (Silero VAD) для надёжной классификации: interview segment vs B-roll insert. Определяет паттерны "говорящая голова + речь" vs "визуальная вставка + музыка/тишина".

## Библиотека

Не требует отдельной библиотеки — это агрегация результатов модулей 01-09.

## Как работает

### Матрица решений:

| Видео (CLIP) | Аудио (VAD) | Результат |
|---|---|---|
| interview | speech | **INTERVIEW** (уверенность: высокая) |
| interview | no speech | **CUTAWAY** (спикер в кадре, но говорит другой) |
| broll | no speech | **B-ROLL** (уверенность: высокая) |
| broll | speech | **VOICE-OVER B-ROLL** (B-roll с закадровым комментарием) |
| any | music only | **TRANSITION / INTRO** |
| any | silence | **DEAD AIR** (потенциальный cut) |

### Scoring:
```python
def classify_segment(clip_result, audio_result, yolo_result):
    is_interview_visual = "interview" in clip_result["shot_type"]
    has_speech = audio_result["speech_ratio"] > 0.3
    person_count = yolo_result["person_count"]

    if is_interview_visual and has_speech and person_count > 0:
        return "interview", 0.95  # Тройное подтверждение
    elif not is_interview_visual and not has_speech:
        return "broll", 0.95     # Тройное подтверждение
    elif not is_interview_visual and has_speech:
        return "voiceover_broll", 0.80
    elif is_interview_visual and not has_speech:
        return "cutaway", 0.70
    else:
        return "ambiguous", 0.50
```

## Применимость к YTAI

**Очень полезно (9/10)** — повышает точность B-roll классификации.

### Проблемы, которые решает:

1. **CLIP ошибается**: кадр с мебелью классифицирован как "interview" (есть стулья) → но аудио = music → на самом деле B-roll интерьер
2. **YOLO не уверен**: person_count=1 в driving footage (отражение в стекле) → но аудио = no speech → B-roll
3. **Ambiguous frames**: человек на балконе с видом на город → interview или B-roll? Аудио решает: если говорит → interview, если нет → B-roll establishing shot

### Пример на YTCR01:
```
scene_005 (05:30-05:55):
  CLIP: "interior_tour" (0.78) → is_broll = true
  YOLO: person=1 → неоднозначно
  Audio: speech_ratio=0.0, music=true → is_broll = true
  FINAL: "broll" (confidence: 0.95) ← аудио подтвердило CLIP

scene_012 (12:00-12:30):
  CLIP: "interview_closeup" (0.85) → is_broll = false
  YOLO: person=1
  Audio: speech_ratio=0.0 → no speech!
  FINAL: "cutaway" (confidence: 0.70) ← спикер слушает, говорит другой
```

## Вход / Выход

### Вход
- Результаты модулей 02 (CLIP), 03 (YOLO), 04 (Person), 09 (Audio)

### Выход
```json
{
  "scene_idx": 5,
  "final_classification": "broll",
  "final_confidence": 0.95,
  "classification_sources": {
    "visual": "broll_interior_tour",
    "audio": "music",
    "person_count": 1,
    "agreement": "visual+audio agree (broll)"
  },
  "is_broll": true,
  "is_interview": false,
  "is_transition": false
}
```

## Пример кода

```python
def fuse_av_classification(clip_result, audio_result, yolo_result):
    """Fuse visual and audio signals for robust classification."""
    shot_type = clip_result["shot_type"]
    is_visual_interview = "interview" in shot_type
    speech_ratio = audio_result.get("speech_ratio", 0)
    has_speech = speech_ratio > 0.3
    has_music = audio_result.get("has_music", False)
    person_count = yolo_result.get("person_count", 0)

    # Decision matrix
    if is_visual_interview and has_speech and person_count > 0:
        classification = "interview"
        confidence = 0.95
    elif not is_visual_interview and not has_speech:
        classification = "broll"
        confidence = 0.95
    elif not is_visual_interview and has_speech:
        classification = "voiceover_broll"
        confidence = 0.80
    elif is_visual_interview and not has_speech and person_count > 0:
        classification = "cutaway"
        confidence = 0.70
    elif has_music and not has_speech:
        classification = "transition"
        confidence = 0.85
    else:
        classification = "ambiguous"
        confidence = 0.50

    return {
        "final_classification": classification,
        "final_confidence": round(confidence, 2),
        "is_broll": classification in ("broll", "voiceover_broll", "transition"),
        "is_interview": classification == "interview",
        "classification_sources": {
            "visual": shot_type,
            "audio": audio_result.get("audio_type", "unknown"),
            "person_count": person_count,
        }
    }
```

## Производительность

Мгновенно — это просто логика на уже вычисленных данных. ~1ms на сцену.

## Зависимости

Никаких дополнительных. Использует данные из других модулей.

## Приоритет

**Extended** — но крайне рекомендуется. Повышает точность B-roll классификации с ~85% (только CLIP) до ~95% (CLIP + Audio). Минимальные затраты (модуль 09 уже посчитал аудио).
