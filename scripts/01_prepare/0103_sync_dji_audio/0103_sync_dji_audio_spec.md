# 0103_sync_dji_audio — Specification v1.2.0

> **Legacy** — Superseded by 0105_multiwindow_sync_dji (multi-window cross-correlation). This script is kept for reference but 0105 is the production sync.

Синхронизация аудио DJI беспроводных микрофонов с видеоклипами камеры.

**Вход:** `Source/Video/*.mp4` (или `Source/Video/{scene}/*.mp4`) + `99_Pipeline/DJI_Audio/*.wav`
**Выход:** `Source/Audio/{clip}_TX{N}.wav` или `Source/Audio/{scene}/{clip}_TX{N}.wav`

---

## Назначение

DJI беспроводные микрофоны записывают аудио в отдельные WAV файлы (24-bit, 48kHz, mono) с максимальной длительностью 30 минут на файл. Таймстемпы DJI записываются в локальном времени, а камера пишет метаданные в UTC.

Скрипт сопоставляет DJI WAV с видеоклипами по временным меткам, обрезает и конкатенирует DJI аудио под длительность каждого клипа. Часовой пояс определяется автоматически.

## Скрипт

```
scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py
```

## Использование

```bash
# Через pipeline (timezone определяется автоматически)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT"

# Напрямую (auto-detect)
python ~/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py \
    --project "$PROJECT"

# Напрямую (explicit timezone)
python ~/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py \
    --project "$PROJECT" --tz-offset 4

# Dry run
python ~/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py \
    --project "$PROJECT" --dry-run
```

### Параметры CLI

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `--project` | string | (обязательно) | Путь к папке проекта |
| `--tz-offset` | float | auto-detect | Часовой пояс DJI (часы от UTC). Если не указан — определяется автоматически |
| `--overwrite` | flag | — | Перезаписать существующие файлы |
| `--dry-run` | flag | — | Только показать план |
| `--verbose` | flag | — | Показать вывод ffmpeg |

## Авто-определение timezone

Если `--tz-offset` не указан, скрипт автоматически определяет часовой пояс:

### Алгоритм

1. Извлечь `creation_time` (UTC) из видеоклипов через `ffprobe`
2. Извлечь локальные таймстемпы DJI из тегов WAV или имени файла (`get_dji_wav_info_raw`)
3. Для каждого возможного offset от -12 до +14 (шаг 0.5ч, всего 53 кандидата):
   - Конвертировать DJI local → UTC через этот offset
   - Подсчитать количество DJI файлов, перекрывающихся по времени с видеоклипами
4. Выбрать offset с максимальным количеством overlap-ов

### Пример

```
DJI файл:   TX02_MIC037_20260306_102304  → local 10:23:04
Видео клип: RYA-FX3-0100.MP4            → created 06:03:08 UTC

offset = +4 → DJI UTC = 06:23:04 → overlap с видео ✓
offset = +3 → DJI UTC = 07:23:04 → overlap с видео ✓
offset = +5 → DJI UTC = 05:23:04 → overlap зависит от длительности

Максимум overlap при offset = +4 → auto-detected: UTC+4
```

### Функция

```python
def auto_detect_tz_offset(clips, raw_wavs) -> (float | None, int, int):
    """Returns (best_offset, overlap_count, total_wavs)"""
```

### Fallback

Если авто-определение не находит overlap-ов → ошибка с подсказкой `--tz-offset`.

## Зачем --tz-offset (ручной режим)

DJI микрофоны записывают таймстемпы в **локальном** времени, камера Sony — в **UTC**. Обычно offset определяется автоматически, но можно указать вручную:

- `--tz-offset 4` — Dubai (UTC+4)
- `--tz-offset 3` — Moscow (UTC+3)
- `--tz-offset -5` — New York (UTC-5)
- `--tz-offset 5.5` — India (UTC+5:30)

## Алгоритм синхронизации

### Phase 0: Resolve timezone

Авто-определение или использование `--tz-offset`. Метаданные видео и DJI кешируются для Phase 1.

### Phase 1: Collect metadata

**Видеоклипы** (`Source/Video/*.mp4`):
- `creation_time` из ffprobe (UTC)
- Длительность клипа

**DJI файлы** (`99_Pipeline/DJI_Audio/*.wav`):
- Парсинг имени: `TX02_MIC037_20260306_102304_orig.wav`
  - `TX02` — номер передатчика
  - `MIC037` — номер микрофона
  - `20260306_102304` — дата и время (локальное)
- Конвертация в UTC через resolved tz_offset

### Phase 2: Sync and trim

Для каждого видеоклипа и каждого передатчика (TX):
1. Найти DJI файлы, перекрывающиеся по времени
2. Рассчитать точку обрезки (trim) относительно начала DJI файла
3. Если клип охватывает несколько DJI файлов → конкатенация

### FFmpeg

```bash
# Простой случай (1 DJI файл → 1 клип)
ffmpeg -i DJI.wav -ss {offset} -t {duration} -c copy output.wav

# Сложный случай (несколько DJI файлов → 1 клип)
ffmpeg -f concat -safe 0 -i list.txt -ss {offset} -t {duration} -c copy output.wav
```

## Выходная структура

### Flat (без scene-папок)

```
01_Media/Source/Audio/
├── RYA-FX3-0099_TX02.wav      ← DJI аудио, синхронизированное с клипом 0099
├── RYA-FX3-0100_TX02.wav      ← DJI аудио, синхронизированное с клипом 0100
└── ...
```

### Scene-aware (v1.2.0)

Если видео лежат в scene-папках (`Source/Video/01_Interview/`, `02_Car/`, `03_Coffee/`), выход зеркалит структуру:

```
01_Media/Source/Audio/
├── 01_Interview/
│   ├── RYA-ZVE1-1180_TX01.wav
│   └── ...
├── 02_Car/
│   ├── RYA-ZVE1-1149_TX01.wav
│   └── ...
└── 03_Coffee/
    ├── RYA-ZVE1-1167_TX01.wav   ← TX01 (mic 1)
    ├── RYA-ZVE1-1167_TX02.wav   ← TX02 (mic 2)
    └── ...
```

Нейминг: `{clip_stem}_TX{NN}.wav`
Scene-папки определяются regex `^\d{2}_` из `Source/Video/`.

## DJI Raw Audio

Формат сырых файлов DJI:

| Параметр | Значение |
|----------|----------|
| Filename pattern | `TX##_MIC###_YYYYMMDD_HHMMSS_orig.wav` |
| Sample rate | 48000 Hz |
| Channels | 1 (mono) |
| Bit depth | 24-bit |
| Max duration | 30 minutes per file |
| Regex | `^TX\d{2}_MIC\d{3}_\d{8}_\d{6}` |

## Premiere XML (Phase 4)

После синхронизации генерируется FCP 7 XML для проверки в Premiere Pro.

### Flat проект → 1 sequence

```
99_Pipeline/DJI_Audio/{CODE}_dji_sync_check.xml
  └── Sequence "DJI Sync Check": V1 + A1 (camera) + A2 (DJI)
```

### Scene проект → N sequences (v1.2.0)

```
99_Pipeline/DJI_Audio/{CODE}_dji_sync_check.xml
  ├── Sequence "01_Interview": V1 + A1 + A2 (TX01)
  ├── Sequence "02_Car":       V1 + A1 + A2 (TX01)
  └── Sequence "03_Coffee":    V1 + A1 + A2 (TX01) + A3 (TX02)
```

Каждая сцена — отдельный таймлайн. TX-каналы раскладываются по дорожкам: TX01→A2, TX02→A3 и т.д. В Coffee — 2 DJI дорожки друг под другом.

**Workflow:** Open `.prproj` → File > Import `.xml` → sequences appear.

## Проверка завершённости

```python
def check_sync_dji(project: Path) -> bool:
    audio = project / "01_Media" / "Source" / "Audio"
    return audio.is_dir() and any(audio.rglob("*.wav"))
```

## Опциональность

Стадия DJI sync пропускается если нет DJI файлов в `99_Pipeline/DJI_Audio/` → `⏭ no DJI files`.

Если DJI файлы есть — стадия запускается автоматически (timezone auto-detected).

## Логи

```
01_Media/Source/Setup/logs/{project}_sync_dji_audio_{YYYYMMDD_HHMMSS}.log
```

## Edge cases

| Ситуация | Поведение |
|----------|----------|
| Нет DJI файлов | Стадия пропускается |
| Авто-определение timezone не нашло overlap | Ошибка + подсказка `--tz-offset` |
| `--tz-offset` указан явно | Используется напрямую, авто-определение не запускается |
| DJI файл не перекрывается с клипом | WARNING, skip |
| Несколько TX на один клип | Создаёт `{clip}_TX02.wav`, `{clip}_TX03.wav` и т.д. |
| DJI запись прервалась (< 30 мин) | Обрезается по доступной длительности |
| Один DJI файл покрывает несколько клипов | Обрезается отдельно для каждого клипа |
| Timezone с половинным часом (UTC+5:30) | Поддерживается (шаг 0.5ч) |

## Ключевые функции

| Функция | Описание |
|---------|----------|
| `get_dji_wav_info_raw()` | Парсинг DJI метаданных без конвертации TZ (для auto-detect) |
| `get_dji_wav_info()` | Парсинг DJI метаданных с конвертацией TZ → UTC |
| `auto_detect_tz_offset()` | Brute-force overlap matching для определения TZ |
| `get_video_clip_info()` | Извлечение creation_time и duration из видео |
| `find_overlapping_wavs()` | Поиск DJI файлов, перекрывающихся с клипом |
| `build_ffmpeg_cmd()` | Построение ffmpeg команды для trim/concat |

## Зависимости

- **ffmpeg** / **ffprobe** — внешние зависимости
- Python stdlib: `argparse`, `subprocess`, `json`, `re`, `datetime`, `pathlib`

## Связи

```
0101_init_folders
├── Source/Video/*.mp4           ← вход (метаданные creation_time)
├── 99_Pipeline/DJI_Audio/*.wav  ← вход (raw DJI recordings)
│
0103_sync_dji_audio          ────┘
└── Source/Audio/{clip}_TX{N}.wav  ← выход
    │
    ├──→ 02_transcribe  (включает synced audio в ingest.json clips[].dji_audio)
    └──→ 0500_uxp INGEST → ASSEMBLY/REVIEW/SCREENS  (DJI на A2 во всех секвенциях)
```
