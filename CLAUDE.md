# YTAI — YouTube Production Pipeline

## Assembly Brief Generation

When the user asks to create or update an Assembly brief (keywords: "Assembly brief", "создай brief", "обнови brief", "pre_edit_brief"):

### Step 1: Load knowledge base

Read these files IN ORDER before generating anything:

1. `scripts/05_editing/0501_brief/INSTRUCTIONS.md` — full workflow, response format, analysis algorithm
2. `scripts/05_editing/0501_brief/project_knowledge/editing_rules.md` — video structure, what to cut, color schema, pacing rules
3. `scripts/05_editing/0501_brief/project_knowledge/output_format.md` — JSON schema (segments, screens, project, changelog)
4. **Channel profile** from `YTs/{CHANNEL}.md`:
   - User provides channel code (e.g. `YTCR`) or it's extracted from project name
   - `YTCR` → read `YTs/YTCR.md`, `YTCG` → read `YTs/YTCG.md`

### Step 2: Auto-resolve paths from project folder

User provides only **channel code** + **project path**. Find everything else automatically:

```
Given: Channel=YTCR, Project=/Volumes/RYA T7 Black/YTCR01_Arty_Dzis

Extract project code:  YTCR01  (regex: ^(YT[A-Z]{2,4}\d+)_ from folder name)

Auto-resolve:
  Transcript:  {project}/01_Media/Source/Setup/YTCR01_Claude4_assembly.json
  Output dir:  {project}/01_Media/Source/Setup/Assembly/
  Next version: scan Assembly/ for existing files → determine v{N}
  Output JSON: Assembly/YTCR01_Assembly_v{N}_in.json
  Output HTML: Assembly/YTCR01_review_v{N}.html
```

### Step 3: Generate outputs

Produce **3 things**:

1. **JSON brief** → write directly to `Setup/Assembly/{CODE}_Assembly_v{N}_in.json`
2. **HTML review** → write directly to `Setup/Assembly/{CODE}_review_v{N}.html`
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

## Project Structure (v3.0)

```
{project}/
├── 01_Media/
│   ├── {project}.prproj
│   └── Source/
│       ├── Video/{scene}/*.MP4
│       ├── Audio/{scene}/*_TX*.wav
│       ├── Transcription/
│       │   ├── {CODE}_transcript.json
│       │   ├── per_clip/
│       │   └── {scene}/
│       └── Setup/
│           ├── {CODE}_ingest.json
│           ├── {CODE}_Claude4_assembly.json
│           └── Assembly/
│               ├── {CODE}_Assembly_v1_in.json
│               ├── {CODE}_Assembly_v2_out.json
│               ├── {CODE}_review_v1.html
│               └── ...
└── 99_Pipeline/DJI_Audio/
```

## Project Naming

- All projects: `YT{XX}{NN}_{Guest_Name}` (e.g. `YTCR01_Arty_Dzis`, `YTCG37_Hadi_Dawani`)
- Channel code: `YT` + 2-4 letters (YTCR, YTCG, YTRF...)
- Project code: channel + number (YTCR01, YTCG37...)
- Regex: `^(YT[A-Z]{2,4}\d+)_`
