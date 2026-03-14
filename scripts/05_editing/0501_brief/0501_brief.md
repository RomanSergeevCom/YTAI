# Editing Claude KB — Quick Setup

## Create a Project

1. Claude Desktop → **Projects** (left panel) → **Create Project**
2. Name: **`YTAI Editing — YTCG`** (or another channel: YTCR, YTRM...)

## Custom Instructions

Copy the contents of **`INSTRUCTIONS.md`** → paste into the Custom Instructions field of the project.

## Project Knowledge

Upload 5 files from the `project_knowledge/` folder + channel profile:

| # | File | What it is |
|---|------|------------|
| 1 | `editing_rules.md` | Editing rules + color schema |
| 2 | `output_format.md` | JSON schema for `{project}_edit_brief.json` |
| 3 | `example_input.json` | Example input (transcript) |
| 4 | `example_output.json` | Example output (edit brief) |
| 5 | `~/YTAI/YTs/YTCG.md` | Channel profile |

> For another channel — replace `YTCG.md` with the appropriate `YTXX.md` from `~/YTAI/YTs/`.

## Usage

### New Brief

1. Open the project → start a new chat
2. Attach `{project}_transcript.json` (from stage 02_transcribe)
3. Write:

```
Make an edit brief. Target duration: 12 minutes.
```

4. Claude will return:
   - **JSON artifact** — named `{project}_edit_brief.json` (e.g. `YTCG37_Hadi_Dawani_edit_brief.json`)
   - **Overview** (block table, chapters, skipped) — for quick review

5. Chat name = project name (e.g. `YTCG37_Hadi_Dawani`)

### Browser Review

```bash
python ~/YTAI/scripts/05_editing/generate_review.py --brief YTCG37_Hadi_Dawani_edit_brief.json
open YTCG37_Hadi_Dawani_edit_brief_review.html
```

### Edits

In the same chat:
```
Remove block 3.
Change the hook to seg_005.
Make it shorter — target 10 minutes.
```
Claude will return the updated JSON artifact → re-save → regenerate HTML.

### Load into Premiere

Premiere → Window → Extensions → **YTAI Assembly** → load `{project}_edit_brief.json`

The **0500_uxp** plugin works in four stages:

1. **INGEST** (from ingest.json): imports clips + DJI WAVs → `00_Source/` bin + `{project}_1_Ingest` sequence
2. **ASSEMBLY** (from edit_brief.json): reads `00_Source/` → builds `{project}_2_Assembly` sequence (V1: trimmed clips + A2: DJI audio + colored Chapter markers)
3. **REVIEW** (from edit_brief.json): builds `{project}_3_Review` sequence (complement of Assembly, V1 + A2)
4. **SCREEN CUES** (from edit_brief.json): builds `{project}_4_ScreenCues` sequence (V1: Assembly copy + V2: PNG overlays + A2: DJI audio)

## Parameters

| Parameter | Example | Default |
|-----------|---------|---------|
| Duration | "12 minutes" | ~60-70% of material |
| Style | "interview", "documentary", "vlog" | auto from context |
| Instructions | "start with the moment about X" | — |
