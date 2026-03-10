# Output JSON Format: {project}_edit_brief.json

JSON contains two objects: `segments` (array) and `project` (settings).

## segments[]

Each element is one video segment. Numbering is sequential across all clips.

### Required Fields

| Field | Type | Format | Description |
|-------|------|--------|-------------|
| `segment_id` | string | `seg_001`, `seg_002`... | Sequential numbering |
| `source_file` | string | `C5402.MP4` | Filename from transcript.json (clip's `filename` field) |
| `tc_in` | string | `MM:SS.s` | Start time (local, within clip). From segment's `start` field |
| `tc_out` | string | `MM:SS.s` | End time (local, within clip). From segment's `end` field |
| `block` | int | 1-99 | Block number. Block 99 = Cut/Unused |
| `block_name` | string | max 50 chars | Block name ("Hook", "Government Vision", etc.) |
| `use` | string | `"TRUE"` / `"FALSE"` | Include in ASSEMBLY sequence? String, not boolean |

### Optional Fields

| Field | Type | Default | Max | Description |
|-------|------|---------|-----|-------------|
| `segment_name` | string | auto | 100 chars | Segment name ("Opening question about business") |
| `speaker` | string | — | — | Who is speaking (from `speaker` field in transcript) |
| `transcript` | string | — | 500 chars | Segment text. Truncate if longer than 500 |
| `track` | string | `"V1"` | — | Always `"V1"` — the panel decides inclusion based on `use` field |
| `color` | string | by block | — | One of: Cyan, Blue, Green, Yellow, Red, Magenta, Orange, Purple |
| `priority` | int | 1 | 1-9 | 1 = primary take, 2 = alternative take (→ ALT/Yellow in Review), 9 = cut/noise (→ CUT/Red in Review) |
| `is_chapter` | string | `"FALSE"` | — | `"TRUE"` on the FIRST segment of each block to create a Chapter marker |
| `broll_note` | string | — | 200 chars | B-roll suggestion for the editor |
| `notes` | string | — | 500 chars | Notes for the editor (rationale, cut reason, context) |

### Timecode Conversion (seconds -> MM:SS.s)

```
start: 1.46   -> tc_in: "00:01.5"
end:   88.76  -> tc_out: "01:28.8"
start: 119.42 -> tc_in: "01:59.4"
end:   151.88 -> tc_out: "02:31.9"
```

Formula: `MM = floor(seconds / 60)`, `SS.s = seconds % 60` (one decimal place)

### Important Rules

1. **tc_in / tc_out** — local time within the clip (segment's `start`/`end` fields in transcript.json)
2. **Segments with use="FALSE"** must also be included — they are kept in the brief for review and reference
3. **transcript** — truncate to 500 characters, no line breaks
4. **segment_id** numbered sequentially across all clips
5. **source_file** — exact filename with extension
6. **Block 99** — reserved for cuts, noise, expletives, between-takes content. Always color **Red**, priority **9**
7. **track** — always `"V1"` for all segments
8. **priority** — 1 = primary take (used in ASSEMBLY), 2 = alternative take (→ **ALT/Yellow** in Review), 9 = cut/noise (→ **CUT/Red** in Review). Other values → **SKIP/Purple** in Review
9. **Color for use=FALSE segments:** priority 2 keeps its **block color** (e.g. Green for Hook alt take), priority 9 is always **Red** (block 99). In Review timeline, colors are overridden by category (CUT=Red, ALT=Yellow, SKIP=Purple)
10. **Block ordering matters**: segments are sorted by `block` number in the ASSEMBLY sequence. **Within the same block, segments are placed in BRIEF ORDER** (the order they appear in the JSON array — NOT sorted by tc_in). This is important because tc_in is the source timecode, not the desired assembly order
11. **Color names**: valid colors are exactly: `Green`, `Blue`, `Cyan`, `Yellow`, `Orange`, `Red`, `Magenta`, `Purple` (case-sensitive)

### How `color` field works in Assembly

The `color` field controls **TWO things** in Premiere Pro:

1. **Clip color on timeline** — each segment gets a colored label on V1/A1 (per-segment application, so the same source file can have different colors in different blocks)
2. **Marker color** — Chapter markers inherit the color of their block

Premiere Pro uses two separate color palettes:
- **Clip labels**: Green=13, Blue=9, Orange=7, Cyan=10, Yellow=15, Red=6, Magenta=11, Purple=8
- **Marker colors**: Green=0, Blue=6, Orange=3, Cyan=7, Yellow=4, Red=1, Magenta=2

You don't need to specify indices — just use the color NAME. The UXP plugin handles the mapping.

### How `is_chapter` field works in Assembly

Set `is_chapter="TRUE"` on the **FIRST segment of each block** (not on every segment).

The UXP plugin creates **two types of markers** from this:

1. **Block-level Chapter marker** (when `is_chapter="TRUE"`):
   - Name = `block_name` (e.g. "Hook", "Government Vision")
   - Duration = total duration of ALL segments in that block
   - Color = block color (from `color` field)
   - Type = Chapter (for YouTube chapter export)

2. **Per-segment point markers** (for ALL segments with comments):
   - Name = `segment_name` or `segment_id`
   - Duration = 0 (point marker)
   - Comment = speaker + transcript + broll_note + notes
   - Color = segment color
   - Type = Chapter

All markers are **Chapter type** (not Comment or Event) for consistent navigation in Premiere Pro timeline and YouTube chapter export.

## project{}

Project settings. Core values taken from `clips[0].media` in transcript.json.

### Core Settings

| Key | Type | Source | Example |
|-----|------|--------|---------|
| `project_name` | string | transcript `project` field | `"YTAI_Edit"` |
| `fps` | float | clips[0].media.fps | `25` |
| `width` | int | clips[0].media.width | `3840` |
| `height` | int | clips[0].media.height | `2160` |
| `sample_rate` | int | clips[0].media.audio_sample_rate | `48000` |
| `video_tracks` | int | always 1 | `1` |
| `audio_tracks` | int | always 4 | `4` |

### Feature Flags

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `create_assembly_sequence` | bool | `true` | Create `{project}_2_Assembly` sequence |
| `create_chapter_markers` | bool | `true` | Create colored Chapter markers at block boundaries |
| `include_unused` | bool | `true` | Include unused segments in the brief |
| `cut_color` | string | `"Red"` | Premiere label color for cut segments |

### Transcript Link

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `_transcription_dir` | string | `""` | Transcription folder name for loading Premiere transcripts (e.g. `"YTAI_Edit_transcription"`) |

## ASSEMBLY Sequence Workflow

The UXP panel (050105_assembly_uxp) creates one sequence from the edit brief:

### `{project}_2_Assembly`

USE=TRUE segments (block != 99) laid out on **V1 only** in **block order** (block 1 first, then block 2, etc.). Within each block — **brief order** (order in JSON array).

- Each segment pre-trimmed to tc_in/tc_out before insertion
- Per-segment color labels (Green, Blue, Orange, etc.) applied before each insert
- Same source file can have different colors in different blocks (e.g. C5403 = Green in Hook, Blue in Government Vision)
- Chapter markers at `is_chapter="TRUE"` positions with block duration and color
- Per-segment Chapter markers with speaker, transcript, and notes
- Purpose: pre-edited assembly sequence ready for refinement by the editor

### Project State After All Stages

```
Project Root
+-- 00_Source/              <- imported clips (from INGEST)
+-- 01_Sequence/            <- (from INGEST)
+-- 02_Transcripts/         <- SRT, transcripts, captions (from INGEST + ASSEMBLY + REVIEW)
+-- {project}_1_Ingest      <- all clips, whole, on V1 (from INGEST)
+-- {project}_2_Assembly    <- used segments on V1, by block order (from ASSEMBLY)
+-- {project}_3_Review      <- unused segments on V1, by source file order (from REVIEW)
```

## File Naming Convention

All YTAI project files use `{project}_` prefix for identification:

| File | Pattern | Example |
|------|---------|---------|
| Transcript | `{project}_transcript.json` | `YTAI_Edit_transcript.json` |
| Edit brief | `{project}_edit_brief.json` | `YTAI_Edit_edit_brief.json` |
| Review HTML | `{project}_edit_brief_review.html` | auto from `generate_review.py` |

The `{project}` value comes from the `project` field in transcript.json (e.g. `"YTAI_Edit"`).
