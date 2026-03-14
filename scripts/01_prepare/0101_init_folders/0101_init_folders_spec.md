# 0101_init_folders — Specification v1.0.0

Инициализация v3.0 структуры папок и организация медиафайлов.

**Вход:** Папка проекта с сырыми файлами (MP4, XML, WAV, .cube) в корне или подпапках
**Выход:** v3.0 структура папок + файлы перемещены в правильные директории

---

## Назначение

Стадия Init — первый шаг фазы Prepare. Создаёт структуру папок v3.0 из шаблона и автоматически перемещает медиафайлы из корня проекта в нужные директории.

Логика встроена в `run_pipeline.py` (функция `run_init`), отдельного скрипта нет.

## Алгоритм

### Шаг 1: Deep merge шаблона

Рекурсивный merge из `YTAI_Folder_Templates/Type1_Footage` или `Type2_Production`:

- Создаёт все отсутствующие директории
- Копирует файлы из шаблона (если не существуют)
- Пропускает `.gitkeep`
- Идемпотентно: повторный запуск безопасен

```python
_deep_merge_template(template_path, project, log)
```

### Шаг 2: Premiere project файлы

- `01_Media/{project_name}.prproj` — rename из `PROJECT_NAME.prproj` или touch
- `Source/{project_name}_Source.prproj` — только для production
- `{project_name}.gdoc` — только для production

```python
_create_premiere_project(project, folder_type, log)
```

### Шаг 3: File Discovery

Сканирование проекта (`os.walk`) для поиска неорганизованных файлов:

```python
discover_media_files(project, log)
```

**Классификация файлов:**

| Расширение | Тип | Куда |
|-----------|-----|------|
| `.mp4`, `.mov`, `.m4v`, `.mts`, `.avi`, `.mkv` | Video | → `Source/Video/` |
| `.wav` с паттерном `TX##_MIC###_*` | DJI audio | → `99_Pipeline/DJI_Audio/` |
| `.wav` без DJI паттерна | Other audio | ⏭ skip (оставить на месте) |
| `.cube` | LUT | → `Source/LUT/` |
| `.xml` | Sidecar | → `Transcription/per_clip/{clip}/` |

**Skip directories (не сканируются):**

| Тип | Правило |
|-----|---------|
| v3.0 managed | `01_Media`, `02_Exports`, `03_Shorts`, `04_Thumbnail`, `YouTube`, `99_Pipeline` |
| System/hidden | `.Spotlight-V100`, `.fseventsd`, `.Trashes`, `__MACOSX` и т.д. |
| Archive | Имя начинается с `archive`, `old_`, `backup`, `_old`, `_backup` (case-insensitive) |
| Dot-dirs | Любая папка с `.` в начале имени |

### Шаг 4: Organize (перемещение файлов)

```python
organize_media_files(project, discovered, log)
```

**Video, DJI, LUT:** прямое перемещение (`shutil.move`) в целевую папку.

**XML sidecars → per_clip/{clip}/:**
1. Извлечь clip_id из имени XML: `RYA-FX3-0099M01.XML` → `RYA-FX3-0099`
2. Sony convention: strip `M##` суффикс
3. Проверить, что clip_id совпадает с stem видеофайла
4. Создать `per_clip/{clip_id}/` и переместить XML туда
5. Fallback: если нет совпадения → `Source/Video/`

### Шаг 5: Cleanup

Удаление пустых директорий, оставшихся после перемещения файлов. Не трогает v3.0 managed dirs.

## DJI Raw Audio Pattern

Регулярное выражение для определения сырых DJI файлов:

```python
DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}', re.IGNORECASE)
```

Примеры совпадений:
- `TX02_MIC037_20260306_102304_orig.wav` ✓
- `TX02_MIC038_20260306_102304_orig.wav` ✓
- `RYA-FX3-0099_TX02.wav` ✗ (это synced output, не raw)

## Шаблоны папок

```
YTAI_Folder_Templates/
├── Type1_Footage/          ← минимальная (--type footage)
│   ├── 01_Media/
│   │   └── Source/
│   │       ├── Video/
│   │       ├── Audio/
│   │       ├── LUT/
│   │       ├── Transcription/per_clip/
│   │       └── Setup/logs/
│   └── 99_Pipeline/DJI_Audio/
│
└── Type2_Production/       ← полная (--type production, default)
    ├── 01_Media/
    │   ├── PROJECT_NAME.prproj
    │   ├── Assets/          Music/ SFX/ Graphics/ Stock/ Fonts/
    │   └── Source/
    │       ├── PROJECT_NAME_Source.prproj
    │       ├── Video/
    │       ├── Audio/
    │       ├── LUT/
    │       ├── Transcription/per_clip/
    │       └── Setup/logs/
    ├── 02_Exports/
    ├── 03_Shorts/
    ├── 04_Thumbnail/
    ├── YouTube/
    ├── 99_Pipeline/DJI_Audio/
    └── PROJECT_NAME.gdoc
```

## Ключевые функции в run_pipeline.py

| Функция | Описание |
|---------|----------|
| `run_init()` | Оркестратор: merge + prproj + discover + organize |
| `_deep_merge_template()` | Рекурсивный merge шаблона |
| `_create_premiere_project()` | Создание/rename .prproj и .gdoc |
| `discover_media_files()` | Поиск неорганизованных файлов |
| `organize_media_files()` | Перемещение файлов в v3.0 структуру |
| `_xml_to_clip_id()` | Извлечение clip_id из XML (Sony M## convention) |
| `_cleanup_empty_dirs()` | Удаление пустых папок после перемещения |

## Проверка завершённости

```python
def check_init(project: Path) -> bool:
    return (project / "01_Media" / "Source" / "Video").is_dir()
```

Init всегда перезапускается (идемпотентно), но check используется для `--list`.

## Edge cases

| Ситуация | Поведение |
|----------|----------|
| Файл уже в целевой папке | `⚠ Already exists, skip` |
| XML без совпадения с video | Fallback → `Source/Video/` |
| Пустая папка `Backup/` после move | Удаляется cleanup |
| Повторный запуск | Безопасно, merge идемпотентен |
| Нет видеофайлов в корне | "All files already in place ✓" |
