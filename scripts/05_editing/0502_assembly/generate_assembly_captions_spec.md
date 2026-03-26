# generate_assembly_captions — Specification v1.0.0

Python-скрипт для генерации Assembly captions SRT с таймкодами Assembly-таймлайна.

**Вход:**
- `{CODE}_Claude4_assembly.json` (из 0501_brief, в Setup/)
- `per_clip/{clip_id}/{clip_id}_transcript.json` (из 020101_transcribe, word-level timing)

**Выход:**
- `{CODE}_2_Assembly_v{N}_captions.srt` — word-level субтитры с таймкодами Assembly таймлайна (имя = имя таймлайна)

> **Примечание:** UXP плагин теперь генерирует transcript + captions SRT автоматически при сборке Assembly/Review (Step 6). Python скрипт используется как fallback для более точного word-level timing.

---

## Назначение

Существующий `{project}_1_Ingest_captions.srt` из 020101_transcribe содержит таймкоды относительно исходных clip-файлов. Эти таймкоды **не совпадают** с Assembly-таймлайном, где клипы переставлены по блокам, обрезаны, и идут в другом порядке.

Скрипт ремаппит word-level таймкоды на Assembly-таймлайн, чтобы субтитры точно совпадали с видео.

## Использование

```bash
python generate_assembly_captions.py --brief {CODE}_Claude4_assembly.json
python generate_assembly_captions.py --brief path/to/Claude4_assembly.json --words-per-block 4
python generate_assembly_captions.py --brief path/to/Claude4_assembly.json --output custom_output.srt
```

### Параметры CLI

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `--brief` | string | (обязательно) | Путь к Claude4_assembly.json |
| `--words-per-block` | int | 6 | Слов на SRT-блок (2 строки по N/2 слов) |
| `--output` | string | auto | Выходной путь (default: `{project}_2_Assembly_captions.srt` рядом с brief) |

---

## Алгоритм (зеркалит assemblyBuilder.js)

### 1. Фильтрация и сортировка

```
useSegs = [s for s in segments if s.use == "TRUE" and s.block != 99]
useSegs.sort(key=(block, _brief_idx))  # block ASC, brief order внутри
```

Точно повторяет `assemblyBuilder.js:sortSegments()`.

### 2. Cumulative position

```
cumulative = 0.0
for seg in useSegs:
    timeline_start = cumulative
    duration = max(0, outSec - inSec)
    cumulative = round(cumulative + duration, 1)  # rounding to 1 decimal!
```

Точно повторяет `assemblyBuilder.js` (строки 246-326).

### 3. Word extraction

Для каждого сегмента:
- Загрузить `{clip_id}_transcript.json`
- Собрать все words из всех segments клипа
- Отфильтровать: `word.start >= inSec AND word.start < outSec`

### 4. Timecode remapping

```
assembly_word_start = timeline_start + (word.start - inSec)
assembly_word_end   = timeline_start + (word.end - inSec)
```

### 5. SRT grouping (per-segment)

- Слова группируются **внутри каждого сегмента** (SRT-блоки не пересекают границы сегментов/клипов)
- Каждый SRT-блок: до N слов, разбитых на 2 строки
- Формат: `HH:MM:SS,mmm --> HH:MM:SS,mmm`

---

## Структура функций

```
parse_timecode(tc_str) → float
    Зеркалит briefParser.js parseTimecode()

format_srt_time(seconds) → str
    Seconds → HH:MM:SS,mmm

load_brief(path) → dict
    Загрузка Claude4_assembly.json

sort_segments(segments) → list
    Фильтрация + сортировка (зеркалит assemblyBuilder.js)

find_per_clip_dir(brief_path, transcription_dir, project_name) → Path
    Поиск per_clip/ директории

load_clip_words(per_clip_dir, clip_id) → list
    Загрузка всех слов из clip transcript

extract_words_in_range(all_words, in_sec, out_sec) → list
    Фильтрация слов по диапазону

group_words_to_blocks(words, words_per_block) → list
    Группировка в SRT-блоки

generate_assembly_srt(brief_path, words_per_block) → (str, dict)
    Главная функция

main()
    CLI: argparse → generate → write
```

---

## Обнаружение пути к транскрипциям

Поиск `per_clip/` директории (в порядке приоритета):

1. `{brief_dir}/{transcription_dir}/per_clip/` — рядом с brief
2. `{brief_dir}/../{transcription_dir}/per_clip/` — уровнем выше
3. Вверх по дереву → `scripts/02_transcribe/{project}/{transcription_dir}/per_clip/`
4. Fallback: `{project_name}_transcription` если `_transcription_dir` пустой

---

## Форматы данных

### Per-clip transcript (вход)

```json
{
  "clip_id": "C5403",
  "segments": [{
    "words": [
      {"word": "Long", "start": 0.0, "end": 0.1, "confidence": 0.74},
      {"word": "story", "start": 0.1, "end": 0.28, "confidence": 0.97}
    ]
  }]
}
```

Timing: секунды относительно начала клипа (0.0 = начало clip файла).

### Assembly SRT (выход)

```
1
00:00:00,000 --> 00:00:02,500
Long story short.
Yeah, long story

2
00:00:02,500 --> 00:00:04,740
short. The other
day, I received
```

Timing: секунды относительно начала Assembly секвенции.

---

## Связи с другими компонентами

```
020101_transcribe
├── per_clip/{clip_id}_transcript.json ─┐
│                                       ├──→ generate_assembly_captions.py
0505_claude_kb                        │         │
└── Claude4_assembly.json ──────────────┘         │
                                                  ↓
                                    {project}_2_Assembly_captions.srt
                                                  │
                                                  ↓
                                    050105_assembly_uxp (Step 6: auto-import)
                                         │
                                    01_Transcripts bin → editor drag to Caption track
```

### Именование

| Файл | Источник | Таймкоды |
|------|---------|----------|
| `{project}_1_Ingest_captions.srt` | 020101_transcribe | Относительно raw source clips (для Ingest таймлайна) |
| **`{project}_2_Assembly_captions.srt`** | **generate_assembly_captions.py** | **Относительно Assembly таймлайна** |

Имена зеркалят секвенции: `{project}_1_Ingest` и `{project}_2_Assembly`.

---

## Edge cases

| Ситуация | Поведение |
|----------|----------|
| Клип без transcript JSON | WARNING + skip (пустые субтитры для сегмента) |
| Нет слов в диапазоне tc_in..tc_out | WARNING + skip |
| `_transcription_dir` пустой | Fallback на `{project_name}_transcription` |
| Слово на границе out_sec | Включается если `word.start < outSec` |
| Очень короткий сегмент (3s) | 1-2 SRT-блока, корректные таймкоды |
| Один clip в нескольких сегментах | Кэширование — clip загружается один раз |

---

## Зависимости

Только Python stdlib: `json`, `argparse`, `pathlib`, `sys`, `os`. Нет внешних библиотек.

---

## Тестирование

```bash
# Базовый запуск
python generate_assembly_captions.py --brief 999_testing_project/YTAI_Edit/YTAI_Edit_Claude4_assembly.json

# Ожидаемый результат:
#   Segments processed: 5
#   Clips loaded: 3 (C5402, C5403, C5404)
#   Words mapped: 471
#   SRT blocks: 81
#   Timeline duration: 193.3s
```

### Верификация

1. **Первый субтитр** начинается ~00:00:00,000 (первое слово seg_001)
2. **Переход Block 1→2** — таймкод прыгает на ~00:01:11,600 (71.6s cumulative)
3. **Переход Block 2→3** — таймкод прыгает на ~00:01:47,100 (107.1s cumulative)
4. **SRT-блоки не пересекают границы сегментов** — слова из разных клипов не смешиваются
5. **Premiere Pro** — импорт SRT + drag на Caption track → синхронно с речью
