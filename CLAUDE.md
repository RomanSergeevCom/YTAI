# YTAI — YouTube Production Pipeline

## Assembly Brief Generation

When the user asks to create or update an Assembly brief (keywords: "Assembly brief", "создай brief", "обнови brief", "pre_edit_brief"):

### Step 1: Load knowledge base

Read these files IN ORDER before generating anything:

1. `scripts/05_editing/0501_brief/INSTRUCTIONS.md` — full workflow, response format, analysis algorithm
2. `scripts/05_editing/0501_brief/project_knowledge/editing_rules.md` — video structure, what to cut, color schema, pacing rules
3. `scripts/05_editing/0501_brief/project_knowledge/output_format.md` — JSON schema (segments, screens, project, changelog)
4. **Channel profile** from `YTs/{CHANNEL}/{CHANNEL}.md`:
   - User provides channel code (e.g. `YTCR`) or it's extracted from project name
   - `YTCR` → read `YTs/YTCR/YTCR.md`, `YTCG` → read `YTs/YTCG/YTCG.md`

### Step 2: Auto-resolve paths from project folder

User provides only **channel code** + **project path**. Find everything else automatically:

```
Given: Channel=YTCR, Project=/Volumes/RYA T7 Black/YTCR01_Arty_Dzis

Extract project code:  YTCR01  (regex: ^(YT[A-Z]{2,4}\d+)_ from folder name)

Auto-resolve:
  Transcript:  {project}/00_Setup/YTCR01_Claude4_assembly.json
  Output dir:  {project}/00_Setup/02_Assembly/
  Next version: scan 02_Assembly/ for existing files → determine v{N}
  Output JSON: 02_Assembly/YTCR01_Assembly_v{N}_in.json
  Output HTML: 02_Assembly/YTCR01_review_v{N}.html
```

### Step 3: Generate outputs

Produce **3 things**:

1. **JSON brief** → write directly to `00_Setup/02_Assembly/{CODE}_Assembly_v{N}_in.json`
2. **HTML review** → write directly to `00_Setup/02_Assembly/{CODE}_review_v{N}.html`
3. **Chat summary** — compact overview: block table + YouTube chapters + 1-3 key notes

### Important overrides (vs INSTRUCTIONS.md defaults)

- **`transcript` field = FULL TEXT of the segment's tc_in→tc_out range** — include the complete spoken text for the timecode range covered by this segment. For full transcript segments, this is the entire segment text. For sub-segments (Hook excerpts), this is the text corresponding to the extracted portion. The brief must cover ALL spoken words — every word in the source video must appear in exactly one segment's transcript field (USE=TRUE or USE=FALSE). No gaps allowed.
- **Word timestamps available** — Claude4_assembly.json includes `words[]` array per segment with per-word timing `{w: "word", s: "M:SS.sss", e: "M:SS.sss"}`. Use for precise sub-segment tc: `tc_in = first_word.s`, `tc_out = last_word.e + smart_padding`. Smart padding = `min(gap_to_next_word, 0.3)` — adds natural air after the word when there's a gap, but never captures the next word when words are contiguous (gap=0). `transcript` field = concatenation of `words[first..last].w`.
- **HTML review = ALWAYS generated** — written to disk as a file the user opens in browser. Not a Claude artifact.
- **Files written directly** — no MCP needed, Claude Code has direct filesystem access.

### Round-trip workflow (updating brief after Premiere edit)

When the user provides a `_out.json` (marker export from Premiere):

1. Read the `_out.json` marker export
2. Read the previous `_in.json` brief (detect version from filename)
3. Parse editor comments from markers (structured as `Speaker: X | text | B-roll: Y | Notes: Z. EDITOR NOTES`)
4. Apply changes → write new `_v{N+1}_in.json` + updated HTML with:
   - Changelog section at top
   - Editor notes highlighted in yellow
   - CHANGED badges on modified segments
   - Strikethrough on removed segments

## Multicam Word-Sync (сборка мультикам-таймлайна после съёмки)

When the user wants to **sync/assemble a multicam shoot day onto one timeline**
(keywords: "синхрон мультикама", "собери мультикам", "sync cameras", "несколько
камер в одну секвенцию", "word-sync", "клипы по транскриптам"):

**Follow the runbook STEP BY STEP with its gates:**
`scripts/05_editing/0500_uxp/docs/wordsync/WORDSYNC_RUNBOOK.md`

Do NOT sync multicam by creation_time alone — device clocks lie (proven: ±5–22 min
quartz error, recorder filenames ±9.5 min off). Speech (per-word transcripts) is the
anchor. Tools: `scripts/999_extra/wordsync_multicam/` (wordsync.py → make_ingest.py →
validate_ingest.py → qc_html.py → UXP «Build Ingest»). Theory:
`wordsync_multicam_README.md` there; KB: yt.rya.ae/kb/multicam-wordsync/.

## Folder Sync / Mirror

When the user wants to mirror/sync a project between SSD and Google Drive (keywords:
"синхрон", "зеркало проекта", "синхронизируй проект", "sync project", "mirror to Drive",
"обнови зеркало", "sync YTCR.."): use the **`/sync` skill** (`.claude/skills/sync/SKILL.md`).

It drives the cross-cutting Sync layer `scripts/11_sync/1101_mirror/` — a **bidirectional**
full-project mirror via `rclone bisync` (both versions kept on conflict; `--max-delete` +
`--check-access` safety). NOT a content pipeline stage — invoked on-demand per project.
Routine sync runs locally; privileged/destructive ops (force mass-delete, folder-dup
cleanup, Shared Drive perms) escalate to Winston. Mirror ≠ editor handoff (one-way copy →
Winston, см. память `reference_editor_handoff_drive`).

Entry: `python3 scripts/11_sync/1101_mirror/mirror.py --project <path|CODE> --dry-run`.

## Media Prep (подготовка носителей перед съёмкой)

When the user wants to **clear camera cards before a shoot** — check whether a card's contents
are on Google Drive, upload the gaps, wipe the card, or fix volume labels (keywords: "подготовь
карты", "почисти карту", "что на карте есть на диске", "проверь архивы", "метки карт", "card
prep", "wipe card"): use the **Media layer** `scripts/14_media/1401_card_prep/` (cross-cutting,
on-demand — like Sync and Acquire, NOT part of `run_pipeline`). KB 0.5 `/kb/media-prep/`.

**Правило: карту чистим только после того, как каждый её файл подтверждён на Drive.**
Подтверждение = имя + **точный размер в байтах**; по одному имени HEVC-прокси из
`01_Source_Proxy/` засчитывается за оригинал, и карта стирается зря.

- Сверять по **всему** Drive, не «папка в папку» — клипы одного дня расходятся по разным проектам.
- Shared Drive **`Archive`** обязателен в индексе: там прошлые выгрузки карт (`Archive:DJI-TX/`).
- Целые `*_orig.wav` → `{проект}/99_Pipeline/DJI_Audio/`; срезы `__S##` целый файл не заменяют.
- Ничейный футаж → `YTCH S3/_unassigned_footage/{источник}_{дата}/`.
- Журнал операций → `YTAI:_ops_log/media_prep/{год}/` (хронология, поиск задним числом).
- Чистим **с Mac, не форматом в камере** (формат сбрасывает метку); `.Trashes` на карте — явно.

Entry: `python3 scripts/14_media/1401_card_prep/media_prep.py --audit --report`
(без `--apply` всё сухо). Парк и метки — `cards.json` + KB 0.2 `/kb/storage/`.

## Editing Proxies (прокси монтажёру)

When the user wants to **build or rebuild a proxy kit** — собрать прокси проекту, пересобрать
комплект канала, проверить уже собранные прокси (keywords: «собери прокси», «прокси монтажёру»,
«пересобери комплект», «проверь прокси», «кадр-в-кадр», «build proxies»): use the **proxy stage**
`scripts/16_proxy/` (cross-cutting, on-demand — как Sync, Media и Color; НЕ часть `run_pipeline`).
KB 3.4 `/kb/proxy/`.

**Прокси — лёгкая копия, а не мелкая.** Единственное, ради чего она делается, — вес файла.
Всё остальное обязано совпасть, потому что подмена на оригинал — это смена одной корневой
папки. Контракт из восьми пунктов проверяется **на каждом клипе**: разрешение · fps строкой
(29.97 = `30000/1001` ≠ `30`) · число кадров по пакетам · **битность с источника** (10 бит →
`main10`/`p010le`, 8 бит → `main`/`yuv420p`; не повышать и не понижать) · имена и относительные
пути 1:1 · число дорожек и каналов (не схлопывать — L и R часто разные микрофоны) ·
**таймкод с источника** (Sony держит его на data-дорожке `rtmd`, `format_tags` пуст) ·
цветовые теги как есть (**не форсить bt709 на логе**; FX3 не несёт тегов вообще — прокси
обязана остаться такой же пустой).

- ⚠️ **Рецепт живёт в одном месте** — `16_proxy/1601_build/contract.py`. Своей копии заводить
  нельзя: именно три разошедшиеся копии стоили комплекта YTCH (441 прокси 8-битными и без TC).
- ⚠️ **Не жать то, что уже лёгкое.** Айфон копируется байт-в-байт. Клип с недекодируемой
  дорожкой (`apac` 4ch) не перекодируется вообще — ни одна дорожка не должна пропасть.
- ⚠️ `-pix_fmt p010le` на входе даёт в файле `yuv420p10le` — сверять pix_fmt строкой нельзя.
- Ночная пересборка канала — `rebuild.py`: кодирование и заливка внахлёст, стейджинг с потолком
  (кодировщик ждёт заливку, иначе очередь обгонит место на диске).

Entry: `python3 scripts/16_proxy/1601_build/proxy.py --src <01_Source> --dst <01_Source_Proxy> --dry-run`

## Color (проявка, экспозиция, покраска)

When the user wants to **choose or apply colour** — подобрать проявку под камеру, выбрать
look канала, выставить экспозицию по клипам, собрать раскладку цвета, пополнить библиотеку
лутов (keywords: «цвет», «проявка», «покраска», «look канала», «экспозиция по клипам»,
«витрина лутов», «раскладка цвета», «библиотека кубов», «lut», «color»): use the **Color layer**
`scripts/15_color/` (cross-cutting, on-demand — как Sync, Media и Proxy; НЕ часть `run_pipeline`).
KB 3.8 `/kb/luts/`.

**Цвет — это ступени, а не один куб.** До сентября 2026 три куба
(`01_bright/02_normal/03_dark_scene`) делали проявку и покраску сразу, и все были под S-Log3:
на YTEVO03 это покрасило **61 клип DJI из 163** чужой математикой. Теперь:
проявка (log → Rec.709, детерминированно по **гамме+камере**) · экспозиция (**число в стопах**,
не лут) · покраска (look, ДНК канала, один на канал).

- ⚠️ **Незнакомая гамма = отказ, а не «mismatch и поехали».** Ровно эта снисходительность и
  стоила 37 % съёмочного дня. Клип без проявки не должен молча остаться без слоя.
- ⚠️ **Стоп витрины ≠ стоп Lumetri, множитель ровно 2,4.** Превью считает экспозицию фильтром
  ffmpeg поверх гамма-кодированного Rec.709, Lumetri линеаризует ДО экспозиции. Кадры, которые
  Роман утверждал, верны как изображение — расходится только число. Предел ползунка ±7.
- ⚠️ **Параметр Lumetri адресуется по ИНДЕКСУ, а не по имени** — имена дублируются
  (`Look` ×2, `Input LUT` ×2, `Saturation` ×4), а сеттер панели берёт последнее совпадение.
- ДНК канала — `YTs/{КАНАЛ}/color_profile.json`; выбор дня —
  `{проект}/00_Setup/01_Ingest/{CODE}_color_choice.json`; раскладка — `{CODE}_color_plan.json`.
- ⚠️ **Кубы не в git, манифест в git.** Глобальное правило `*.cube` в `.gitignore` добавлять
  нельзя — под git лежат 12 кубов (шаблоны папок и бандл панели).
- ⛔ На таймлайн раскладка пока не ложится: проба Premiere (`Input LUT` / `Exposure`) не сделана.

Entry: `python3 scripts/15_color/1503_color_apply/color_apply.py --project <путь>`
(без `--apply` всё сухо). Витрина выбора — `1502_lut_pick/lut_board.py`, библиотека — `1501_lut_library/`.

## Cut Review & Montage TZ (ревью ката, ТЗ монтажёру)

When the user wants to **review an editor's cut**, build the editor's ТЗ, audit on-screen titles,
regenerate the review timeline / doc tabs after his edits, or build a montage list from raw sources
(keywords: "ревью ката", "ревью сборки", "ТЗ монтажёру", "аудит экранов", "правки в доке",
"монтажный лист из исходников", "review cut"): use the **`/review` skill** (`.claude/skills/review/SKILL.md`).

It drives stage `scripts/05_editing/0509_review_cycle/` (`review.py`, KB 6.2 /kb/review-cycle/):
card `{project}/00_Setup/05_Review/review_card.json` + channel profile `YTs/{CH}/review_profile.json`,
Memex runs frames/OCR/transcript/VLM/LLM autonomously, ONE cloud pass per film (≤10 agents, text-only),
all surfaces (6-layer timeline, doc tabs, sheet, Drive, phone brief) from one `pravki`. Never write
ad-hoc scripts into a project and never Read frames/large JSON into the thread (see skill hygiene).

## Knowledge Archives (где искать материал для сценария)

Когда нужен факт, картинка или сюжет для видео — **путь не угадывать**, брать из карты:

```
YTs/{CHANNEL}/library.json          машиночитаемая карта архивов канала
```

Для YTUVI (драгоценные камни) — два архива на `T7-Blue-2-RYA`, у каждого зеркало
в Shared Drive «YTUVI»:

| Корень | policy | Что |
|---|---|---|
| `YTUVI-Digital_Originals` | **primary** | 20 лабораторий и журналов, 37 ГБ. Искать ВСЕГДА здесь первым |
| `YTUVI-Book_Scans` | **fallback** | Сканы учебников Романа. Качество хуже цифры — только если в primary пусто, с пометкой «⚠️ скан книги» |

- Поиск: `python3 scripts/999_extra/gem_kb/search.py "<запрос>" [--kind figure|image|text]`
- ⚠️ **Индекс — не надмножество.** У части источников записей мало относительно числа
  файлов (Rivista, Lotus, ICA): там `search.py` промахнётся, идти надо в их каталог
  сюжетов `_INDEX.html`. У кого какой — поле `catalog` и `search_hint` в `library.json`.
- Пересобрать карту: `python3 scripts/999_extra/gem_kb/build_library.py`
  (`--check` — сверить, не переписывая). Текст правится в `library_seed.json`,
  цифры измеряются с диска и руками не набираются.
- ⚠️ Старые планы и вкладки могут нести путь `01_SSEF/01_Book/…` или `01_ScanBook-SSEF` —
  это **сканы книг**, ныне `YTUVI-Book_Scans` (см. `aliases` в карте).

## Content Acquisition (Download)

When the user wants to **download external/social content of a guest** for B-roll/inserts
(keywords: "скачай инсту/телеграм/ютуб", "выгрузи сторис/посты/аватарки", "download his
Instagram/Telegram/YouTube", "контент для перебивок"): use the **Acquisition layer**
`scripts/12_acquire/1201_social/` (cross-cutting, on-demand — like Sync, NOT part of
`run_pipeline`). Full methods/auth/gotchas: `scripts/12_acquire/1201_social/INSTRUCTIONS.md`.

- **Telegram** (`tg_stories_dl.py` + `tg_login2.py`): stories/avatars/channels via MTProto
  user-session (bots can't read stories). Public Telegram Desktop key default — no my.telegram.org.
  Gotcha: borrowed-key session gets revoked on bulk load → resume + relogin (may take 2-3 codes).
- **Instagram** (`ig_download.py` = gallery-dl + 1.1.1.1 DNS shim): posts/reels/photos + captions.
  Needs Chrome cookies (`--cookies-from-browser chrome`); Tailscale MagicDNS fails for cdninstagram.
- **YouTube** (`yt_download.sh` = yt-dlp): video/playlist/channel max quality + subs.

Save into the project as Source by origin: `{project}/01_Media/Source/Video/<handle>_<platform>/`
(see memory `feedback_source_vs_stock`). Network/auth setup escalates to Winston.

## Pipeline Commands

```bash
# Activate environment
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Prepare (init folders + extract audio + DJI sync)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT"

# Transcribe only
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --only transcribe --language en --no-pause

# Full pipeline (prepare + transcribe)
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --all --language en --no-pause

# Check status
python ~/YTAI/scripts/run_pipeline.py "$PROJECT" --list

# Export markers from Premiere
python ~/YTAI/scripts/05_editing/0506_marker_export/export_markers_from_prproj.py --project "$PROJECT"
```

## Project Structure (v4.1)

```
{project}/
├── {project}.prproj
├── {project}_Source.prproj
├── {project}.gdoc
├── 00_Setup/
│   ├── logs/
│   ├── pipeline/
│   ├── {CODE}_Claude4_assembly.json
│   ├── 01_Ingest/
│   │   ├── {CODE}_ingest.json
│   │   └── {CODE}_audio_map.json
│   ├── 02_Assembly/
│   │   ├── {CODE}_Assembly_v1_in.json
│   │   ├── {CODE}_Assembly_v2_out.json
│   │   └── {CODE}_review_v1.html
│   ├── 03_Pre-Edit/
│   ├── 04_ScreenCues/
│   └── 05_Review/
├── 01_Source/
│   ├── Video/{scene}/*.MP4
│   ├── Audio/{scene}/*_TX*.wav
│   ├── LUT/*.cube
│   └── Transcription/
│       ├── {CODE}_transcript.json
│       ├── transcripts/{CODE}_2_Assembly_v{N}_transcript.srt
│       ├── captions/{CODE}_2_Assembly_v{N}_captions.srt
│       └── {scene}/
├── 01_Source_Proxy/            ← прокси-комплект монтажёру: зеркало сцен 01_Source (HEVC ~8 Мбит/с,
│                                 кадр-в-кадр, битность и таймкод С ИСТОЧНИКА) + Transcription
│                                 + 00_LUT. Живёт ВНУТРИ проекта, не папкой-соседкой
│                                 (решение 17.08.2026, YTCH10). Контракт — этап 16_proxy
├── 02_Edit/
│   ├── Sound/
│   ├── AE_Projects/
│   ├── AE_Templates/
│   ├── Stock/
│   └── Fonts/
├── 03_Exports/
├── 04_Shorts/
├── 05_Thumbnail/
├── 06_YouTube/
└── 99_Pipeline/DJI_Audio/
```

## Project Naming

- All projects: `YT{XX}{NN}_{Guest_Name}` (e.g. `YTCR01_Arty_Dzis`, `YTCG37_Hadi_Dawani`)
- Вместо имени гостя можно короткое латинское описание — через подчёркивания: `YT{XX}{NN}_kratkoe_opisanie` (например `YTEVO02_evolution_manifesto`)
- Channel code: `YT` + 2-4 letters (YTCR, YTCG, YTRF...)
- Project code: channel + number (YTCR01, YTCG37...)
- Regex: `^(YT[A-Z]{2,4}\d+)_`
