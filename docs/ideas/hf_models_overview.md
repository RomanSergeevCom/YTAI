# HuggingFace модели для YTAI Pipeline

Анализ моделей с HuggingFace, которые можно использовать в пайплайне. Все модели запускаются локально на Mac (Apple Silicon M-series).

Дата анализа: 2026-03-26

---

## Карта пайплайна → модели

```
Stage 00: INGEST (discover.py)
  └─ Scene classification         → CLIP, BLIP
  └─ Content sampling             → faster-whisper (уже Whisper, но быстрее)

Stage 01: PREPARE (extract_audio + sync_dji)
  └─ Audio denoising              → DeepFilterNet3
  └─ Voice activity detection     → Silero VAD v5
  └─ Audio quality assessment     → (нет готовой модели)

Stage 02: TRANSCRIBE (transcribe_project.py)
  └─ Speech-to-text               → faster-whisper-large-v3-turbo (ЗАМЕНА)
  └─ Speaker diarization          → pyannote 3.1 (уже используем)
  └─ Post-correction              → Llama-3.2-3B-Instruct

Stage 03: SPEAKER ID
  └─ Speaker name resolution      → Llama-3.2-3B via MLX (замена Ollama)
  └─ Speaker voice embeddings     → pyannote/embedding-3.0 (кластеризация по голосу)

Stage 04: VIDEO ANALYSIS (TODO — не реализован)
  └─ Shot boundary detection      → PySceneDetect + TransNetV2
  └─ B-roll vs. talking head      → CLIP (text-image matching)
  └─ Face detection               → YOLO11 / MediaPipe
  └─ Frame captioning             → BLIP-2

Stage 05: EDITING
  └─ Brief generation             → Llama-3.2-3B / Claude API (уже Claude)
  └─ Keyword extraction           → KeyBERT
  └─ Subtitle translation         → NLLB-200

Stage 06: THUMBNAILS (TODO)
  └─ Image generation             → FLUX.1-schnell via mflux
  └─ Text overlay                 → Pillow (уже есть)

Stage 07: SHORTS (TODO)
  └─ Highlight detection          → CLIP + audio energy
  └─ Auto-captions                → faster-whisper

Stage 08: YOUTUBE (TODO)
  └─ Title/description gen        → Llama-3.2-3B
  └─ Tag extraction               → KeyBERT
  └─ Chapter generation           → Llama-3.2-3B

Stage 09: IDEAS (TODO)
  └─ Competitor analysis          → sentence-transformers (similarity)

Дополнительно:
  └─ Background music             → MusicGen-medium
  └─ Sound effects                → AudioGen-medium
```

---

## Модели по категориям

### 1. Речь и аудио

| Модель | Размер | Задача | Mac M-series | Заметки |
|---|---|---|---|---|
| **faster-whisper-large-v3-turbo** | ~1.5 GB | ASR | Да (CTranslate2) | 3-4x быстрее текущего Whisper |
| **WhisperKit (CoreML)** | варьируется | ASR | Нативный CoreML | Самый быстрый на Mac |
| **pyannote/speaker-diarization-3.1** | ~200 MB | Diarization | Да (MPS) | Уже используем |
| **Silero VAD v5** | ~2 MB | Voice Activity | Да (CoreML) | Детекция речи перед Whisper |
| **DeepFilterNet3** | ~10 MB | Denoising | Да (Rust) | Реальное время, очень быстро |
| **ResembleAI/resemble-enhance** | ~400 MB | Voice enhancement | Да (PyTorch) | Улучшение качества голоса |

### 2. Видео и изображения

| Модель | Размер | Задача | Mac M-series | Заметки |
|---|---|---|---|---|
| **openai/clip-vit-large-patch14** | 890 MB | Image-text matching | Да (MPS) | B-roll поиск по описанию |
| **Salesforce/blip-image-captioning-large** | 1.8 GB | Image captioning | Да (MPS) | Авто-описание кадров |
| **Ultralytics/YOLO11** | 6-50 MB | Object/face detection | Да (CoreML) | Лица, люди, объекты |
| **MediaPipe** | ~5 MB | Face/pose detection | Да (нативный) | Жесты, выражения |
| **PySceneDetect** | библиотека | Scene detection | Да (CPU) | Границы сцен |
| **TransNetV2** | ~15 MB | Shot detection | Да (PyTorch) | Точнее PySceneDetect |

### 3. NLP и текст

| Модель | Размер | Задача | Mac M-series | Заметки |
|---|---|---|---|---|
| **meta-llama/Llama-3.2-3B-Instruct** | 2 GB (Q4) | LLM general | Да (MLX) | Замена Ollama для Speaker ID, chapters |
| **meta-llama/Llama-3.1-8B-Instruct** | 4.5 GB (Q4) | LLM quality | Да (MLX) | Лучше качество, больше RAM |
| **facebook/nllb-200-distilled-600M** | 1.2 GB | Translation | Да (MPS) | 200 языков, включая ru/ar |
| **KeyBERT** | ~100 MB | Keywords | Да (CPU) | Ключевые слова из текста |
| **facebook/bart-large-cnn** | 1.6 GB | Summarization | Да (MPS) | Extractive summary |

### 4. Генерация контента

| Модель | Размер | Задача | Mac M-series | Заметки |
|---|---|---|---|---|
| **FLUX.1-schnell** | ~12 GB | Text-to-image | Да (MLX, ~30s) | Тамбнейлы, B-roll |
| **SDXL 1.0** | ~7 GB | Text-to-image | Да (CoreML) | ControlNet экосистема |
| **MusicGen-medium** | 3.3 GB | Text-to-music | Да (MPS, ~30s/10s) | Фоновая музыка |
| **AudioGen-medium** | 3.3 GB | Text-to-SFX | Да (MPS) | Звуковые эффекты |
| **Stable Audio Open** | ~1.2 GB | Audio generation | Да (MPS) | До 47 сек аудио |
