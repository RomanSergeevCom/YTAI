# transcribe_messenger_voice.py

Транскрибация голосовых сообщений WhatsApp и Telegram с помощью OpenAI Whisper.

## Возможности

- 🎙️ **Telegram** — `.ogg`, `.oga` файлы
- 📱 **WhatsApp** — `.opus` файлы
- 🎵 **Другие форматы** — `.mp3`, `.m4a`, `.wav`, `.flac`, `.aac`
- 🌍 **Авто-определение языка** или указание вручную
- ⚡ **Кэширование модели** — быстрая обработка нескольких файлов
- 📝 **Сохранение в .txt** — рядом с оригиналом или в указанную папку

## Установка

### 1. Зависимости

```bash
# macOS
brew install ffmpeg

# Python пакеты
pip install openai-whisper
```

### 2. Скачать скрипт

Положить `transcribe_messenger_voice.py` в удобное место, например `~/YTAI/scripts/`.

## Использование

### Базовый запуск

```bash
# Один файл (Telegram)
python transcribe_messenger_voice.py message.ogg

# Один файл (WhatsApp)
python transcribe_messenger_voice.py voice.opus
```

### С указанием языка (быстрее)

```bash
python transcribe_messenger_voice.py message.ogg -l ru
python transcribe_messenger_voice.py message.ogg -l en
python transcribe_messenger_voice.py message.ogg -l ar
```

### Выбор модели

| Модель | Размер | Скорость | Качество |
|--------|--------|----------|----------|
| `tiny` | 39 MB | ⚡⚡⚡⚡⚡ | ⭐ |
| `base` | 74 MB | ⚡⚡⚡⚡ | ⭐⭐ |
| `small` | 244 MB | ⚡⚡⚡ | ⭐⭐⭐ |
| `medium` | 769 MB | ⚡⚡ | ⭐⭐⭐⭐ |
| `large-v3` | 2.9 GB | ⚡ | ⭐⭐⭐⭐⭐ |

```bash
# Быстрая модель (для черновиков)
python transcribe_messenger_voice.py message.ogg -m medium

# Максимальное качество (по умолчанию)
python transcribe_messenger_voice.py message.ogg -m large-v3
```

### Пакетная обработка

```bash
# Все OGG файлы в текущей папке
python transcribe_messenger_voice.py *.ogg

# Сохранить в отдельную папку
python transcribe_messenger_voice.py *.ogg -o ./transcripts/
```

### Контекстная подсказка

Помогает Whisper лучше распознавать специфичную лексику:

```bash
python transcribe_messenger_voice.py message.ogg --prompt "Бизнес в ОАЭ, free zone, компания"
```

## Примеры

### Telegram голосовое

```bash
python transcribe_messenger_voice.py ~/Downloads/2026-01-16_19_04_47.ogg -l ru
```

Результат:
- Текст выводится в терминал
- Сохраняется в `2026-01-16_19_04_47.txt`

### WhatsApp голосовое

```bash
python transcribe_messenger_voice.py ~/Downloads/PTT-20260116-WA0001.opus -l en
```

### Все голосовые за день

```bash
python transcribe_messenger_voice.py ~/Downloads/*.ogg ~/Downloads/*.opus -o ~/transcripts/
```

## Вывод

```
╔══════════════════════════════════════════════════════════╗
║              TRANSCRIBE VOICE v1.0.0                     ║
║        WhatsApp / Telegram Voice Messages                ║
╚══════════════════════════════════════════════════════════╝

Files: 1
Model: large-v3
Language: auto-detect
Total duration: 1m 23s

============================================================
File: 2026-01-16_19_04_47.ogg
Duration: 1m 23s
============================================================
  Loading Whisper model (large-v3)...
  Transcribing...
  Language: ru
  Time: 12.3s (6.7x realtime)

------------------------------------------------------------
TRANSCRIPT:
------------------------------------------------------------
Привет, это голосовое сообщение для теста транскрибации...
------------------------------------------------------------

Saved: /Users/roman/Downloads/2026-01-16_19_04_47.txt

============================================================
Done: 1/1 files transcribed
Total time: 15s
============================================================
```

## Советы

1. **Указывайте язык** (`-l ru`) — ускоряет обработку на 20-30%
2. **Используйте `medium`** для черновиков — в 3-4 раза быстрее
3. **Пакетная обработка** — модель загружается один раз
4. **Prompt** — помогает с именами, терминами, аббревиатурами

## Ограничения

- Без диаризации спикеров (для этого используй `whisper_batch.py`)
- Whisper работает лучше с чистым звуком (меньше шума)
- Первый запуск скачивает модель (~2.9 GB для large-v3)

## Требования

- Python 3.8+
- ffmpeg
- ~3 GB RAM для large-v3
- Apple Silicon (MPS) или CUDA для ускорения

## Связанные скрипты

- `whisper_batch.py` — транскрибация с диаризацией спикеров
- `transcribe_project.py` — полный пайплайн YTAI для видео проектов
