# transcribe_project v2.14 — Спецификация

## Обзор

Полная транскрипция: word-level timestamps, Premiere Transcript JSON, глобальная диаризация.
Multi-camera проекты (подпапки камер) с per-camera и combined выходными файлами.
**v2.14:** переименование `_project.json` → `_transcript.json`, расширение `structure` полными путями.

**Скрипт:** ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py
**Версия:** 2.14
**Зависимости:** whisper, pyannote.audio, torch, ffmpeg, openpyxl, soundfile, numpy

---

## Окружение

    # Активировать venv
    source ~/YTAI/environment/.venv_transcribe/bin/activate

    # Flat проект (авто-определение спикеров)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project ~/Desktop/YTAI_Edit \
      --language en \
      -y

    # Multi-camera проект (подпапки камер)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project '/Volumes/RYA T7 Black/YTCG Gambling Ru' \
      -y

    # С указанием количества спикеров
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" \
      -n 2 \
      -y

    # Dry-run (быстрый просмотр плана без загрузки моделей)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project '/Volumes/RYA T7 Black/YTCG Gambling Ru' \
      --dry-run

**Python venv:** `/Users/romansergeev/YTAI/environment/.venv_transcribe`
**HuggingFace token:** автоматически из `~/.huggingface/token` или `~/.cache/huggingface/token`
**Whisper модель:** large-v3 (по умолчанию)
**Устройство:** Apple Silicon MPS (авто-определение)

---

## Входные данные

Скрипт принимает **папку с видео**, **один видеофайл**, или **папку с подпапками камер** — определяет автоматически.

### Вариант A: Папка с видео (flat)

    python transcribe_project_v2.14.py --project "/path/to/Interview" -y

    Interview/
    +-- C5090.MP4
    +-- C5091.MP4
    +-- C5092.MP4

Результат:

    Interview/
    +-- C5090.MP4, C5091.MP4, C5092.MP4
    +-- Interview_transcript.xlsx
    +-- Interview_transcript.json
    +-- Interview.prproj
    +-- Interview_transcription/
        +-- ...

project_name = имя папки ("Interview")

### Вариант B: Один видеофайл

    python transcribe_project_v2.14.py --project "/path/to/C5090.MP4" -y

Результат:

    SomeFolder/
    +-- C5090.MP4
    +-- C5090_transcript.xlsx
    +-- C5090_transcript.json
    +-- C5090.prproj
    +-- C5090_transcription/
        +-- ...

project_name = имя файла без расширения ("C5090")

### Вариант C: Папка с подпапками камер (multi-camera)
    python transcribe_project_v2.14.py --project '/Volumes/RYA T7 Black/YTCG Gambling Ru' -y

    YTCG Gambling Ru/
    +-- FX3/          (8 MP4 от Sony FX3)
    +-- ZVE1/         (8 MP4 от Sony ZV-E1)
    +-- Audio/        (WAV — игнорируется, не VIDEO_EXTENSIONS)

**Автодетект:** скрипт проверяет подпапки корневой директории. Если хотя бы одна подпапка содержит видео — включается multi-camera mode.

Результат:

    YTCG Gambling Ru/
    +-- FX3/
    |   +-- RYA-FX3-0090.MP4 ... (исходники)
    |   +-- FX3_transcript.xlsx          (per-camera XLSX)
    |   +-- FX3_transcript.json             (per-camera project)
    |   +-- FX3_transcription/
    |       +-- per_clip/
    |           +-- RYA-FX3-0090/
    |           |   +-- RYA-FX3-0090_audio.wav
    |           |   +-- RYA-FX3-0090_whisper_raw.json
    |           |   +-- RYA-FX3-0090_transcript.json
    |           |   +-- RYA-FX3-0090_transcript.srt
    |           |   +-- RYA-FX3-0090_transcript.txt
    |           |   +-- RYA-FX3-0090_premiere_transcript.json
    |           +-- RYA-FX3-0091/ ...
    +-- ZVE1/
    |   +-- RYA-ZVE1-1674.MP4 ... (исходники)
    |   +-- ZVE1_transcript.xlsx         (per-camera XLSX)
    |   +-- ZVE1_transcript.json            (per-camera project)
    |   +-- ZVE1_transcription/
    |       +-- per_clip/
    |           +-- RYA-ZVE1-1674/ ...
    +-- YTCG Gambling Ru_transcript.xlsx    (combined — все 16 клипов)
    +-- YTCG Gambling Ru_transcript.json       (combined)
    +-- YTCG Gambling Ru.prproj             (combined Premiere)
    +-- YTCG Gambling Ru_transcription/     (global pipeline internals)
        +-- full_audio.wav                    (все 16 клипов склеены)
        +-- meta.json
        +-- diarization.json                  (глобальная диаризация)
        +-- speakers.json
        +-- clip_offsets.json
        +-- combined_transcript.json
        +-- *.log

project_name = имя корневой папки ("YTCG Gambling Ru")

### Определение типа входных данных

    input_path = Path(args.project)

    if input_path.is_file():
        video_files = [input_path]
        project_name = input_path.stem
        work_dir = input_path.parent
        subfolder_groups = None

    elif input_path.is_dir():
        # Check for subfolders with videos (multi-camera)
        subfolder_groups = {}
        for item in sorted(input_path.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                sub_vids = sorted([
                    f for f in item.iterdir()
                    if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
                    and not f.name.startswith('.')
                ])
                if sub_vids:
                    subfolder_groups[item.name] = {
                        "source_dir": item,
                        "clips": sub_vids,
                        "clip_ids": [f.stem for f in sub_vids],
                    }

        if subfolder_groups:
            # Multi-camera mode
            video_files = []
            for grp in subfolder_groups.values():
                video_files.extend(grp["clips"])
            video_files.sort()
        else:
            # Flat mode (backward compat)
            video_files = find_videos(input_path)
            subfolder_groups = None

        project_name = input_path.name
        work_dir = input_path
        transcription_dir = work_dir / f"{project_name}_transcription"

### Поддерживаемые форматы видео

    VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.avi', '.mts', '.m4v'}

    def find_videos(folder):
        """Find video files recursively, skip hidden dirs/files."""
        return sorted([
            f for f in folder.rglob('*')
            if f.is_file()
            and f.suffix.lower() in VIDEO_EXTENSIONS
            and not f.name.startswith('.')
            and not any(p.startswith('.') for p in f.relative_to(folder).parts[:-1])
        ])

### Multi-camera маршрутизация (get_clip_dir)

Центральная функция, определяющая куда писать per_clip файлы:

    def get_clip_dir(ctx, clip_id):
        """Get per_clip directory for a clip. Subfolder-aware for multi-camera."""
        groups = ctx.get("subfolder_groups")
        if groups:
            for grp_name, grp in groups.items():
                if clip_id in grp["clip_ids"]:
                    td = grp["source_dir"] / f"{grp_name}_transcription"
                    return td / "per_clip" / clip_id
        return ctx["transcription_dir"] / "per_clip" / clip_id

**Flat mode:** per_clip файлы → `{project}_transcription/per_clip/{clip_id}/`
**Multi-camera:** per_clip файлы → `{camera}/{camera}_transcription/per_clip/{clip_id}/`

### Backward Compatibility

| Сценарий | subfolder_groups | Поведение |
|----------|-----------------|-----------|
| Плоская папка (YTAI_Edit/) | `None` | Как v2.12 |
| Подпапки (FX3/, ZVE1/) | `{...}` | Multi-camera mode |
| Один файл (video.MP4) | `None` | Как v2.12 |

`get_clip_dir()` автоматически выбирает правильный путь.

### Определение clip_id

    clip_id = Path(filename).stem
    # "C5090.MP4"         -> "C5090"
    # "RYA-ZVE1-1146.MP4" -> "RYA-ZVE1-1146"

### Параметры запуска

    --project PATH      папка или файл (обязательный)
    -n NUM              количество спикеров (опциональный, auto-detect если не указан)
    -m MODEL            модель Whisper (default: large-v3)
    -y                  пропустить подтверждения
    --language LANG     язык (default: auto-detect)
    --resume            продолжить с последнего этапа
    --stages 3,4,5      только указанные этапы
    --no-prproj         не генерировать .prproj
    --dry-run           показать план без запуска (клипы, длительность, оценка) — см. ниже

### --dry-run

**v2.13:** Dry-run НЕ загружает ML модели (torch, whisper, pyannote). Только ffmpeg/ffprobe для сканирования видео. Работает быстро (~2с).

После preflight checks скрипт выводит список клипов с информацией и завершается:

**Flat mode:**

    Dry run — plan for 3 clips (18:44 total):

      #  Clip    Duration  Resolution  FPS  Codec  Stages       Est. time
      1  C5090   5:24      3840×2160   25   H264   1,2,3,4,5    ~6m 20s
      2  C5091   6:28      3840×2160   25   H264   1,2,3,4,5    ~7m 35s
      3  C5092   6:52      3840×2160   25   H264   1,2,3,4,5    ~8m 02s

**Multi-camera mode:**

    Dry run — would process:

      [FX3]  (8 clips)
        RYA-FX3-0090.MP4       1:04  3840×2160 25fps H264
        RYA-FX3-0091.MP4       0:38  3840×2160 25fps H264
        ...

      [ZVE1]  (8 clips)
        RYA-ZVE1-1674.MP4      1:06  3840×2160 25fps H264
        ...

      Total: 16 clips  225:21  Stages: 1,2,3,4,5,5b
      Estimated: ~169-203 min

### Валидация параметров

Перед запуском (в preflight) скрипт валидирует входные параметры:

- **`-n`** — должен быть положительным целым числом (`> 0`). При невалидном значении: `ERROR: -n must be a positive integer, got: {value}`
- **`--stages`** — должен быть подмножеством `{1, 2, 3, 4, 5, 5b}`. При невалидном значении: `ERROR: invalid stage(s): {invalid}. Valid stages: 1, 2, 3, 4, 5, 5b`
- **`--language`** — валидируется против списка поддерживаемых языков Whisper (`whisper.tokenizer.LANGUAGES`). При невалидном значении: `ERROR: unsupported language: {lang}. Supported: en, ru, ...`
- **Дубликаты clip stems** — если в папке есть файлы с одинаковым stem но разным расширением (например `C5090.MP4` и `C5090.MOV`), скрипт завершается с ошибкой: `ERROR: duplicate clip stems found: C5090 (C5090.MP4, C5090.MOV). Remove duplicates before processing.`

---

## Preflight Checks

Перед запуском скрипт проверяет все зависимости. Если ошибка — НЕ начинает обработку.

### Проверки

    1. ffmpeg              which ffmpeg + ffmpeg -version
    2. Python packages     import whisper, pyannote.audio, torch, soundfile, openpyxl
    3. Whisper model       whisper.load_model("large-v3") — загрузка в память
    4. HuggingFace token   проверка ~/.huggingface/token или config
    5. torch device        MPS / CUDA / CPU — показать что используется
    6. Input path          существует, содержит видео (папка) / видеофайл (файл)
    7. Video files         количество, суммарная длительность + полные метаданные через get_media_info() (ffprobe JSON)
                           resolution, FPS, codec, bitrate, pixel format, audio info, creation date, timecode
                           Вывод: "Media: 3840×2160 25fps H264" в preflight output
    8. Disk space          os.statvfs — нужно ~2x от размера аудио
    9. Previous run        если _transcription/ уже существует — предупредить
    10. Premiere template   ~/YTAI/templates/premiere_template.prproj (WARN if missing)

**v2.13 dry-run fast path:** При `--dry-run` проверяются только ffmpeg + input files. ML модели (whisper, pyannote, torch) НЕ загружаются. Используется `get_media_info()` (ffprobe) для сканирования всех клипов.

**Multi-camera preflight:**

    ✓ Input: folder — 16 files
    Cameras:    FX3 (8) + ZVE1 (8) = 16 clips

### Оценка времени

    # Калиброванные коэффициенты (M3 Pro 36GB, large-v3)
    SPEED_COEFFICIENTS = {
        "extract_audio": 0.03,
        "diarization":   0.15,
        "whisper":       0.70,
        "speaker_map":   0.001,
        "generate":      0.002,
        "prproj":        0.001,
    }
    estimated_total = audio_duration * sum(SPEED_COEFFICIENTS.values())

---

## Pipeline

    Stage 1: Extract Audio
      Per clip -> WAV (16kHz mono) + concatenate -> full_audio.wav + clip_offsets.json

    Stage 2: Global Diarization
      pyannote on full_audio.wav -> speaker intervals [start, end, SPEAKER_XX]

    Stage 3: Per-clip Whisper
      word_timestamps=True per clip -> words with local timecodes

    Stage 4: Speaker Mapping
      Local word -> global timecode -> speaker via diarization

    Stage 5: Generate Outputs
      xlsx, SRT, TXT, internal JSON, Premiere JSON, transcript.json, meta.json
      Multi-camera: per-camera XLSX + transcript.json

    Stage 5b: Generate Premiere Project
      Template .prproj -> inject clips on V1/A1 timeline

For single file (Variant B): Stage 1 skips concatenation, clip_offsets = {clip_id: 0.0}.

**Multi-camera (Variant C):**
- Stage 1: per_clip аудио → в папки камер через `get_clip_dir()`. full_audio.wav → в глобальный `_transcription/`.
- Stage 2: глобальная диаризация (full_audio.wav) — обеспечивает consistent speaker IDs между камерами.
- Stage 3: Whisper per clip, wav_path через `get_clip_dir()`.
- Stage 5: per-clip файлы → в камеры. Per-camera XLSX + transcript.json → в папки камер. Combined файлы → в корень.

---

## Stage 1: Extract Audio

    ffmpeg -i C5090.MP4 -ar 16000 -ac 1 -vn {clip_dir}/C5090_audio.wav

**v2.13:** `clip_dir = get_clip_dir(ctx, clip_id)` — маршрутизирует в папку камеры при multi-camera.

**Конкатенация (Python/soundfile, не ffmpeg -c copy):**

    import soundfile as sf
    import numpy as np

    clip_offsets = {}
    all_audio = []
    current_offset = 0.0

    for clip_id in sorted(clips):
        wav_path = get_clip_dir(ctx, clip_id) / f"{clip_id}_audio.wav"
        data, sr = sf.read(wav_path)
        clip_offsets[clip_id] = current_offset
        current_offset += len(data) / sr
        all_audio.append(data)

    combined = np.concatenate(all_audio)
    sf.write(f"{transcription_dir}/full_audio.wav", combined, 16000)

> Почему не ffmpeg concat: WAV concat через ffmpeg не обновляет заголовки. soundfile гарантирует точные офсеты.

**Один файл:** конкатенация пропускается, full_audio.wav = копия единственного аудио.

### Обработка ошибок ffmpeg

После каждого вызова ffmpeg проверяется returncode. При ненулевом коде:

    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_excerpt = result.stderr[-500:]  # последние 500 символов
        print(f"ERROR: ffmpeg failed for {clip_id} (exit code {result.returncode})")
        print(f"stderr: {stderr_excerpt}")
        sys.exit(1)

Скрипт завершается немедленно — частичное аудио не имеет смысла для дальнейшего пайплайна.

---

## Stage 2: Global Diarization

    from pyannote.audio import Pipeline
    pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=HF_TOKEN)

**Workaround: pyannote 4.0.3 + torchcodec incompatibility.**
pyannote 4.x uses torchcodec for audio I/O, but torchcodec can't find FFmpeg shared libs.
Fix: load audio in-memory via soundfile and pass as dict:

    import soundfile as sf
    audio_data, sample_rate = sf.read(str(full_audio_path))
    waveform = torch.tensor(audio_data, dtype=torch.float32).unsqueeze(0)
    diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)

**pyannote 4.x returns DiarizeOutput dataclass** (not Annotation):

    annotation = getattr(diarization, "speaker_diarization", diarization)
    for turn, _, speaker in annotation.itertracks(yield_label=True): ...

**Маппинг спикеров на UUID (для Premiere):**

    speaker_map = {}
    for i, label in enumerate(unique_speakers):
        speaker_map[label] = {"id": str(uuid.uuid4()), "name": f"Speaker {i + 1}"}

---

## Stage 3: Per-clip Whisper

    model = whisper.load_model("large-v3")
    for clip_id in clips:
        clip_dir = get_clip_dir(ctx, clip_id)
        result = model.transcribe(
            str(clip_dir / f"{clip_id}_audio.wav"),
            word_timestamps=True, language=None, verbose=False
        )

**Важно:** Whisper returns `probability`, not `confidence`. Mapping:
    Whisper: word["probability"]  ->  Internal JSON: word["confidence"]

### Checkpointing

После успешной транскрипции каждого клипа raw-результат Whisper сохраняется как checkpoint:

    # После model.transcribe()
    checkpoint_path = get_clip_dir(ctx, clip_id) / f"{clip_id}_whisper_raw.json"
    with open(checkpoint_path, "w") as f:
        json.dump(result, f, ensure_ascii=False)

При `--resume` со стадии 3 скрипт проверяет наличие checkpoint-файлов. Уже транскрибированные клипы (с валидным `{clip_id}_whisper_raw.json`) пропускаются:

    for clip_id in clips:
        checkpoint = get_clip_dir(ctx, clip_id) / f"{clip_id}_whisper_raw.json"
        if resuming and Path(checkpoint).exists():
            result = json.load(open(checkpoint))
            log(f"Loaded cached whisper result for {clip_id}")
            continue
        result = model.transcribe(...)
        json.dump(result, open(checkpoint, "w"), ensure_ascii=False)

Это позволяет возобновить работу после сбоя на середине Stage 3 без повторной транскрипции уже обработанных клипов.

### Обработка ошибок transcribe

Каждый вызов `model.transcribe()` обёрнут в try/except. При ошибке транскрипции клипа:

    for clip_id in clips:
        try:
            result = model.transcribe(audio_path, word_timestamps=True, ...)
        except Exception as e:
            log(f"WARNING: Whisper failed for {clip_id}: {e}")
            result = {"text": "", "segments": [], "language": language or ""}

Используется пустой результат и обработка продолжается. Клип получит пустые сегменты в выходных файлах (аналогично B-roll без речи). Ошибка логируется в лог-файл.

---

## Stage 4: Speaker Mapping

    def assign_speaker(word, clip_id, clip_offsets, diarization_segments):
        global_mid = clip_offsets[clip_id] + (word["start"] + word["end"]) / 2
        for segment in diarization_segments:
            if segment["start"] <= global_mid <= segment["end"]:
                return segment["speaker"]
        return find_nearest_speaker(global_mid, diarization_segments)

**Группировка в сегменты:**
- Последовательные слова одного спикера -> один сегмент
- Смена спикера -> новый сегмент (Whisper-сегмент разбивается если пересекает границу спикеров)
- Пауза > 1.5с внутри одного спикера -> новый сегмент

---

## Stage 5: Generate Outputs

### 5.1 Структура файлов (Вариант A — flat папка)

    Interview/
    +-- C5090.MP4, C5091.MP4, C5092.MP4
    +-- Interview_transcript.xlsx
    +-- Interview_transcript.json
    +-- Interview.prproj
    +-- Interview_transcription/
        +-- full_audio.wav
        +-- clip_offsets.json
        +-- diarization.json
        +-- speakers.json
        +-- combined_transcript.json
        +-- meta.json
        +-- Interview_transcribe_20260113_125047.log
        +-- per_clip/
            +-- C5090/
            |   +-- C5090_audio.wav
            |   +-- C5090_transcript.json
            |   +-- C5090_transcript.srt
            |   +-- C5090_transcript.txt
            |   +-- C5090_premiere_transcript.json
            +-- C5091/ ...
            +-- C5092/ ...

### 5.1b Структура файлов (Вариант B — один файл)

    SomeFolder/
    +-- C5090.MP4
    +-- C5090_transcript.xlsx
    +-- C5090_transcript.json
    +-- C5090.prproj
    +-- C5090_transcription/
        +-- full_audio.wav
        +-- clip_offsets.json, diarization.json, speakers.json
        +-- combined_transcript.json, meta.json
        +-- C5090_transcribe_20260113_125047.log
        +-- per_clip/
            +-- C5090/
                +-- C5090_audio.wav, C5090_transcript.json
                +-- C5090_transcript.srt, C5090_transcript.txt
                +-- C5090_premiere_transcript.json

### 5.1c Структура файлов (Вариант C — multi-camera)
    YTCG Gambling Ru/
    +-- FX3/
    |   +-- RYA-FX3-0090.MP4 ... (исходники)
    |   +-- FX3_transcript.xlsx              (per-camera, 8 клипов FX3)
    |   +-- FX3_transcript.json                 (per-camera)
    |   +-- FX3_transcription/
    |       +-- per_clip/
    |           +-- RYA-FX3-0090/
    |           |   +-- RYA-FX3-0090_audio.wav
    |           |   +-- RYA-FX3-0090_whisper_raw.json
    |           |   +-- RYA-FX3-0090_transcript.json
    |           |   +-- RYA-FX3-0090_transcript.srt
    |           |   +-- RYA-FX3-0090_transcript.txt
    |           |   +-- RYA-FX3-0090_premiere_transcript.json
    |           +-- RYA-FX3-0091/ ...
    +-- ZVE1/
    |   +-- RYA-ZVE1-1674.MP4 ... (исходники)
    |   +-- ZVE1_transcript.xlsx             (per-camera, 8 клипов ZVE1)
    |   +-- ZVE1_transcript.json                (per-camera)
    |   +-- ZVE1_transcription/
    |       +-- per_clip/
    |           +-- RYA-ZVE1-1674/ ...
    +-- YTCG Gambling Ru_transcript.xlsx     (combined, все 16 клипов)
    +-- YTCG Gambling Ru_transcript.json        (combined)
    +-- YTCG Gambling Ru.prproj              (combined Premiere)
    +-- YTCG Gambling Ru_transcription/      (global pipeline internals)
        +-- full_audio.wav                     (все 16 клипов склеены)
        +-- meta.json
        +-- diarization.json                   (глобальная диаризация)
        +-- speakers.json
        +-- clip_offsets.json
        +-- combined_transcript.json
        +-- YTCG Gambling Ru_transcribe_*.log

> **Правило именования:**
> - Папка: {project_name}_transcription (root), {camera}_transcription (per-camera)
> - XLSX: {project_name}_transcript.xlsx (combined), {camera}_transcript.xlsx (per-camera)
> - Transcript JSON: {project_name}_transcript.json (combined), {camera}_transcript.json (per-camera)
> - Лог: {project_name}_transcribe_{timestamp}.log (корень _transcription)
> - Файлы per_clip: всегда с префиксом {clip_id}_

### Per-camera output generation
    # В stage5_generate_outputs():
    groups = ctx.get("subfolder_groups")
    if groups:
        for grp_name, grp in groups.items():
            grp_xlsx = generate_xlsx(ctx, args, clip_filter=grp["clip_ids"],
                output_path=grp["source_dir"] / f"{grp_name}_transcript.xlsx")
            grp_proj = generate_project_json(ctx, args, clip_filter=grp["clip_ids"],
                output_path=grp["source_dir"] / f"{grp_name}_transcript.json")

Функции `generate_xlsx()` и `generate_project_json()` принимают опциональные параметры:
- `clip_filter: list[str]` — список clip_id для включения (None = все)
- `output_path: Path` — путь для сохранения (None = default в корень)

---

### 5.2 meta.json

    {
      "version": "2.14",
      "status": "completed",
      "created_at": "2026-01-13T12:20:00Z",
      "updated_at": "2026-01-13T12:50:47Z",
      "project_name": "Interview",
      "input_type": "folder",
      "input_path": "/Volumes/RYA Blue/Interview",
      "params": {
        "num_speakers": 2, "whisper_model": "large-v3",
        "language": null, "device": "mps"
      },
      "clips": ["C5090", "C5091", "C5092"],
      "total_duration_sec": 1124.9,
      "stages_completed": ["1", "2", "3", "4", "5", "5b"],
      "stages_timing": {
        "1_extract_audio": 135.2, "2_diarization": 588.4,
        "3_whisper": 1112.8, "4_speaker_mapping": 4.1, "5_generate_outputs": 7.9,
        "5b_premiere_project": 2.1
      },
      "total_time": 1850.5
    }

**Поле `status`:**
- `"in_progress"` — устанавливается в начале пайплайна (после preflight), сохраняется в meta.json перед первой стадией
- `"completed"` — устанавливается после успешного завершения всех запрошенных стадий
- Используется при `--resume` для предупреждения о неполном предыдущем запуске (см. раздел --resume логика)

---

### 5.3 Internal JSON (C5090_transcript.json)

    {
      "version": "2.14",
      "created_at": "2026-01-13T12:50:47Z",
      "whisper_model": "large-v3",
      "clip_id": "C5090",
      "clip_file": "C5090.MP4",
      "duration": 324.5,
      "clip_offset_in_full": 0.0,
      "language": "en",
      "segments": [
        {
          "id": 0,
          "start": 0.5,
          "end": 5.2,
          "speaker": "SPEAKER_00",
          "text": "Hello and welcome to Connect Group channel.",
          "words": [
            {"word": "Hello", "start": 0.5, "end": 0.82, "confidence": 0.95},
            {"word": "and", "start": 0.85, "end": 0.98, "confidence": 0.91}
          ],
          "avg_confidence": 0.93,
          "low_confidence": false
        }
      ],
      "stats": {
        "total_words": 1542, "total_segments": 87,
        "speakers": {
          "SPEAKER_00": {"segments": 44, "words": 820, "duration": 165.2},
          "SPEAKER_01": {"segments": 43, "words": 722, "duration": 148.8}
        },
        "avg_confidence": 0.89, "low_confidence_segments": 3
      }
    }

> **Whisper probability -> confidence:** маппинг при создании internal JSON.
> **words[].speaker убран** — спикер определяется на уровне сегмента.

---

### 5.4 Premiere Transcript JSON (C5090_premiere_transcript.json)

    {
      "language": "en-us",
      "segments": [
        {
          "language": "en-us",
          "speakerId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
          "words": [
            {"confidence": 0.95, "duration": 320, "eos": false, "start": 500, "tags": [], "text": "Hello", "type": "word"},
            {"confidence": 0.91, "duration": 130, "eos": false, "start": 850, "tags": [], "text": "and", "type": "word"},
            {"confidence": 0.88, "duration": 200, "eos": false, "start": 980, "tags": [], "text": "welcome", "type": "word"},
            {"confidence": 0.92, "duration": 150, "eos": false, "start": 1180, "tags": [], "text": "to", "type": "word"},
            {"confidence": 0.97, "duration": 280, "eos": false, "start": 1330, "tags": [], "text": "Connect", "type": "word"},
            {"confidence": 0.96, "duration": 250, "eos": false, "start": 1610, "tags": [], "text": "Group", "type": "word"},
            {"confidence": 0.94, "duration": 320, "eos": true, "start": 1860, "tags": [], "text": "channel", "type": "word"},
            {"confidence": 1.0, "duration": 0, "eos": false, "start": 2180, "tags": [], "text": ".", "type": "punctuation"}
          ]
        }
      ],
      "speakers": [
        {"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "name": "Speaker 1"},
        {"id": "f0e1d2c3-b4a5-6789-0fed-cba987654321", "name": "Speaker 2"}
      ]
    }

**Конвертация Whisper -> Premiere:**

    word["start"] (сек)          -> start (мс)       int(start * 1000)
    word["end"]-word["start"]    -> duration (мс)    int((end-start) * 1000)
    word["probability"]          -> confidence       as-is float
    ---                          -> eos              True if followed by .?!
    ---                          -> type             "word" | "punctuation"
    ---                          -> tags             [] (future: ["filler"])
    SPEAKER_XX                   -> speakerId        speakers.json -> UUID

**Пунктуация — split_word_punctuation:**

    import re
    PUNCT_PATTERN = re.compile(r'^(.*?)([.?!,;:\u2026\-"\']+)$')
    EOS_CHARS = set('.?!')

    def split_word_punctuation(whisper_word):
        text = whisper_word["word"].strip()
        word_start_ms = int(whisper_word["start"] * 1000)
        word_end_ms = int(whisper_word["end"] * 1000)
        duration_ms = word_end_ms - word_start_ms
        match = PUNCT_PATTERN.match(text)

        if match and match.group(1):
            # "channel." -> word "channel" (eos=true) + punct "."
            clean_word, punct = match.group(1), match.group(2)
            return [
                {"text": clean_word, "start": word_start_ms, "duration": duration_ms,
                 "confidence": whisper_word["probability"],
                 "eos": any(c in EOS_CHARS for c in punct), "tags": [], "type": "word"},
                {"text": punct, "start": word_end_ms, "duration": 0,
                 "confidence": 1.0, "eos": False, "tags": [], "type": "punctuation"}
            ]
        elif match and not match.group(1):
            # "..." -> only punctuation
            return [{"text": match.group(2), "start": word_start_ms, "duration": duration_ms,
                     "confidence": whisper_word["probability"], "eos": False, "tags": [], "type": "punctuation"}]
        else:
            # clean word
            return [{"text": text, "start": word_start_ms, "duration": duration_ms,
                     "confidence": whisper_word["probability"], "eos": False, "tags": [], "type": "word"}]

**Язык:** "en" -> "en-us", "ru" -> "ru-ru", unknown -> "??-??"

---

### 5.5 SRT (C5090_transcript.srt)

    1
    00:00:00,500 --> 00:00:05,200
    [Speaker 1] Hello and welcome to Connect Group channel.

    2
    00:00:05,300 --> 00:00:12,100
    [Speaker 2] Thank you for having me, Roman.

### 5.6 TXT (C5090_transcript.txt)

    [00:00:00] Speaker 1:
      Hello and welcome to Connect Group channel.

    [00:00:05] Speaker 2:
      Thank you for having me, Roman.

### 5.7 XLSX ({project_name}_transcript.xlsx)

Рядом с видеофайлами (не в _transcription/). **3 листа: Transcript, Summary, Media.**

**Multi-camera:** per-camera XLSX содержит те же 3 листа, но только для клипов данной камеры.

#### Sheet 1: "Transcript" — полная транскрипция по клипам

Заголовок: синий фон, белый bold текст. Клипы разделены голубыми строками-разделителями.

    [C5402  |  5:24  |  842 words  |  45 segments]        <- clip separator (light blue)
    Timecode | #  | Clip  | Start | End   | Duration | Words | Speaker   | Text              | Confidence
    00:00:00 | 1  | C5090 | 0.500 | 5.200 | 4.70     | 7     | Speaker 1 | Hello and welc... | 0.930
    00:00:05 | 2  | C5090 | 5.300 | 12.10 | 6.80     | 9     | Speaker 2 | Thank you for...  | 0.870

**Форматирование:**
- Low confidence (< 0.7): ячейка Text жёлтым фоном
- Заголовки: bold white on blue (#2F5496), freeze row 1
- Clip separators: light blue (#D6E4F0) merged row with clip name, duration, words, segments
- Text: wrap_text, vertical=top, width=80
- Duration/Confidence: rounded to 2-3 decimals (no float artifacts)
- Thin bottom border on data rows

#### Sheet 2: "Summary" — статистика проекта + план-факт

    Project:  YTAI_Edit
    Version:  2.14
    Date:     2026-03-03
    Language: en
    Speakers: 1

    Clip   | File       | Duration | Words | Segments | Speakers | Avg Conf | Low Conf
    C5402  | C5402.MP4  | 5:24     | 842   | 45       | 2        | 0.890    | 3
    C5091  | C5091.MP4  | 6:28     | 1021  | 52       | 2        | 0.920    | 1
    TOTAL  |            | 18:45    | 4650  | 187      |          |          |

    Stage          | Estimated | Actual  | Delta
    Extract audio  | 11s       | 1s      | -10s
    Diarization    | 53s       | 14s     | -39s
    Whisper        | 4m 09s    | 4m 36s  | +27s    (red if >30% over)
    TOTAL          | 5m 14s    | 4m 51s  | -23s

#### Sheet 3: "Media" — техническая информация по клипам

Per-clip метаданные, собранные через `get_media_info()` (ffprobe JSON output).

    Clip   | File       | Duration | Resolution | FPS | Frames | Video Codec           | Bitrate (Mbps) | Pixel Format          | Audio                  | Size (GB) | Created          | Timecode
    C5402  | C5402.MP4  | 2:36     | 3840x2160  | 25  | 3900   | H264 High 4:2:2       | 140            | yuv422p10le (10-bit)  | PCM_S16BE 48kHz stereo | 2.69      | 2026-03-02 12:48 | 22:14:01:11

---

## Stage 5b: Generate Premiere Project (.prproj)

### Обзор

Скрипт генерирует готовый .prproj файл с клипами на таймлайне. Открыл — и сразу смотришь/режешь.

### Размещение

    Вариант A (flat):         Interview/Interview.prproj
    Вариант B (файл):         SomeFolder/C5090.prproj
    Вариант C (multi-camera): YTCG Gambling Ru/YTCG Gambling Ru.prproj (combined)

Имя файла = project_name + ".prproj"

### Подход: Template-based generation

    1. Взять шаблон Untitled.prproj (Premiere 2026, Version="45")
    2. Распаковать gzip -> XML
    3. Подставить: project name, media files, sequence clips
    4. Запаковать XML -> gzip -> .prproj

Шаблон хранится в ~/YTAI/templates/premiere_template.prproj

### Цепочка объектов для каждого клипа

Для каждого видеофайла генерируются объекты:

    Media (ObjectUID=uuid)
      FilePath = абсолютный путь к видео
      RelativePath = ./filename.MP4
      ActualMediaFilePath = абсолютный путь
      AudioStream, VideoStream

    MasterClip (ObjectUID=uuid)
      Clips: VideoClip + AudioClip + TranscriptClip
      Name = filename

    VideoClipTrackItem (ObjectID=N)
      Start = cumulative ticks (предыдущий End)
      End = Start + duration_ticks
      SubClip -> Clip -> MasterClip
      ComponentOwner -> VideoComponentChain (Motion, Opacity)

    AudioClipTrackItem (ObjectID=N+1)
      Start/End = те же что у Video
      SubClip -> Clip -> MasterClip
      ComponentOwner -> AudioComponentChain

### Единицы времени

    FrameRate (video) = 10160640000 ticks/frame (при 25fps)
    1 секунда = 254016000000 ticks (10160640000 * 25)
    duration_ticks = duration_seconds * 254016000000

    Для расчёта из ffprobe:
    duration_sec = float(ffprobe_output)
    duration_ticks = int(duration_sec * 254016000000)

### Sequence настройки

Из шаблона (не менять):
    - 3840x2160 (4K)
    - FrameRect: 0,0,3840,2160
    - 3 video tracks (V1, V2, V3)
    - 4 audio tracks (A1-A4) + master
    - BT.709, 8-bit, Display-Referred

Клипы размещаются на V1/A1 подряд.

### Генерация ObjectID

    MAX_TEMPLATE_ID = max ObjectID в шаблоне
    new_id = MAX_TEMPLATE_ID + 1  (инкремент для каждого нового объекта)

    ObjectUID = uuid4() для каждого нового MasterClip, Media, Sequence source


### Дополнительные поля Media объекта

    Media:
      Start = MediaInPoint из ffprobe (обычно 0, но может отличаться)
      ConformedAudioRate = 5292000  (стандарт для 48kHz -> Premiere internal)
      FileKey = uuid4()
      ContentAndMetadataState = uuid4()
      ImplementationID = "1fa18bfa-255c-44b1-ad73-56bcd99fceaf" (из шаблона, одинаковый)

### Обновление Sequence

После добавления клипов обновить:

    MZ.WorkOutPoint = End последнего клипа (в тиках)
    Sequence name (<n>) = project_name

### Параметр --no-prproj

    --no-prproj     пропустить генерацию .prproj (по умолчанию: генерировать)

---

## Служебные JSON файлы

### clip_offsets.json

    {
      "version": "2.14", "created_at": "2026-01-13T12:22:00Z",
      "clips": [
        {"clip_id": "C5090", "file": "C5090.MP4", "offset": 0.0, "duration": 324.5},
        {"clip_id": "C5091", "file": "C5091.MP4", "offset": 324.5, "duration": 388.3},
        {"clip_id": "C5092", "file": "C5092.MP4", "offset": 712.8, "duration": 412.1}
      ],
      "total_duration": 1124.9
    }

### diarization.json

    {
      "version": "2.14", "created_at": "2026-01-13T12:30:00Z",
      "num_speakers": 2, "total_duration": 1124.9,
      "segments": [
        {"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00"},
        {"start": 5.3, "end": 12.1, "speaker": "SPEAKER_01"},
        {"start": 12.5, "end": 18.7, "speaker": "SPEAKER_00"}
      ]
    }

### speakers.json

    {
      "version": "2.14", "created_at": "2026-01-13T12:30:00Z",
      "speakers": {
        "SPEAKER_00": {"id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "name": "Speaker 1"},
        "SPEAKER_01": {"id": "f0e1d2c3-b4a5-6789-0fed-cba987654321", "name": "Speaker 2"}
      }
    }

> Обновляется stage 03 (speaker_id): "Speaker 1" -> "Roman"

### {project_name}_transcript.json

**Главный файл проекта** — центральный манифест со всеми данными. Генерируется в корне проекта (рядом с XLSX).
Содержит: параметры транскрипции, спикеров, глобальную статистику, структуру проекта с полными путями,
и для каждого клипа — media metadata, пути к файлам, сегменты с полями `use`/`notes` для UXP-плагина.

**Multi-camera:** per-camera transcript.json содержит только клипы данной камеры. Пути к файлам — относительные от расположения transcript.json.

**Flat project:**

    {
      "version": "2.14",
      "project": "Interview",
      "created_at": "2026-01-13T12:50:47Z",
      "language": "en",
      "params": {"whisper_model": "large-v3", "language": null, "num_speakers": 2},
      "speakers": {
        "SPEAKER_00": {"id": "uuid-...", "name": "Speaker 1"},
        "SPEAKER_01": {"id": "uuid-...", "name": "Speaker 2"}
      },
      "stats": {
        "total_duration": 1124.9, "total_words": 4650, "total_segments": 187,
        "num_speakers": 2, "avg_confidence": 0.89, "low_confidence_segments": 7
      },
      "structure": {
        "type": "folder",
        "input_path": "/Volumes/RYA Blue/Interview",
        "transcription_dir": "Interview_transcription",
        "work_dir": "/Volumes/RYA Blue/Interview",
        "transcription_dir_full": "/Volumes/RYA Blue/Interview/Interview_transcription",
        "transcript_json": "/Volumes/RYA Blue/Interview/Interview_transcript.json",
        "transcript_xlsx": "/Volumes/RYA Blue/Interview/Interview_transcript.xlsx",
        "video_files": [
          "/Volumes/RYA Blue/Interview/C5090.MP4",
          "/Volumes/RYA Blue/Interview/C5091.MP4",
          "/Volumes/RYA Blue/Interview/C5092.MP4"
        ]
      },
      "clips": [
        {
          "clip_id": "C5090", "filename": "C5090.MP4",
          "duration": 380.5, "offset": 0.0,
          "media": {
            "width": 3840, "height": 2160, "fps": 25.0, "nb_frames": 9512,
            "video_codec": "h264", "video_profile": "High 4:2:2",
            "video_bitrate_mbps": 140.5, "pix_fmt": "yuv422p10le", "bit_depth": 10,
            "audio_codec": "pcm_s24le", "audio_sample_rate": 48000, "audio_channels": 2,
            "file_size_bytes": 2890137600, "creation_time": "2026-01-13T10:30:00Z",
            "timecode": "22:14:01:11"
          },
          "files": {
            "premiere_transcript": "per_clip/C5090/C5090_premiere_transcript.json",
            "transcript": "per_clip/C5090/C5090_transcript.json",
            "srt": "per_clip/C5090/C5090_transcript.srt",
            "txt": "per_clip/C5090/C5090_transcript.txt"
          },
          "segments": [
            {
              "id": 0, "start": 0.5, "end": 5.2, "duration": 4.7,
              "timecode": "00:00:00", "words": 12,
              "speaker": "Speaker 1", "speaker_id": "SPEAKER_00",
              "text": "Hello and welcome...",
              "confidence": 0.93, "low_confidence": false,
              "use": false, "notes": ""
            }
          ]
        }
      ]
    }

**Multi-camera combined transcript.json — блок structure:**

    "structure": {
      "type": "multi-camera",
      "input_path": "/Volumes/RYA T7 Black/YTCG Gambling Ru",
      "cameras": {
        "FX3": {
          "path": "FX3",
          "clips": 8,
          "clip_ids": ["RYA-FX3-0090", "RYA-FX3-0091", ...],
          "transcription_dir": "FX3/FX3_transcription",
          "xlsx": "FX3/FX3_transcript.xlsx",
          "transcript_json": "FX3/FX3_transcript.json"
        },
        "ZVE1": {
          "path": "ZVE1",
          "clips": 8,
          "clip_ids": ["RYA-ZVE1-1674", "RYA-ZVE1-1675", ...],
          "transcription_dir": "ZVE1/ZVE1_transcription",
          "xlsx": "ZVE1/ZVE1_transcript.xlsx",
          "transcript_json": "ZVE1/ZVE1_transcript.json"
        }
      },
      "combined": {
        "transcription_dir": "YTCG Gambling Ru_transcription",
        "xlsx": "YTCG Gambling Ru_transcript.xlsx",
        "transcript_json": "YTCG Gambling Ru_transcript.json",
        "prproj": "YTCG Gambling Ru.prproj"
      }
    }

**Per-camera transcript.json (FX3_transcript.json) — блок structure:**

    "structure": {
      "type": "camera",
      "camera": "FX3",
      "input_path": "/Volumes/RYA T7 Black/YTCG Gambling Ru",
      "transcription_dir": "FX3_transcription"
    }

> **Роль файла:** Единая точка входа для UXP-плагина и внешних потребителей.
> Word-level данные НЕ включены (доступны через `files.premiere_transcript`).
> Поля `use` / `notes` — для редакторского workflow (маркировка сегментов).
> Блок `structure` — описывает расположение проекта и его файловую структуру.
> Включает полные абсолютные пути: `work_dir`, `transcription_dir_full`, `transcript_json`, `transcript_xlsx`, `video_files`.

---

### combined_transcript.json

**Слова НЕ включены** — доступны в per-clip JSON.

    {
      "version": "2.14", "created_at": "2026-01-13T12:50:47Z", "project": "Interview",
      "total_duration": 1124.9, "num_speakers": 2, "language": "en",
      "clips": ["C5090", "C5091", "C5092"],
      "segments": [
        {"id": 0, "clip_id": "C5090", "local_start": 0.5, "local_end": 5.2,
         "global_start": 0.5, "global_end": 5.2,
         "speaker": "SPEAKER_00", "text": "Hello and welcome...", "avg_confidence": 0.93}
      ],
      "stats": {
        "total_words": 4650, "total_segments": 187,
        "speakers": {
          "SPEAKER_00": {"segments": 95, "words": 2500, "duration": 570.3},
          "SPEAKER_01": {"segments": 92, "words": 2150, "duration": 530.7}
        },
        "avg_confidence": 0.89, "low_confidence_segments": 7
      }
    }

---

## Прогресс и логирование

### Визуализация

Скрипт использует ANSI-цвета для яркого терминального интерфейса:

**Цвета (class C):**
- BG_CYAN/BG_GREEN/BG_BLUE — фоновые для заголовков стадий
- GREEN/YELLOW/RED/CYAN/MAGENTA — текстовые акценты
- CLEAR_LINE (`\033[2K\r`) — перезапись строки для анимации

**Компоненты:**
- `progress_bar()` — Unicode прогресс-бар с градиентом цвета (cyan->yellow->green)
- `class Spinner` — анимированный braille spinner с таймером (daemon thread)
- `class PipelineProgress` — общий прогресс пайплайна с весами стадий

**Подавление мусорного вывода:**
- `warnings.filterwarnings("ignore", module=r"pyannote\.audio\.core\.io")` — torchcodec warnings
- `warnings.filterwarnings("ignore", module=r"speechbrain|whisper")` — прочие
- Stage 3: `_FilterStdout` wrapper — фильтрует "Detected language" из stdout Whisper, сохраняя Spinner видимым
- Stage 3: `_FilterStderr` wrapper — фильтрует tqdm progress bars

### Terminal Output

    ========================================================
      Preflight Checks                              (white on blue BG)
    v ffmpeg
    v Python packages
    v Whisper model: large-v3
    v HuggingFace token
    v Device: mps
    ...

    ========================================================
      YTAI Transcribe v2.14                         (white on cyan BG)
    --------------------------------------------------------
      Project:    Interview
      Files:      12 | 64:00 | 2 speakers
      Model:      large-v3 | MPS
      Estimated:  ~28-35 min
    ========================================================

    # Multi-camera дополнительно:
      Cameras:    FX3 (8) + ZVE1 (8) = 16 clips

### Pipeline Dashboard (print_status_table)

Comprehensive dashboard displayed BEFORE each stage starts and AFTER each stage completes.
Shows ALL 6 stages regardless of `--stages` filter.

    +------------------------------------------------------------+
    |  YTAI_Edit | 3 clips | 5:56  4/6 done | Elapsed 3m39s | ETA ~1s
    +------------------------------------------------------------+
    |     Stage               Plan   Actual    Delta           |
    |------------------------------------------------------------|
    |  v  Extract audio       11s ->     1s    -10s            |
    |  v  Diarization         53s ->    14s    -39s            |
    |  v  Whisper          4m09s -> 3m24s     -45s            |
    |  v  Speaker map          0s ->     0s     -0s            |
    |  >  Generate             1s  running...                  |
    |  .  Premiere proj        0s                              |
    +------------------------------------------------------------+
    |  ===================>  67%  3m39s/5m15s  -1m35s          |
    +------------------------------------------------------------+

**Status icons:**
- `v` — completed (green), shows Plan -> Actual with colored delta
- `>` — currently running (cyan, bold label), shows Plan + "running..."
- `.` — pending (dim), shows Plan estimate, drift-adjusted if available
- `-` — skipped (not in this run, not completed)

**Header:** project name, clips count, duration, X/6 done, elapsed, ETA
**Drift-adjusted ETA:** uses ratio of actual/estimated for completed stages (capped 0.3x-3.0x)

### Лог файл

Path: {transcription_dir}/{project_name}_transcribe_{timestamp}.log
Один файл, без подпапки.

Contents:
- Configuration: project, input, clips, duration, speakers, model, language, device
- Clips: per-clip offset, duration, filename, resolution, FPS, codec
- Diarization: speakers, durations, gap %
- Transcription: total words/segments, avg confidence, low confidence count
- Low-confidence segment details
- Per-clip details: words, segments, confidence, per-speaker stats
- Timings (Plan vs Fact): estimated vs actual per stage with delta
- Output files: full listing with file sizes (KB)

---

## --resume логика

    1. Check {transcription_dir}/meta.json exists
    2. Read stages_completed from meta.json
    3. Verify clips match current video files
    4. Validate parameters against saved params
    5. Check previous run status
    6. Restore timing data from previous stages
    7. Determine first incomplete stage
    8. Load intermediate data (clip_offsets.json, diarization.json, speakers.json)
    9. If resuming from stage 5+, load clip_transcripts from per_clip JSONs
       v2.13: uses get_clip_dir() for subfolder-aware paths
    10. Handle corrupted per-clip JSONs (JSONDecodeError -> fall back to stage 3)
    11. Continue from first incomplete stage

    If meta.json missing/corrupted:
       WARN Cannot resume. Run without --resume to start fresh.
    If clips changed:
       WARN Clips changed (was 12, now 14). Run without --resume.
    If corrupted transcript JSON:
       WARN Corrupted {clip}_transcript.json, re-running from stage 3.

### Проверка параметров при resume

При `--resume` скрипт сравнивает текущие параметры `-n`, `--model` (`-m`), и `--language` с сохранёнными в `meta.json.params`. При расхождении выводится предупреждение:

    WARN Parameter mismatch with previous run:
      num_speakers: saved=2, current=3
      whisper_model: saved=large-v3, current=medium
      language: saved=en, current=ru

### Проверка статуса предыдущего запуска

При `--resume` проверяется поле `status` в meta.json. Если `"status": "in_progress"`, выводится предупреждение:

    WARN Previous run was incomplete (status: in_progress). Some data may be partial.

---

## Edge Cases

### Слово в gap между спикерами
    find_nearest_speaker: find closest diarization segment by time distance

### Клип без речи (B-roll)
- Create files with empty segments
- xlsx: row with [no speech]
- Premiere JSON: empty segments, speakers preserved

### Разный язык для клипов
- language per clip in internal JSON
- Premiere JSON: language per segment
- combined_transcript: main language = most frequent

### Длинный сегмент (>30s one speaker)
- Split by pauses > 1.0s between words
- If no pauses, keep as-is

### Только пунктуация ("..." or dashes)
- split_word_punctuation handles: empty match.group(1) -> punctuation only
- Covered: . ? ! , ; : - ... quotes

### Один файл без речи
- All output files created with empty segments
- xlsx: one row [no speech]
- Terminal warning

### Шаблон .prproj не найден
- ~/YTAI/templates/premiere_template.prproj отсутствует
- WARN Premiere template not found, skipping .prproj generation
- Остальные файлы генерируются нормально

### Multi-camera: подпапка без видео
- Audio/ (только WAV) — игнорируется (нет VIDEO_EXTENSIONS)
- .hidden_folder/ — игнорируется (startswith('.'))

### Multi-camera: дублирующиеся clip stems между камерами
- Проверяется в detect_input(), ошибка: `ERROR: duplicate clip stems found`

---

## Совместимость с stage 03 (speaker_id)

Input:
1. combined_transcript.json — content analysis (text, no words)
2. speakers.json — file to update

Output:
1. speakers.json: "Speaker 1" -> "Roman"
2. Can regenerate xlsx, SRT, TXT with real names
3. Does NOT touch Premiere JSON — update via plugin or separate script

---

## Место в общем пайплайне YTAI

### Полная цепочка обработки

    [Съёмка] -> Папка с клипами (C5090.MP4, C5091.MP4, ...)
                    |          или подпапки камер (FX3/, ZVE1/)
                    v
    +----------------------------------------------------------+
    |  Stage 02: transcribe_project v2.14  (ЭТОТ СКРИПТ)      |
    |                                                          |
    |  Вход:  папка/файл/подпапки камер + число спикеров       |
    |  Выход: _transcription/ + xlsx + transcript.json + .prproj  |
    |         - per-clip: json, srt, txt, premiere_transcript   |
    |         - общие: combined_transcript, speakers, diarize  |
    |         - multi-camera: per-camera xlsx + transcript.json   |
    +--------------------+-------------------------------------+
                         |
           +-------------+----------------+
           v             v                v
    +-----------+  +------------+  +-------------------+
    | Stage 03: |  | Premiere   |  | Ручной просмотр   |
    | speaker_id|  | UXP Plugin |  | xlsx / txt        |
    +-----+-----+  +------+-----+  +-------------------+
          |               |
          v               v
    speakers.json   Attach Transcripts
    с именами       (premiere_transcript.json -> Text Panel)
          |               |
          v               v
    +---------------------------------------------+
    |  Stage 05: editing (XML, edit brief, etc.)  |
    +---------------------------------------------+

### Что передаётся между этапами

**transcribe (02) -> speaker_id (03):**
- combined_transcript.json — LLM анализирует текст сегментов
- speakers.json — speaker_id обновляет name: "Speaker 1" -> "Roman"

**transcribe (02) -> Premiere UXP Plugin:**
- per_clip/*_premiere_transcript.json — плагин привязывает к клипам через Transcript API
- speakers.json — плагин читает UUID маппинг для спикеров в Text Panel
- transcript.json — единая точка входа с метаданными и путями

**transcribe (02) -> editing (05):**
- combined_transcript.json — для генерации edit brief, chapters, highlights
- clip_offsets.json — для маппинга глобальных таймкодов на клипы
- xlsx — для ручного просмотра и пометок редактором

### Что НЕ делает этот скрипт

- НЕ определяет реальные имена спикеров (это stage 03)
- НЕ обновляет Premiere JSON с именами (это UXP плагин)
- НЕ создаёт XML нарезки для Premiere (это stage 05; raw .prproj с клипами создаётся на stage 5b)
- НЕ анализирует видеоконтент / B-roll (это stage 04, будущее)
- НЕ генерирует chapters, descriptions, shorts (stages 05-08)

---

## Команды

    # Активировать окружение
    source ~/YTAI/environment/.venv_transcribe/bin/activate

    # Flat проект (auto-detect speakers)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project "/path/to/Interview" --language en -y

    # Flat проект (2 speakers)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project "/path/to/Interview" -n 2 -y

    # Multi-camera проект
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project '/Volumes/RYA T7 Black/YTCG Gambling Ru' -y

    # Single file
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project "/path/to/video.MP4" --language en -y

    # Dry-run (быстрый, без загрузки ML моделей)
    python ~/YTAI/scripts/02_transcribe/transcribe_project_v2.14.py \
      --project '/Volumes/RYA T7 Black/YTCG Gambling Ru' --dry-run

    # Resume
    python ... --project "/path/to/Interview" --resume

    # Specific stages
    python ... --project "/path/to/Interview" --stages 3,4,5

    # Set language
    python ... --project "/path/to/Interview" --language en

    # Without Premiere project
    python ... --project "/path/to/Interview" --no-prproj

---

## Changelog

### v2.14
- **Переименование:** `_project.json` → `_transcript.json` (единообразие с `_transcript.xlsx`)
- **Расширение `structure`:** добавлены полные абсолютные пути (`work_dir`, `transcription_dir_full`, `transcript_json`, `transcript_xlsx`, `video_files`)
- **Ключ `"project_json"`** → `"transcript_json"` в structure блоке multi-camera

### v2.13
- **Multi-camera support:** рекурсивный поиск видео (`rglob`), автодетект подпапок камер
- **Per-camera outputs:** XLSX + transcript.json в папках камер с `clip_filter`
- **Combined outputs:** XLSX + transcript.json + .prproj в корне проекта (все клипы)
- **`get_clip_dir()`** — маршрутизация per_clip файлов в папки камер
- **`subfolder_groups`** — структура для multi-camera mode (None = flat/backward compat)
- **Dry-run fast path:** пропускает загрузку ML моделей (torch, whisper, pyannote), только ffprobe scan
- **Backward compatible:** плоские папки и одиночные файлы работают как v2.12

### v2.12
- Removed LUT stage (5c) and all LUT-related code
- Removed Brief sheet from XLSX (3 sheets: Transcript, Summary, Media)
- Replaced brief.json with `{project}_transcript.json` — comprehensive project manifest
  - Includes: params, speakers, global stats, per-clip media metadata, file paths, segments with use/notes
