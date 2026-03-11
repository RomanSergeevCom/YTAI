# YTAI Quick Start

## Проект: YTCG37_Hadi_Dawani

---

## Подготовка

### 1. Запустить Ollama
```bash
# Терминал 1
OLLAMA_MAX_VRAM=20g ollama serve
```

### 2. Активировать окружение
```bash
# Терминал 2
source /Users/romansergeev/YTAI/environment/.venv_transcribe/bin/activate
```

### 3. Установить переменную проекта
```bash
export PROJECT="/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
```

---

## Этап 1: Склейка клипов

### Команда:
```bash
python ~/YTAI/scripts/01_prepare/01_concat_clips.py --project "$PROJECT"
```

### Что делает:
- Берёт все клипы из `01_Raw/01_01_Video/`
- Склеивает в один master файл без перекодирования

### Результат:
```
01_Raw/
├── 01_01_Video/
│   ├── RYA-ZVE1-1146.MP4      (исходные клипы)
│   ├── RYA-ZVE1-1147.MP4
│   └── ...
└── YTCG37_Hadi_Dawani.mkv     ← НОВЫЙ ФАЙЛ (склеенный master)

08_Logs/
└── concat_master_20260113_120000.log
```

### Проверка:
```bash
ls -la "$PROJECT/01_Raw/"*.mkv
# Должен быть: YTCG37_Hadi_Dawani.mkv (~10-50 GB)
```

---

## Этап 2: Извлечение аудио

### Команда:
```bash
python ~/YTAI/scripts/01_prepare/02_extract_audio.py --project "$PROJECT"
```

### Что делает:
- Извлекает аудио из каждого клипа
- Склеивает в один FULL_AUDIO.wav для транскрипции

### Результат:
```
01_Raw/01_02_Audio/
├── RYA-ZVE1-1146_AUDIO.wav    (аудио каждого клипа)
├── RYA-ZVE1-1147_AUDIO.wav
├── ...
└── YTCG37_Hadi_Dawani_FULL_AUDIO.wav  ← ГЛАВНЫЙ ФАЙЛ

08_Logs/
└── extract_audio_20260113_121000.log
```

### Проверка:
```bash
ls -la "$PROJECT/01_Raw/01_02_Audio/"*FULL_AUDIO.wav
# Должен быть: YTCG37_Hadi_Dawani_FULL_AUDIO.wav (~1-3 GB)
```

---

## Этап 3: Транскрипция

### Команда:
```bash
python ~/YTAI/scripts/02_transcribe/01_transcribe_project.py --project "$PROJECT" -n 2
```

### Параметры:
- `-n 2` — количество спикеров (2 для интервью)
- `-m large-v3` — модель Whisper (по умолчанию)

### Что делает:
- Whisper транскрибирует аудио в текст
- Pyannote определяет кто говорит (SPEAKER_00, SPEAKER_01)
- Объединяет в единый транскрипт

### Время: ~15-25 минут для 1 часа видео

### Результат:
```
02_Transcripts/02_01_Runs/
├── YTCG37_Hadi_Dawani_transcript_20260113_122000.json  ← для скриптов
├── YTCG37_Hadi_Dawani_transcript_20260113_122000.txt   ← читаемый текст
└── YTCG37_Hadi_Dawani_transcript_20260113_122000.srt   ← субтитры

08_Logs/
└── YTCG37_Hadi_Dawani_transcribe_20260113_122000.log
```

### Проверка:
```bash
# Файлы созданы?
ls "$PROJECT/02_Transcripts/02_01_Runs/"

# Сколько спикеров найдено?
grep -o '"SPEAKER_[0-9]*"' "$PROJECT/02_Transcripts/02_01_Runs/"*.json | sort -u
# Ожидается: "SPEAKER_00" и "SPEAKER_01"

# Посмотреть начало транскрипта
head -50 "$PROJECT/02_Transcripts/02_01_Runs/"*.txt
```

### Пример содержимого .txt:
```
[00:00:05] SPEAKER_00:
  Hello and welcome to Connect Group channel...

[00:00:12] SPEAKER_01:
  Thank you for having me, Roman...
```

---

## Этап 4: Идентификация спикеров

### Команда:
```bash
python ~/YTAI/scripts/03_speaker_id/00_process_all.py --project "$PROJECT" --no-pause
```

### Что делает (4 подэтапа):

#### 4.1 Extract Speakers
- Извлекает все реплики каждого спикера в отдельные файлы

#### 4.2 Analyze Speakers (LLM)
- qwen2.5:32b анализирует реплики
- Определяет кто Host (Roman), кто Guest (Hadi Dawani)

#### 4.3 Apply Names
- Заменяет SPEAKER_00 → "Roman", SPEAKER_01 → "Hadi Dawani"

#### 4.4 Split Clips
- Разбивает транскрипт по исходным клипам
- Создаёт SRT для каждого клипа с локальными таймкодами

### Время: ~5-10 минут

### Результат:
```
02_Transcripts/02_02_Clean/
├── YTCG37_Hadi_Dawani_extract_speakers_20260113_123000/
│   ├── SPEAKER_00.txt         (все реплики спикера 0)
│   ├── SPEAKER_01.txt         (все реплики спикера 1)
│   └── _SUMMARY.txt           (статистика)
│
├── YTCG37_Hadi_Dawani_extract_speakers_20260113_123000_srt/
│   ├── SPEAKER_00.srt
│   └── SPEAKER_01.srt
│
├── YTCG37_Hadi_Dawani_analyze_speakers_20260113_123500.json      ← результат LLM
├── YTCG37_Hadi_Dawani_analyze_speakers_20260113_123500_report.txt
│
├── YTCG37_Hadi_Dawani_apply_names_20260113_124000.json           ← с именами
├── YTCG37_Hadi_Dawani_apply_names_20260113_124000.txt
├── YTCG37_Hadi_Dawani_apply_names_20260113_124000.srt
│
├── YTCG37_Hadi_Dawani_split_clips_20260113_124500.xlsx           ← таблица
├── RYA-ZVE1-1146.srt          ← SRT для клипа 1
├── RYA-ZVE1-1147.srt          ← SRT для клипа 2
├── RYA-ZVE1-1148.srt          ← SRT для клипа 3
└── ...

08_Logs/
├── YTCG37_Hadi_Dawani_extract_speakers_20260113_123000.log
├── YTCG37_Hadi_Dawani_analyze_speakers_20260113_123500.log
├── YTCG37_Hadi_Dawani_apply_names_20260113_124000.log
└── YTCG37_Hadi_Dawani_split_clips_20260113_124500.log
```

### Проверка:
```bash
# Какие имена определил LLM?
cat "$PROJECT/02_Transcripts/02_02_Clean/"*_analyze_speakers_*.json

# Сколько SRT файлов создано?
ls "$PROJECT/02_Transcripts/02_02_Clean/"*.srt | wc -l

# Посмотреть таблицу
open "$PROJECT/02_Transcripts/02_02_Clean/"*_split_clips_*.xlsx

# Посмотреть транскрипт с именами
head -50 "$PROJECT/02_Transcripts/02_02_Clean/"*_apply_names_*.txt
```

### Пример содержимого *_apply_names_*.txt:
```
[00:00:05] Roman:
  Hello and welcome to Connect Group channel...

[00:00:12] Hadi Dawani:
  Thank you for having me, Roman...
```

### Пример SRT для клипа (RYA-ZVE1-1146.srt):
```
1
00:00:05,000 --> 00:00:11,500
[Roman] Hello and welcome to Connect Group channel...

2
00:00:12,000 --> 00:00:18,300
[Hadi Dawani] Thank you for having me, Roman...
```

---

## Итоговая структура проекта

```
YTCG37_Hadi_Dawani/
│
├── 01_Raw/
│   ├── 01_01_Video/
│   │   ├── RYA-ZVE1-1146.MP4
│   │   ├── RYA-ZVE1-1147.MP4
│   │   └── ...
│   ├── 01_02_Audio/
│   │   ├── RYA-ZVE1-1146_AUDIO.wav
│   │   ├── ...
│   │   └── YTCG37_Hadi_Dawani_FULL_AUDIO.wav
│   └── YTCG37_Hadi_Dawani.mkv
│
├── 02_Transcripts/
│   ├── 02_01_Runs/                              ← сырой транскрипт
│   │   ├── YTCG37_Hadi_Dawani_transcript_*.json
│   │   ├── YTCG37_Hadi_Dawani_transcript_*.txt
│   │   └── YTCG37_Hadi_Dawani_transcript_*.srt
│   │
│   └── 02_02_Clean/                             ← обработанный
│       ├── YTCG37_Hadi_Dawani_extract_speakers_*/
│       ├── YTCG37_Hadi_Dawani_analyze_speakers_*.json
│       ├── YTCG37_Hadi_Dawani_apply_names_*.json
│       ├── YTCG37_Hadi_Dawani_apply_names_*.txt
│       ├── YTCG37_Hadi_Dawani_split_clips_*.xlsx
│       ├── RYA-ZVE1-1146.srt
│       ├── RYA-ZVE1-1147.srt
│       └── ...
│
└── 08_Logs/
    ├── concat_master_*.log
    ├── extract_audio_*.log
    ├── YTCG37_Hadi_Dawani_transcribe_*.log
    ├── YTCG37_Hadi_Dawani_extract_speakers_*.log
    ├── YTCG37_Hadi_Dawani_analyze_speakers_*.log
    ├── YTCG37_Hadi_Dawani_apply_names_*.log
    └── YTCG37_Hadi_Dawani_split_clips_*.log
```

---

## Файлы для Premiere Pro

| Файл | Назначение |
|------|------------|
| `*_split_clips_*.xlsx` | Таблица: клип → таймкод → спикер → текст |
| `RYA-ZVE1-1146.srt` | Субтитры для клипа 1 (локальные таймкоды) |
| `RYA-ZVE1-1147.srt` | Субтитры для клипа 2 |
| `...` | ... |

### Как использовать:
1. Импортировать клипы из `01_Raw/01_01_Video/`
2. Для каждого клипа импортировать соответствующий SRT из `02_02_Clean/`
3. XLSX использовать как референс для навигации

---

## Troubleshooting

### Ошибка: "FULL_AUDIO.wav not found"
```bash
python ~/YTAI/scripts/01_prepare/02_extract_audio.py --project "$PROJECT"
```

### Ошибка: "Ollama connection refused"
```bash
# Проверить что Ollama запущен
curl http://localhost:11434/api/tags

# Если нет — запустить
OLLAMA_MAX_VRAM=20g ollama serve
```

### Неправильные имена спикеров
```bash
# Отредактировать JSON
nano "$PROJECT/02_Transcripts/02_02_Clean/"*_analyze_speakers_*.json

# Перезапустить с этапа 3
python ~/YTAI/scripts/03_speaker_id/00_process_all.py --project "$PROJECT" --start-from 3
```

### Посмотреть логи
```bash
# Последние 50 строк лога транскрипции
tail -50 "$PROJECT/08_Logs/"*_transcribe_*.log

# Лог анализа спикеров
cat "$PROJECT/08_Logs/"*_analyze_speakers_*.log
```

---

## Quick Commands

```bash
# Полный цикл (после подготовки)
source /Users/romansergeev/YTAI/environment/.venv_transcribe/bin/activate
export PROJECT="/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

python ~/YTAI/scripts/02_transcribe/01_transcribe_project.py --project "$PROJECT" -n 2
python ~/YTAI/scripts/03_speaker_id/00_process_all.py --project "$PROJECT" --no-pause

# Проверить результат
ls "$PROJECT/02_Transcripts/02_02_Clean/"*.srt | wc -l
```

---

## Конфигурация

| Параметр | Значение |
|----------|----------|
| Python venv | `/Users/romansergeev/YTAI/environment/.venv_transcribe` |
| LLM модель | `qwen2.5:32b` |
| Whisper модель | `large-v3` |
| Спикеров | 2 (интервью) |
