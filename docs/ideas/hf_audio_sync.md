# Улучшение аудио-синхронизации (Stage 01: DJI Sync)

Текущий алгоритм: envelope cross-correlation (8kHz mono, FFT, multi-window scoring).
Проблемы: шум на улице, spanning TX файлов, low SNR indoor.

---

## Текущий алгоритм (для контекста)

```
Camera MP4 → ffmpeg → mono 8kHz → |signal| → envelope (0.1s window) → z-normalize
DJI TX WAV → ffmpeg → mono 8kHz → |signal| → envelope (0.1s window) → z-normalize
                                                    ↓
                          fftconvolve (60s windows, 30s step) → peak offset per window
                                                    ↓
                          consistency voting (±2s tolerance) → score = consistency% × confidence
```

**Параметры:** window=60s, step=30s, tolerance=±2s, short clip threshold=90s

**Слабые места:**
1. Envelope теряет спектральную информацию (только амплитуда)
2. Шум имеет похожую амплитуду → ложные корреляции
3. Нет sub-sample refinement (грубый пик)
4. Spanning определяется эвристикой (файлы подряд по дате)
5. Верификация только первых 60 секунд

---

## Улучшения — Drop-in замены

### 1. GCC-PHAT вместо envelope correlation (САМЫЙ БЫСТРЫЙ WIN)

Generalized Cross-Correlation с Phase Transform — стандарт для time delay estimation в шумных средах.

**Что делает:** Whitening в частотной области → более острый пик корреляции, устойчив к частотно-зависимому шуму (ветер, трафик).

**Заменяет:** Текущий `fftconvolve(envelope_a, envelope_b)`.

```python
import numpy as np

def gcc_phat(sig, refsig, fs=8000, max_tau=None):
    """GCC-PHAT: robust time delay estimation."""
    n = sig.shape[0] + refsig.shape[0]
    SIG = np.fft.rfft(sig, n=n)
    REFSIG = np.fft.rfft(refsig, n=n)
    R = SIG * np.conj(REFSIG)
    cc = np.fft.irfft(R / (np.abs(R) + 1e-10), n=n)

    max_shift = int(fs * max_tau) if max_tau else n // 2
    cc = np.concatenate((cc[-max_shift:], cc[:max_shift + 1]))
    shift = np.argmax(np.abs(cc)) - max_shift
    return shift / fs  # offset in seconds
```

**Размер:** 0 (чистый NumPy, ~20 строк)
**Усилия:** 1-2 часа — заменить вызов fftconvolve
**Файл:** `0105_multiwindow_sync_dji.py`, функция корреляции

---

### 2. Silero VAD перед корреляцией (ВТОРОЙ БЫСТРЫЙ WIN)

**Что делает:** Определяет речевые сегменты → корреляция только по речи (не по шуму/тишине).

**Зачем:** Outdoor recordings: 60% аудио = ветер/трафик. Корреляция шума даёт ложные пики. VAD маскирует шум → чистый сигнал для корреляции.

```python
from silero_vad import load_silero_vad, read_audio, get_speech_timestamps

model = load_silero_vad()

def get_speech_mask(audio_path, sr=8000):
    """Return binary mask: 1=speech, 0=silence/noise."""
    wav = read_audio(audio_path, sampling_rate=sr)
    timestamps = get_speech_timestamps(wav, model, sampling_rate=sr)

    mask = np.zeros(len(wav))
    for ts in timestamps:
        mask[ts['start']:ts['end']] = 1.0
    return mask

# В sync pipeline:
mask_camera = get_speech_mask(camera_audio)
mask_dji = get_speech_mask(dji_audio)

# Применить маску перед корреляцией
camera_masked = camera_envelope * mask_camera
dji_masked = dji_envelope * mask_dji
# → gcc_phat(camera_masked, dji_masked)
```

**Размер:** 2 MB модель
**Скорость:** <1ms на 30ms chunk (реальное время)
**Усилия:** 2-3 часа
**Установка:** `pip install silero-vad`

---

### 3. DeepFilterNet3 — шумоподавление перед корреляцией

**Что делает:** Real-time neural noise reduction. Удаляет ветер, трафик, кондиционер.

**Зачем:** Если камера и DJI записали одну речь, но с разным фоновым шумом → после DeepFilter оба сигнала ближе друг к другу.

```bash
# CLI
deepFilter camera_audio.wav -o camera_clean.wav
deepFilter dji_audio.wav -o dji_clean.wav

# Потом корреляция на clean версиях
```

```python
# Python API
from df.enhance import enhance, init_df

model, df_state, _ = init_df()
enhanced_audio = enhance(model, df_state, audio_tensor)
```

**Размер:** ~10 MB (Rust backend)
**Скорость:** ~0.5 сек на 1 мин аудио
**Установка:** `pip install deepfilternet`
**Усилия:** 3-4 часа (добавить как optional preprocessing step)

---

## Улучшения — Новые подходы

### 4. Audio Fingerprinting (coarse-to-fine matching)

**Проблема:** Текущий алгоритм перебирает все TX-кандидаты → медленно.

**Идея:** Fingerprint → быстро найти правильный TX файл → GCC-PHAT для точного offset.

#### audfprint (Dan Ellis, Columbia)
Landmark-based fingerprinting. Строит базу хэшей из спектральных пиков.

```bash
pip install audfprint

# Шаг 1: Построить базу из всех DJI WAV
audfprint new --dbase dji_index.pklz TX01_MIC026.wav TX01_MIC027.wav TX01_MIC028.wav

# Шаг 2: Найти совпадение для камеры
audfprint match --dbase dji_index.pklz camera_audio.wav
# → "camera_audio.wav: matched TX01_MIC027.wav at offset 142.3s (score: 98)"
```

**Преимущество:** Мгновенное определение КАКОЙ TX файл (вместо перебора всех).
**Точность:** ~0.1s для offset (грубо), потом GCC-PHAT для точности.
**Усилия:** 4-6 часов

#### Chromaprint (AcoustID)
Более компактные fingerprints, 0.124s resolution.

```python
import acoustid
import chromaprint

# Fingerprint обоих файлов
dur1, fp1 = acoustid.fingerprint_file("camera.wav")
dur2, fp2 = acoustid.fingerprint_file("dji_tx01.wav")

# Cross-correlate fingerprint arrays
fp1_array = chromaprint.decode_fingerprint(fp1)[0]
fp2_array = chromaprint.decode_fingerprint(fp2)[0]
# ... numpy cross-correlation на массивах хэшей
```

**Установка:** `pip install pyacoustid` + `fpcalc` binary
**Усилия:** 3-4 часа

---

### 5. WavLM — нейронные audio embeddings (для сложных случаев)

**Что:** Pre-trained model (Microsoft) с injection шума при обучении → embeddings устойчивы к шуму.

**Зачем:** Когда GCC-PHAT не уверен (confidence < 10) → fallback на embedding similarity.

```python
from transformers import WavLMModel, AutoFeatureExtractor
import torch

model = WavLMModel.from_pretrained("microsoft/wavlm-base")
extractor = AutoFeatureExtractor.from_pretrained("microsoft/wavlm-base")

def get_audio_embedding(audio_array, sr=16000):
    """Extract WavLM embedding for audio chunk."""
    inputs = extractor(audio_array, sampling_rate=sr, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    # Mean pooling over time
    return outputs.last_hidden_state.mean(dim=1)  # [1, 768]

# Нарезать оба аудио на 5-сек chunks
camera_chunks = split_audio(camera_audio, chunk_sec=5)
dji_chunks = split_audio(dji_audio, chunk_sec=5)

# Embed все chunks
camera_embs = [get_audio_embedding(c) for c in camera_chunks]
dji_embs = [get_audio_embedding(c) for c in dji_chunks]

# Cosine similarity matrix → найти лучший offset
similarity = cosine_similarity_matrix(camera_embs, dji_embs)
best_offset = find_diagonal_with_max_sum(similarity) * 5.0  # seconds
```

**Размер:** Base=360 MB, Large=1.2 GB
**Скорость:** ~50 chunks/sec на MPS
**Усилия:** 1-2 дня (новый модуль + интеграция)

---

### 6. synctoolbox — DTW для clock drift

**Проблема:** За 30+ минут записи, часы камеры и DJI расходятся. Текущий алгоритм ищет ОДИН offset, но реальный offset может меняться.

**Решение:** Dynamic Time Warping — находит нелинейное соответствие.

```python
from synctoolbox.dtw.mrmsdtw import sync_via_mrmsdtw
import librosa

# Chroma features (или MFCC)
camera_chroma = librosa.feature.chroma_cqt(y=camera_audio, sr=8000)
dji_chroma = librosa.feature.chroma_cqt(y=dji_audio, sr=8000)

# Multi-resolution DTW
wp = sync_via_mrmsdtw(camera_chroma, dji_chroma)
# wp = warping path: array of (camera_frame, dji_frame) pairs
# Показывает как offset меняется со временем
```

**Установка:** `pip install synctoolbox`
**Размер:** Библиотека (~5 MB)
**Усилия:** 1-2 дня
**Когда нужно:** Клипы > 30 мин, высокие требования к точности

---

## Рекомендуемый порядок

### Phase 1 — Drop-in (1-2 дня, фиксит 80% проблем)
1. **Silero VAD** — маска речи перед корреляцией
2. **GCC-PHAT** — замена envelope correlation

### Phase 2 — Coarse-to-fine (3-5 дней)
3. **audfprint / Chromaprint** — быстрый поиск правильного TX файла
4. **DeepFilterNet3** — optional denoising (флаг `--denoise`)

### Phase 3 — Neural fallback (1 неделя)
5. **WavLM embeddings** — fallback при низком confidence
6. **synctoolbox DTW** — для длинных клипов с clock drift

### Ожидаемый результат
| Метрика | Сейчас | После Phase 1 | После Phase 2 |
|---|---|---|---|
| Outdoor success rate | ~70% | ~90% | ~95% |
| Spanning detection | Manual | Manual | Auto (fingerprint) |
| Processing speed | 1x | 1.2x (VAD skips silence) | 2x (fingerprint pre-filter) |
| Sub-frame accuracy | ±1 frame | ±0.5 frame (GCC-PHAT) | ±0.5 frame |
