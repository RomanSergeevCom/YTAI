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
| `use` | string | `"TRUE"` / `"FALSE"` | Include in final edit? String, not boolean |

### Optional Fields

| Field | Type | Default | Max | Description |
|-------|------|---------|-----|-------------|
| `segment_name` | string | auto | 100 chars | Segment name ("Opening question about business") |
| `speaker` | string | — | — | Who is speaking (from `speaker` field in transcript) |
| `transcript` | string | — | 500 chars | Segment text. Truncate if longer than 500 |
| `track` | string | `"V1"` | — | `"V1"` = main edit track, `"V2"` = cut/disabled track, `"V3"` = graphics |
| `color` | string | by block | — | One of: Cyan, Blue, Green, Yellow, Red, Magenta, Orange, Purple |
| `priority` | int | 1 | 1-9 | 1 = primary take, 2 = alternative take, 9 = cut/noise |
| `is_chapter` | string | `"FALSE"` | — | `"TRUE"` if this starts a YouTube chapter |
| `broll_note` | string | — | 200 chars | B-roll suggestion for the editor |
| `notes` | string | — | 500 chars | Notes for the editor (rationale, cut reason, context) |

### Timecode Conversion (seconds → MM:SS.s)

```
start: 1.46   → tc_in: "00:01.5"
end:   88.76  → tc_out: "01:28.8"
start: 119.42 → tc_in: "01:59.4"
end:   151.88 → tc_out: "02:31.9"
```

Formula: `MM = floor(seconds / 60)`, `SS.s = seconds % 60` (one decimal place)

### Important Rules

1. **tc_in / tc_out** — local time within the clip (segment's `start`/`end` fields in transcript.json)
2. **Segments with use="FALSE"** must also be included — they go to V2 (disabled track) and Unused bin in Premiere
3. **transcript** — truncate to 500 characters, no line breaks
4. **segment_id** numbered sequentially across all clips
5. **source_file** — exact filename with extension
6. **Block 99** — reserved for cuts, noise, expletives, between-takes content. Always color **Red**, priority **9**, track **V2**
7. **track** — USE=TRUE segments go to `"V1"`, USE=FALSE segments go to `"V2"`
8. **priority** — 1 = primary take (on V1), 2 = alternative take (in 03_Alternatives bin), 9 = cut/noise (in 04_Unused bin)
9. **Color for use=FALSE segments:** priority 2 keeps its **block color** (e.g. Green for Hook alt take), priority 9 is always **Red** (block 99)
10. **Block ordering matters**: segments are sorted by `block` number in both FULL and EDIT sequences. Segments within the same block are sorted by `tc_in`. Block 99 (Cut) always appears last
11. **Color names**: valid colors are exactly: `Green`, `Blue`, `Cyan`, `Yellow`, `Orange`, `Red`, `Magenta`, `Purple` (case-sensitive). The UXP panel uses the color name in clip titles (e.g. `[Green] seg_001 Hook`) for visual identification

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
| `video_tracks` | int | always 3 | `3` |
| `audio_tracks` | int | always 4 | `4` |

### Feature Flags

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `create_subclips` | bool | `true` | Create subclips for each segment |
| `create_bins` | bool | `true` | Create organized bin structure (01_Sources, 02_Blocks, 03_Alternatives, 04_Unused) |
| `create_chapter_markers` | bool | `true` | Create markers at YouTube chapter boundaries |
| `include_unused` | bool | `true` | Include unused segments in the brief and Premiere bins |
| `create_full_sequence` | bool | `true` | Create `{project}_FULL` sequence with all clips chronologically |
| `create_edit_sequence` | bool | `true` | Create `{project}_EDIT` sequence with final cut |
| `cut_color` | string | `"Red"` | Premiere label color for disabled/cut segments on V2 |

### Transcript Link

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `_transcription_dir` | string | `""` | Transcription folder name for loading Premiere transcripts (e.g. `"YTAI_Edit_transcription"`) |

## Two-Sequence Workflow

The UXP panel creates **two sequences** from the edit brief:

### Sequence 1: `{project}_FULL`

ALL segments (USE + CUT) laid out on V1 in **block order** (block 1 first, then block 2, etc., block 99 last).
- Each segment trimmed to its tc_in/tc_out
- USE segments: named `[Color] seg_001 Hook`, enabled
- CUT segments: named `[CUT] seg_007 Cut`, disabled
- Block-level chapter markers + per-segment comment markers
- Purpose: reference timeline for reviewing all footage in narrative order

### Sequence 2: `{project}_EDIT`

The final edited sequence with two video tracks:

| Track | Content | Color | Audio |
|-------|---------|-------|-------|
| **V1** (main) | USE=TRUE segments, assembled in block order, trimmed to tc_in/tc_out | Block semantic color (Green, Blue, Orange, etc.) | Active |
| **V2** (disabled) | USE=FALSE and priority>1 segments, placed after a gap | `cut_color` (default: Red) | Muted |

- Chapter markers at block boundaries (for segments with `is_chapter="TRUE"`)
- Block-level markers with speaker/transcript info in comments
- Purpose: final edited sequence ready for refinement by the editor

### Bin Structure

```
Project Root
├── 01_Sources        ← All imported source clips
├── 02_Blocks
│   ├── Block_01_Hook
│   ├── Block_02_Government_Vision
│   └── Block_03_Client_Story
├── 03_Alternatives   ← priority >= 2 segments
└── 04_Unused         ← use="FALSE" segments
```

## File Naming Convention

All YTAI project files use `{project}_` prefix for identification:

| File | Pattern | Example |
|------|---------|---------|
| Transcript | `{project}_transcript.json` | `YTAI_Edit_transcript.json` |
| Edit brief | `{project}_edit_brief.json` | `YTAI_Edit_edit_brief.json` |
| Review HTML | `{project}_edit_brief_review.html` | auto from `generate_review.py` |
| Reviewed brief | `{project}_edit_brief_reviewed.json` | saved by UXP panel |

The `{project}` value comes from the `project` field in transcript.json (e.g. `"YTAI_Edit"`).
