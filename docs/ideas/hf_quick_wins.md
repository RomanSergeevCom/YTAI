# Quick Wins: замены и улучшения через HuggingFace

Модели, которые можно интегрировать с минимальными изменениями в текущий пайплайн.

---

## 1. faster-whisper вместо openai-whisper (Stage 02)

**Текущее:** `openai-whisper` large-v3 — медленный, ~3 мин на 30 мин видео.

**Замена:** `faster-whisper-large-v3-turbo` — CTranslate2 backend, 3-4x быстрее при том же качестве.

**Изменения:**
```python
# Было (openai-whisper)
import whisper
model = whisper.load_model("large-v3")
result = model.transcribe(audio_path, word_timestamps=True)

# Стало (faster-whisper)
from faster_whisper import WhisperModel
model = WhisperModel("large-v3-turbo", device="auto", compute_type="int8")
segments, info = model.transcribe(audio_path, word_timestamps=True)
```

**Установка:** `pip install faster-whisper`

**Файлы:** `scripts/02_transcribe/020101_transcribe/transcribe_project.py`

**Выигрыш:** 30-минутное видео: ~3 мин → ~45 сек. RAM: меньше на ~30%.

**Риск:** Низкий. Тот же Whisper, другой runtime. Формат output немного отличается — нужна адаптация парсера.

---

## 2. Silero VAD перед транскрипцией (Stage 02)

**Текущее:** Whisper получает весь аудиофайл, включая тишину и шум.

**Улучшение:** Предварительная детекция речи → Whisper обрабатывает только речевые сегменты.

**Что даёт:**
- Меньше hallucinations Whisper (не "выдумывает" текст в тишине)
- Быстрее (пропускает тишину)
- Точнее timestamps

**Пример:**
```python
import torch
model, utils = torch.hub.load('snakers4/silero-vad', 'silero_vad')
(get_speech_timestamps, _, read_audio, *_) = utils

wav = read_audio(audio_path, sampling_rate=16000)
speech_timestamps = get_speech_timestamps(wav, model, sampling_rate=16000)
# [{start: 0, end: 15000}, {start: 20000, end: 45000}, ...]
```

**Установка:** `pip install silero-vad` (2 MB модель)

**Файлы:** `scripts/02_transcribe/020101_transcribe/transcribe_project.py` — добавить VAD pass перед Whisper

**Выигрыш:** Меньше hallucinations, быстрее на видео с паузами.

---

## 3. DeepFilterNet3 для полевых записей (Stage 01)

**Текущее:** Аудио с DJI Mic 2 используется as-is, с фоновым шумом.

**Улучшение:** Шумоподавление перед транскрипцией.

**Что даёт:**
- Чище аудио → лучше транскрипция
- Удаление ветра, трафика, кондиционера
- Реальное время (~0.5 сек на 1 мин аудио)

**Установка:** `pip install deepfilternet`

**Пример:**
```bash
# CLI
deepFilter input.wav -o output_denoised.wav

# Или Python
from df.enhance import enhance, init_df
model, df_state, _ = init_df()
enhanced = enhance(model, df_state, audio_tensor)
```

**Файлы:** `scripts/01_prepare/0102_extract_audio.py` — добавить optional denoising step

**Нюанс:** Применять выборочно (не все сцены шумные). Добавить флаг `--denoise` в pipeline.

---

## 4. Llama-3.2-3B через MLX вместо Ollama (Stage 03)

**Текущее:** Speaker ID через Ollama (требует отдельный сервер).

**Замена:** `mlx-lm` — нативный Apple Silicon inference, без сервера.

**Что даёт:**
- Нет зависимости от Ollama daemon
- Быстрее на Apple Silicon (MLX оптимизирован для M-series)
- Один pip install, никаких демонов

**Пример:**
```python
from mlx_lm import load, generate

model, tokenizer = load("mlx-community/Llama-3.2-3B-Instruct-4bit")
prompt = "Based on these utterances, who is the speaker?..."
response = generate(model, tokenizer, prompt=prompt, max_tokens=500)
```

**Установка:** `pip install mlx-lm`

**Файлы:** `scripts/03_speaker_id/02_analyze_speakers.py`

**Выигрыш:** Убирает зависимость от Ollama. ~2 GB на диске (Q4 quantization).

---

## 5. KeyBERT для авто-тегов (Stage 08)

**Текущее:** Stage 08 (YouTube metadata) не реализован.

**Новое:** Автоматическая генерация тегов/ключевых слов из транскрипта.

**Пример:**
```python
from keybert import KeyBERT

kw_model = KeyBERT()

transcript = "Today we explore the Al Qudra Lakes in Dubai..."
keywords = kw_model.extract_keywords(
    transcript,
    keyphrase_ngram_range=(1, 3),
    stop_words='english',
    top_n=15
)
# [('Al Qudra Lakes', 0.82), ('Dubai desert', 0.75), ('flamingos', 0.71), ...]
```

**Установка:** `pip install keybert`

**Файлы:** Новый `scripts/08_youtube/03_tags.py`

**Выигрыш:** Авто-теги для YouTube из транскрипта. ~100 MB, работает на CPU за секунды.

---

## 6. NLLB-200 для субтитров (Stage 05/08)

**Текущее:** Субтитры только на языке оригинала.

**Новое:** Локальный перевод субтитров на 200 языков.

**Пример:**
```python
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

model = AutoModelForSeq2SeqLM.from_pretrained("facebook/nllb-200-distilled-600M")
tokenizer = AutoTokenizer.from_pretrained("facebook/nllb-200-distilled-600M")

# English → Russian
tokenizer.src_lang = "eng_Latn"
inputs = tokenizer("Hello everyone, welcome to our channel", return_tensors="pt")
translated = model.generate(**inputs, forced_bos_token_id=tokenizer.convert_tokens_to_ids("rus_Cyrl"))
result = tokenizer.batch_decode(translated, skip_special_tokens=True)
# "Привет всем, добро пожаловать на наш канал"
```

**Установка:** `pip install transformers sentencepiece`

**Файлы:** Новый `scripts/08_youtube/04_translate_srt.py`

**Выигрыш:** Перевод SRT на ru/ar/any за минуты. 1.2 GB модель, CPU достаточно.
