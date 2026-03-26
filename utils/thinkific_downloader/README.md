# Thinkific Downloader

CLI-пайплайн для работы с уроками Thinkific:

1. Находит прямой video URL из Thinkific / Wistia / `.m3u8` / `.mp4`.
2. Создает отдельную project-папку под урок.
3. Скачивает видео в эту папку.
4. Запускает транскрибацию через существующий `020101_transcribe`.
5. Делает screenshots по сменам сцены и кладет их в отдельную подпапку.
6. Описывает каждый screenshot через Ollama vision model → `screenshots_descriptions.json`.

## Где лежит

- Скрипт: `/Users/romansergeev/YTAI/utils/thinkific_downloader/download_thinkific.py`
- Spec: `/Users/romansergeev/YTAI/utils/thinkific_downloader/thinkific_downloader_spec.md`
- DOCX batch script: `/Users/romansergeev/YTAI/utils/thinkific_downloader/process_docx_thinkific.py`
- DOCX batch spec: `/Users/romansergeev/YTAI/utils/thinkific_downloader/process_docx_thinkific_spec.md`
- Screenshot descriptions: `/Users/romansergeev/YTAI/utils/thinkific_downloader/describe_screenshots.py`
- Screenshot descriptions spec: `/Users/romansergeev/YTAI/utils/thinkific_downloader/describe_screenshots_spec.md`

## Что получается на выходе

После запуска создается отдельная папка проекта:

```text
downloads/
└── Phase_2_-_1._Intro/
    ├── Phase_2_-_1._Intro.mp4
    ├── Phase_2_-_1._Intro.info.json
    ├── Phase_2_-_1._Intro_transcript.xlsx
    ├── Phase_2_-_1._Intro_transcription/
    │   ├── Phase_2_-_1._Intro_transcript.json
    │   ├── Phase_2_-_1._Intro_transcript.srt
    │   ├── Phase_2_-_1._Intro_1_Ingest_captions.srt
    │   └── ...
    ├── screenshots/
    │   ├── scene_0001_t00-00-12.480.jpg
    │   └── ...
    ├── screenshots_manifest.json
    ├── screenshots_descriptions.json
    └── project_manifest.json
```

Транскрипция лежит рядом с видео, а screenshots идут в отдельную папку внутри того же проекта.

## Зависимости

- Python 3.11+
- `ffmpeg`
- опционально `yt-dlp`
- существующий transcription pipeline:
  `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py`
- по умолчанию используется Python из:
  `/Users/romansergeev/YTAI/environment/.venv_transcribe/bin/python3`
- для описаний скриншотов: Ollama + модель `minicpm-v` (опционально)

## Быстрый старт

### Полный pipeline

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/download_thinkific.py \
  "https://ed-s-school-81f3.thinkific.com/courses/take/YTGS4/lessons/67892293-phase-2-intro?wvideo=obyeqz0swb" \
  --title "Phase_2_-_1._Intro"
```

### Только скачать видео

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/download_thinkific.py \
  "https://ed-s-school-81f3.thinkific.com/courses/take/YTGS4/lessons/67892293-phase-2-intro?wvideo=obyeqz0swb" \
  --title "Phase_2_-_1._Intro" \
  --download-only
```

### С cookies для закрытого урока Thinkific

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/download_thinkific.py \
  "https://your-school.thinkific.com/courses/take/course-name/lessons/12345678-lesson" \
  --cookie-header "sessionid=...; _thinkific_session=...;"
```

### Проверить структуру без запуска

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/download_thinkific.py \
  "https://ed-s-school-81f3.thinkific.com/courses/take/YTGS4/lessons/67892293-phase-2-intro?wvideo=obyeqz0swb" \
  --title "Phase_2_-_1._Intro" \
  --dry-run
```

## Полезные флаги

- `--output-dir` — корневая папка, где будут создаваться project-папки.
- `--title` — имя проекта и видеофайла.
- `--download-only` — скачать только видео и metadata.
- `--no-transcribe` — пропустить транскрибацию.
- `--no-screenshots` — пропустить screenshots.
- `--no-descriptions` — пропустить AI-описания скриншотов.
- `--vision-model` — Ollama vision model (по умолчанию `minicpm-v`).
- `-n`, `--speakers` — число спикеров для `020101_transcribe`.
- `-m`, `--model` — Whisper model для `020101_transcribe`.
- `--language` — язык для транскрибации.
- `--scene-threshold` — чувствительность screenshot extraction.
- `--scene-max-width` — ограничение ширины screenshots.
- `--engine ffmpeg` — всегда качать через `ffmpeg`.
- `--engine yt-dlp` — использовать `yt-dlp`, если установлен.

## Как screenshots определяются

Screenshots извлекаются не через semantic-анализ, а через `ffmpeg` scene detection.
То есть инструмент ловит заметные визуальные изменения кадра: новые слайды, графику, смену композиции, вставки, иллюстрации.

Если кадров получается слишком много:

- увеличь `--scene-threshold`, например до `0.24` или `0.30`;
- или отключи screenshots через `--no-screenshots`.

## Описания скриншотов (AI)

После извлечения screenshots каждый кадр отправляется в Ollama vision model (`minicpm-v`) для текстового описания. Описания сохраняются в `screenshots_descriptions.json`.

Это превращает визуальные captures в текст для базы знаний: тип слайда, видимый текст, ключевая тема, визуальные элементы.

### Настройка Ollama

```bash
brew install ollama
ollama serve
ollama pull minicpm-v
```

### Standalone запуск на готовой папке

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/describe_screenshots.py \
  downloads/Phase_2_-_1._Intro/
```

### Отключение

```bash
# В pipeline
python3 download_thinkific.py <url> --no-descriptions

# Или другая модель
python3 download_thinkific.py <url> --vision-model llava
```

Если Ollama не запущен, pipeline продолжит работу без описаний.

## Ограничения

- Скрипт не обходит DRM.
- Если Thinkific-школа использует нестандартный embed или backend-защиту, может понадобиться доработка extraction-логики.
- Для закрытых страниц Thinkific нужны валидные cookies.
- Scene detection не понимает смысл изображения, он только реагирует на визуальные изменения.

## DOCX batch режим

Если у тебя есть большой `.docx` с lesson-ссылками, текстом, картинками и дополнительными ресурсами, используй batch-скрипт:

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/process_docx_thinkific.py \
  "/Users/romansergeev/Downloads/YTCG.docx"
```

Что он делает:

- находит lesson-блоки по заголовкам вроде `Phase_...mp4`;
- берет main Thinkific lesson link;
- создает project-папку через тот же layout, что и обычный downloader;
- сохраняет `document_notes.md`, встроенные картинки из DOCX и таблицы;
- пытается скачать extra-links из блока в `linked_resources/`;
- может также делать транскрибацию и screenshots для каждого main lesson video.

Для быстрой проверки структуры без скачивания:

```bash
python3 /Users/romansergeev/YTAI/utils/thinkific_downloader/process_docx_thinkific.py \
  "/Users/romansergeev/Downloads/YTCG.docx" \
  --limit 3 \
  --dry-run
```
