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

## Cut Review & Montage TZ (ревью ката, ТЗ монтажёру)

When the user wants to **review an editor's cut**, build the editor's ТЗ, audit on-screen titles,
regenerate the review timeline / doc tabs after his edits, or build a montage list from raw sources
(keywords: "ревью ката", "ревью сборки", "ТЗ монтажёру", "аудит экранов", "правки в доке",
"монтажный лист из исходников", "review cut"): use the **`/review` skill** (`.claude/skills/review/SKILL.md`).

It drives stage `scripts/05_editing/0509_review_cycle/` (`review.py`, KB 4.7 /kb/review-cycle/):
card `{project}/00_Setup/05_Review/review_card.json` + channel profile `YTs/{CH}/review_profile.json`,
Memex runs frames/OCR/transcript/VLM/LLM autonomously, ONE cloud pass per film (≤10 agents, text-only),
all surfaces (6-layer timeline, doc tabs, sheet, Drive, phone brief) from one `pravki`. Never write
ad-hoc scripts into a project and never Read frames/large JSON into the thread (see skill hygiene).

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
│                                 кадр-в-кадр) + Transcription + 00_LUT. Живёт ВНУТРИ проекта,
│                                 не папкой-соседкой (решение 17.08.2026, YTCH10)
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
