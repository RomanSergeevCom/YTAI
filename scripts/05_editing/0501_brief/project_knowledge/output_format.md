# Output JSON Format: {CODE}_pre_edit_brief.json

JSON contains three sections: `segments` (array), `screens` (array, optional), and `project` (settings).

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
| `transcript` | string | — | 500 chars | Brief summary or key phrase of the segment (NOT the full text). Full text is pulled from transcript.json at display time via source_file + tc_in/tc_out lookup. Can be empty — used as editor note. |
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
3. **transcript** — brief summary or key phrase (max 500 chars). Full text is sourced from transcript.json at display time. The brief is the source of truth for *what to do*; transcript.json is the source of truth for *what was said*.
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

## screens[] (optional)

Production Cues for the editor/motion designer. Each screen describes a visual overlay type and its text content. Screens are placed on V2 of the Assembly sequence as orange clip markers.

**If no visual overlays are needed, omit the `screens` array entirely.**

### Fields

| Field | Type | Max | Required | Description |
|-------|------|-----|----------|-------------|
| `screen_id` | string | — | yes | `scr_001`, `scr_002`... sequential numbering |
| `type` | string | — | yes | Screen type (see table below) |
| `segment_id` | string | — | yes | Reference to segment (`seg_003`) where this cue appears |
| `tc_in` | string | — | no | `MM:SS.s` — time within the clip (defaults to segment's tc_in) |
| `title` | string | 100 | yes | Main text (headline, name, etc.) |
| `subtitle` | string | 100 | no | Secondary text (job title, subheading) |
| `body` | string | 500 | no | List items, data, descriptions. Use `\n` for line breaks |

### Screen Types

| type | Description | Required fields |
|------|-------------|-----------------|
| `full_overlay` | Full-screen gradient overlay (градиент на весь экран — оглавление) | title |
| `half_overlay` | 1/2 screen gradient left (градиент на левую половину) | title |
| `three_fifths_overlay` | 3/5 screen gradient left (градиент на 3/5 экрана) | title |
| `chapter_bar` | Bottom center bar (бар снизу по центру — название главы) | title |
| `lower_third` | Centered rounded bar (закруглённый бар снизу — имя спикера) | title |

**IMPORTANT: Use ONLY the 5 types listed above.** Do NOT invent types like `chapter_title`, `info_graphic`, `title_card`, etc. — they will be rejected by the UXP plugin.

### Rules

1. **screen_id** — sequential across all screens: `scr_001`, `scr_002`, etc.
2. **segment_id** — must reference a USE=TRUE segment. Screens on use=FALSE segments are skipped
3. **tc_in** — if omitted, defaults to the segment's tc_in (screen appears at segment start)
4. **type names** — case-insensitive, will be normalized to lowercase
5. **body** — use `\n` for line breaks in lists and multi-line content
6. Screens are placed on **V2** (separate from V1 content) with **Orange** color labels
7. Screen cue markers are **Comment type** (not Chapter) to avoid confusing navigation

### Example

```json
"screens": [
  {
    "screen_id": "scr_001",
    "type": "full_overlay",
    "segment_id": "seg_001",
    "title": "Digital Transformation",
    "subtitle": "How AI Changes Business"
  },
  {
    "screen_id": "scr_002",
    "type": "lower_third",
    "segment_id": "seg_003",
    "tc_in": "00:15.2",
    "title": "Ivan Petrov",
    "subtitle": "CEO, TechCorp"
  },
  {
    "screen_id": "scr_003",
    "type": "chapter_bar",
    "segment_id": "seg_005",
    "title": "KEY NUMBERS"
  },
  {
    "screen_id": "scr_004",
    "type": "half_overlay",
    "segment_id": "seg_006",
    "title": "Revenue Growth",
    "subtitle": "+40% year over year"
  }
]
```

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

## changelog[] (from v2 onwards)

Version history of editing decisions. Added when the brief is updated (v2, v3, etc.). Each entry documents what changed, why, and who requested it.

**Not present in v1** — only appears after the first round of edits.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Version tag: `"v2"`, `"v3"`, etc. |
| `date` | string | ISO date: `"2026-03-20"` |
| `source` | string | What triggered this version: `"editor_markers"`, `"chat_request"`, `"review_notes"` |
| `summary` | string | One-line summary of all changes in this version |
| `changes` | array | List of individual changes |

### Change entry fields

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"cut"`, `"add"`, `"move"`, `"trim"`, `"reorder"`, `"merge"`, `"split"`, `"recolor"` |
| `segment_id` | string | Which segment was changed (e.g. `"seg_035"`) |
| `description` | string | Human-readable description of the change |
| `reason` | string | Why — from editor notes, chat, or auto-detected |
| `was` | string | Previous value (for trim/move: old tc, old block) |
| `now` | string | New value |

### Example

```json
"changelog": [
  {
    "version": "v2",
    "date": "2026-03-20",
    "source": "editor_markers",
    "summary": "Removed Hook flash 1h per editor note, trimmed ROI segment, kept block 2a per editor request",
    "changes": [
      {
        "type": "cut",
        "segment_id": "seg_017",
        "description": "Moved 1h (EOI day) to Block 99",
        "reason": "Editor note: 'давай этот блок уберем'"
      },
      {
        "type": "trim",
        "segment_id": "seg_035",
        "description": "Trimmed tc_out from 17:54.5 to 17:27.9",
        "reason": "Last 16s 'ROI punchline' already used in Hook",
        "was": "17:54.5",
        "now": "17:27.9"
      },
      {
        "type": "add",
        "segment_id": "seg_107",
        "description": "Moved from SKIP to Block 11 (Market Intelligence)",
        "reason": "Editor note: 'нужно оставить несколько моментов'"
      }
    ]
  }
]
```

### How changelog renders in HTML

Each version gets a collapsible section at the top of the HTML review:

```html
<details open>
  <summary>📋 v2 — 3 changes (2026-03-20, from editor markers)</summary>
  <table>
    <tr><td>🔴 CUT</td><td>seg_017</td><td>1h · EOI day → Block 99</td><td>Editor: давай этот блок уберем</td></tr>
    <tr><td>✂️ TRIM</td><td>seg_035</td><td>tc_out: 17:54.5 → 17:27.9</td><td>ROI punchline duplicate</td></tr>
    <tr><td>🟢 ADD</td><td>seg_107</td><td>SKIP → Block 11</td><td>Editor: нужно оставить моменты</td></tr>
  </table>
</details>
```

### How changelog affects segment notes

When a segment is changed, its `notes` field gets a version tag prepended:

```
[v2 editor] давай этот блок уберем | Original notes: HOOK FLASH 8 — 34 sec...
```

This way even without the changelog section, each segment shows its edit history inline.

## ASSEMBLY Sequence Workflow

The UXP panel (0500_uxp) creates one sequence from the edit brief:

### `{project}_2_Assembly`

USE=TRUE segments (block != 99) laid out on **V1** in **block order** (block 1 first, then block 2, etc.). Within each block — **brief order** (order in JSON array).

- V1: Each segment pre-trimmed to tc_in/tc_out before insertion, per-segment color labels
- A2/A3: DJI microphone audio (trimmed with same in/out points as V1, if DJI WAVs exist)
- V2: Screen cue clips (Orange) at positions matching screens[] entries (if present)
- Chapter markers at `is_chapter="TRUE"` positions with block duration and color
- Per-segment Chapter markers with speaker, transcript, and notes
- Screen cue Comment markers (Orange) with type + text content (if screens[] present)
- Purpose: pre-edited assembly sequence ready for refinement by the editor

### Project State After All Stages

```
Project Root
+-- 00_Source/              <- imported clips + DJI WAVs (from INGEST)
|   +-- {CODE}_{scene}/    <- scene sub-bins (e.g. YTCR01_al_qudra_lake)
+-- 01_ScreenCues/          <- PNG overlay images (from SCREEN CUES)
+-- 02_Transcripts/         <- SRT, transcripts, captions (from INGEST + ASSEMBLY + REVIEW + SCREEN CUES)
+-- {project}_1_Ingest      <- V1: all clips whole; A2: DJI TX whole (from INGEST)
+-- {project}_2_Assembly    <- V1: used segments; A2: DJI trimmed; V2: screen cues (from ASSEMBLY)
+-- {project}_3_Review      <- V1: unused segments; A2: DJI trimmed (from REVIEW)
+-- {project}_4_ScreenCues  <- V1: Assembly copy; A2: DJI trimmed; V2: PNGs (from SCREEN CUES)
```

## File Naming Convention

All YTAI project files use `{project}_` prefix for identification:

| File | Pattern | Example |
|------|---------|---------|
| Transcript | `{project}_transcript.json` | `YTAI_Edit_transcript.json` |
| Edit brief | `{CODE}_pre_edit_brief.json` | `YTCG37_pre_edit_brief.json` |
| Assembly SRT | `{project}_2_Assembly_captions.srt` | auto from `generate_assembly_captions.py` |
| Review SRT | `{project}_3_Review_captions.srt` | auto from `generate_assembly_captions.py --review` |
| Screen Cues SRT | `{CODE}_4_PreEdit_captions.srt` | auto from `generate_screen_cues.py` |
| Review HTML | `{CODE}_pre_edit_brief_review.html` | auto from `generate_review.py` |

`{CODE}` = short project code extracted from project name (e.g. `YTCG37` from `YTCG37_Hadi_Dawani`).
