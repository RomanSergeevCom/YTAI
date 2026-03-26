# 09. Audio Analysis — Анализ аудио

## Что делает

Классифицирует аудио по типу (речь, музыка, тишина, фоновые звуки), определяет громкость (LUFS), находит речевые паузы и музыкальные фрагменты — для точной идентификации B-roll участков (видео без речи) и аудио-сегментации.

## Библиотеки

### Silero VAD (Voice Activity Detection)
- https://github.com/snakers4/silero-vad
- GitHub Stars: ~5,000
- Лицензия: MIT
- Точный детектор речи (state-of-the-art)
- Легковесный: 1.6MB модель, работает на CPU

### pyAudioAnalysis
- https://github.com/tyiannak/pyAudioAnalysis
- GitHub Stars: ~6,000
- Лицензия: Apache-2.0
- Классификация: речь/музыка/тишина/noise
- Извлечение audio features (MFCC, chroma, spectral)

### pyloudnorm (LUFS)
- https://github.com/csteinmetz1/pyloudnorm
- Измерение громкости по стандарту ITU-R BS.1770 (LUFS)
- Необходим для профессионального аудио-анализа

## Как работает

### Silero VAD:
1. Загрузить аудио (WAV/MP4)
2. Разбить на chunks (30ms)
3. Для каждого chunk: speech probability (0.0 — 1.0)
4. Результат: массив speech/non-speech сегментов

### pyAudioAnalysis:
1. Извлечь audio features (MFCC, spectral centroid, etc.)
2. Классифицировать сегменты: speech / music / silence / noise
3. Дополняет Silero: различает "не-речь = музыка" vs "не-речь = тишина"

### LUFS:
1. Интегрированная громкость всего сегмента
2. Помогает найти: тихие моменты, громкие пики, аудио-нормализацию

## Применимость к YTAI

**Хорошо подходит (8/10)** — прямая связь с B-roll detection.

### Ключевой инсайт:
**B-roll = видео без речи.** Если на аудио-дорожке нет речи → это B-roll вставка. Это **самый надёжный** способ определить B-roll, даже надёжнее CLIP.

### Связь с транскриптами:
У нас уже есть транскрипты с word-level timing. Audio analysis дополняет их:
- Транскрипт покрывает **что сказано** → но не покрывает **паузы и музыку**
- Audio analysis покрывает **весь** аудио-контент: речь + музыка + тишина

### Сценарии использования:

| Метрика | Как используется |
|---------|-----------------|
| speech_ratio | % речи в сцене. 0% = чистый B-roll |
| music_detected | Музыкальная подложка (intro/outro/transition) |
| silence_segments | Длинные паузы → потенциальные монтажные точки |
| volume_lufs | Нормализация, поиск тихих/громких мест |

### Пример на YTCR01:
```
scene_000 (00:00-00:12): speech=0%, music=80%, silence=20%
  → B-roll establishing shot с музыкой (intro)

scene_001 (00:12-02:45): speech=85%, music=0%, silence=15%
  → Interview segment

scene_002 (02:45-02:52): speech=0%, music=100%, silence=0%
  → B-roll вставка с музыкой

scene_015 (15:00-15:45): speech=30%, music=0%, silence=70%
  → Длинная пауза в интервью (потенциальный cut point)
```

## Вход / Выход

### Вход
- Аудио файл: `{project}/01_Media/Source/Audio/{scene}/*_TX*.wav` или извлечь из MP4
- Таймкоды сцен (от PySceneDetect)

### Выход
```json
{
  "scene_idx": 2,
  "audio": {
    "speech_ratio": 0.0,
    "music_ratio": 1.0,
    "silence_ratio": 0.0,
    "has_speech": false,
    "has_music": true,
    "volume_lufs": -18.5,
    "audio_type": "music",
    "is_broll_audio": true
  }
}
```

### audio_type categories:
- `speech` — доминирует речь (>60%)
- `music` — доминирует музыка (>60%)
- `silence` — тишина (>80%)
- `ambient` — фоновые звуки без речи и музыки
- `mixed` — смешанный контент

## Пример кода

```python
import torch
import torchaudio
import numpy as np

# Silero VAD
vad_model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad', model='silero_vad',
    trust_repo=True
)
get_speech_timestamps = utils[0]

def analyze_audio_segment(audio_path, start_sec, end_sec):
    """Analyze audio content type within a scene."""
    # Load audio segment
    waveform, sr = torchaudio.load(audio_path)
    if sr != 16000:
        waveform = torchaudio.transforms.Resample(sr, 16000)(waveform)
        sr = 16000

    start_sample = int(start_sec * sr)
    end_sample = int(end_sec * sr)
    segment = waveform[0, start_sample:end_sample]

    if len(segment) == 0:
        return {"audio_type": "unknown", "speech_ratio": 0}

    # VAD: detect speech segments
    speech_timestamps = get_speech_timestamps(
        segment, vad_model, sampling_rate=sr,
        threshold=0.5, min_speech_duration_ms=250
    )

    total_samples = len(segment)
    speech_samples = sum(ts['end'] - ts['start'] for ts in speech_timestamps)
    speech_ratio = speech_samples / total_samples if total_samples > 0 else 0

    # Simple silence detection (RMS < threshold)
    rms = float(torch.sqrt(torch.mean(segment ** 2)))
    is_silent = rms < 0.01

    # Classify
    if speech_ratio > 0.6:
        audio_type = "speech"
    elif is_silent:
        audio_type = "silence"
    elif speech_ratio < 0.1:
        audio_type = "music"  # non-speech, non-silent → likely music
    else:
        audio_type = "mixed"

    return {
        "speech_ratio": round(speech_ratio, 2),
        "has_speech": speech_ratio > 0.1,
        "has_music": audio_type in ("music", "mixed"),
        "audio_type": audio_type,
        "is_broll_audio": speech_ratio < 0.1,
        "rms": round(rms, 4),
    }
```

## Производительность

| Метрика | Значение |
|---------|---------|
| Silero VAD | ~50ms на 10 сек аудио (CPU) |
| Модель | 1.6 MB |
| RAM | ~100 MB |
| 15-мин клип | ~5 сек |
| 40 проектов | ~3 мин |

Очень быстрый модуль. Основное время — загрузка аудио файлов.

## Зависимости

```bash
pip install torch torchaudio  # уже установлены (от CLIP/Whisper)
# Silero VAD скачивается через torch.hub (1.6MB)

# Опционально для LUFS:
pip install pyloudnorm  # ~50KB
```

## Связь с существующими данными

### Транскрипты YTAI уже содержат:
- `segments[].start`, `segments[].end` — таймкоды речи
- `segments[].words[]` — пословная разметка
- **НО**: транскрипт покрывает только речь, не музыку/тишину

### Audio analysis дополняет:
- Нашёл B-roll аудио (нет речи) → совпадает с CLIP B-roll → **уверенность ↑↑**
- Нашёл музыку → intro/outro/transition markers
- Нашёл длинную паузу → потенциальный cut point

## Приоритет

**Extended** — но один из самых полезных Extended-модулей. Аудио-сигнал "нет речи = B-roll" — самый надёжный, даже надёжнее CLIP визуального анализа.
