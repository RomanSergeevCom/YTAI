# 0102_extract_audio — Specification v1.0.0

Извлечение аудио из видеоклипов в WAV формат.

**Вход:** `01_Media/Source/Video/*.mp4` (видеоклипы)
**Выход:** `Transcription/per_clip/{clip}/{clip}_AUDIO.wav` + `{project}_FULL_AUDIO.wav`

---

## Назначение

Извлекает аудиодорожку из каждого видеоклипа в формате WAV (48kHz, stereo, 16-bit PCM) и создаёт конкатенированный файл для последующей транскрипции.

## Скрипт

```
scripts/01_prepare/0102_extract_audio/0102_extract_audio.py
```

## Использование

```bash
# Через pipeline
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only extract_audio

# Напрямую
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT"
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT" --dry-run
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT" --overwrite
python ~/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py --project "$PROJECT" --skip-concat
```

### Параметры CLI

| Параметр | Тип | Default | Описание |
|----------|-----|---------|----------|
| `--project` | string | (обязательно) | Путь к папке проекта |
| `--clips-dir` | string | `01_Media/Source/Video` | Папка с видеоклипами |
| `--out-dir` | string | `01_Media/Source/Transcription` | Папка для аудио |
| `--skip-concat` | flag | — | Не создавать FULL_AUDIO.wav |
| `--overwrite` | flag | — | Перезаписать существующие WAV |
| `--dry-run` | flag | — | Только показать план |
| `--verbose` | flag | — | Показать вывод ffmpeg |

## Алгоритм

### Phase 1: Extract per-clip audio

Для каждого видеоклипа:

```bash
ffmpeg -hide_banner -loglevel warning -y \
    -i {clip.mp4} \
    -map 0:a:0 \           # первый аудиопоток
    -vn -sn -dn \          # без видео, субтитров, данных
    -ar 48000 \            # sample rate
    -ac 2 \                # stereo
    -c:a pcm_s16le \       # 16-bit PCM
    per_clip/{clip}/{clip}_AUDIO.wav
```

Проверка: файл ≥ 100KB (`MIN_OK_BYTES`). Если меньше — ошибка, файл удаляется.

### Phase 2: Concatenate

Конкатенация всех per-clip WAV в один `{project}_FULL_AUDIO.wav`:

1. Создание временного файла (Python `tempfile`) со списком WAV
2. FFmpeg concat demuxer:
   ```bash
   ffmpeg -hide_banner -loglevel warning -y \
       -f concat -safe 0 \
       -i {temp_list.txt} \
       -c copy \
       {project}_FULL_AUDIO.wav
   ```
3. Удаление временного файла

Примечание: временный файл создаётся через `tempfile.NamedTemporaryFile`, а не в проекте. Папка `09_Tmp/` не создаётся.

## Выходная структура

```
01_Media/Source/Transcription/
├── {project}_FULL_AUDIO.wav                   ← конкатенация для транскрипции
├── per_clip/
│   ├── {clip1}/
│   │   └── {clip1}_AUDIO.wav                  ← 48kHz stereo 16-bit PCM
│   └── {clip2}/
│       └── {clip2}_AUDIO.wav
```

## Формат WAV

| Параметр | Значение |
|----------|----------|
| Sample rate | 48000 Hz |
| Channels | 2 (stereo) |
| Bit depth | 16-bit |
| Codec | PCM signed 16-bit little-endian |
| Расчёт длительности | `(file_size - 44) / 192000` секунд |

192000 = 48000 Hz × 2 channels × 2 bytes/sample.

## Проверка завершённости

```python
def check_extract_audio(project: Path) -> bool:
    tr = project / "01_Media" / "Source" / "Transcription"
    return tr.is_dir() and any(tr.glob("*_FULL_AUDIO.wav"))
```

## Логи

```
01_Media/Source/Setup/logs/{project}_extract_audio_{YYYYMMDD_HHMMSS}.log
```

Содержит: время, проект, количество клипов, формат, результат каждого клипа (OK/ERROR + размер), итоговую статистику, команду ffmpeg concat.

## Edge cases

| Ситуация | Поведение |
|----------|----------|
| WAV уже существует | SKIP (если ≥ 100KB и без `--overwrite`) |
| Клип без аудио | FFmpeg error, файл удаляется, fail_count++ |
| Пустой WAV (< 100KB) | ERROR, файл удаляется |
| `--skip-concat` | Phase 2 пропускается |
| 1 клип | Phase 2 всё равно создаёт FULL_AUDIO.wav (copy) |
| FULL_AUDIO уже есть | SKIP (без `--overwrite`) |

## Зависимости

- **ffmpeg** — внешняя зависимость, должен быть в PATH
- Python stdlib только: `argparse`, `subprocess`, `pathlib`, `tempfile`, `re`, `datetime`

## Связи

```
0101_init_folders
└── Source/Video/*.mp4          ← вход
                                    │
0102_extract_audio              ────┘
├── per_clip/{clip}/{clip}_AUDIO.wav  ← 48kHz stereo (для DJI sync, Premiere)
├── {project}_FULL_AUDIO.wav          ← для 02_transcribe
│
├──→ 0103_sync_dji_audio       (использует Video/ для timestamp matching)
└──→ 02_transcribe             (использует FULL_AUDIO или per_clip audio)
```
