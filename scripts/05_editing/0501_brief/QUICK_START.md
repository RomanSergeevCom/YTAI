# Assembly Brief — Quick Start

## Claude Code — Copy-Paste Templates

### New brief (v1)

```
Create Assembly brief:
- Channel: ___
- Project: ___

Resolve from project structure:
- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)
- Channel profile: ~/YTAI/YTs/{CHANNEL}.md
- Transcript: {project}/01_Media/Source/Setup/{CODE}_Claude4_assembly.json
- Output JSON: {project}/01_Media/Source/Setup/Assembly/{CODE}_Assembly_v1_in.json
- Output HTML: {project}/01_Media/Source/Setup/Assembly/{CODE}_review_v1.html
```

**Example:**
```
Create Assembly brief:
- Channel: YTCR
- Project: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis

Resolve from project structure:
- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)
- Channel profile: ~/YTAI/YTs/YTCR.md
- Transcript: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Setup/YTCR01_Claude4_assembly.json
- Output JSON: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Setup/Assembly/YTCR01_Assembly_v1_in.json
- Output HTML: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Setup/Assembly/YTCR01_review_v1.html
```

### Update brief (after Premiere edit)

```
Update Assembly brief from markers:
- Markers: ___

Resolve from project structure:
- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)
- Previous brief: auto-detect latest _in.json in Assembly/
- Output JSON: Assembly/{CODE}_Assembly_v{N+1}_in.json
- Output HTML: Assembly/{CODE}_review_v{N+1}.html

[+ extra instructions]
```

**Example:**
```
Update Assembly brief from markers:
- Markers: /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Setup/Assembly/YTCR01_Assembly_v2_out.json

Remove block 5, make block 3 shorter.

Resolve from project structure:
- Knowledge base: ~/YTAI/scripts/05_editing/0501_brief/ (INSTRUCTIONS.md, editing_rules.md, output_format.md)
- Previous brief: auto-detect latest _in.json in Assembly/
- Output JSON: Assembly/YTCR01_Assembly_v3_in.json
- Output HTML: Assembly/YTCR01_review_v3.html
```

---

## Full Pipeline

```
transcript.json ──→ Claude Code ──→ v1_in.json + HTML
                                         ↓
                                   UXP: Build Assembly + Review
                                         ↓
                                   Edit in Premiere (markers)
                                         ↓
                                   Export Markers → v2_out.json
                                         ↓
                                   Claude Code ──→ v3_in.json + HTML (with editor notes highlighted)
                                         ↓
                                   UXP: Rebuild Assembly (old → _v1, new → _2_Assembly)
```

---

### Step 1: Transcribe

```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate

# Single project:
python ~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py \
  --project "/path/to/PROJECT" -y

# Multi-scene (nested):
python ~/YTAI/scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py \
  --project "/path/to/PROJECT" --language ru --fallback en -y
```

Output: `Transcription/{project}_transcript.json`

### Step 2: Create Brief v1 (Claude Code)

Open new Claude Code chat in `~/YTAI` directory. Use the template from the top of this file.

Claude reads instructions from `0501_brief/` + channel profile from `YTs/` and writes:
1. `{CODE}_Assembly_v1_in.json` → directly to `Setup/Assembly/`
2. `{CODE}_review_v1.html` → directly to `Setup/Assembly/` (open in browser)

**Iterate in chat:** review HTML, ask for changes, Claude updates both.

### Step 3: Build in Premiere (UXP Plugin)

1. **Select Project Folder** → auto-detects ingest + brief
2. **Load Edit Brief** → pick from Downloads → auto-saves to `Setup/Assembly/` with version
3. **Build Assembly** → builds `_2_Assembly_v{N}` + auto-builds `_3_Review_v{N}`
   - Auto-generates transcript + captions SRTs (named to match timeline, e.g. `YTCR01_2_Assembly_v3_captions.srt`)
   - Auto-imports SRTs into `01_Transcripts/{CODE}_2_Assembly_v{N}/` and `01_Transcripts/{CODE}_3_Review_v{N}/`

### Step 4: Edit in Premiere

- Watch Assembly timeline
- Add comments to markers (your editing notes)
- Rearrange, cut, adjust

### Step 5: Export Markers → v2

**Button: Export Markers** (or from Terminal):
```bash
python3 ~/YTAI/scripts/05_editing/0506_marker_export/export_markers_from_prproj.py \
  --project "/path/to/PROJECT"
```

Output: `Setup/Assembly/{CODE}_Assembly_v{N}_out.json` + `~/Downloads/`

Contains: marker names, comments (with your notes), positions, durations — ALL data.

### Step 6: Update Brief v2 (Claude Code)

Use the "Update brief" template from the top of this file. Add any extra instructions.

Claude reads your marker comments, applies changes, returns:
1. Updated `_v{N}_in.json`
2. Updated HTML with:
   - 📝 Editor notes highlighted in yellow
   - **CHANGED v2** badges on modified segments
   - ~~Strikethrough~~ on removed segments
   - Changes summary at top

### Step 7: Rebuild in Premiere

**Load Edit Brief** → pick new `_in.json` from Downloads.
Old `_2_Assembly` renamed to `_Assembly_v1`. New one built fresh.

---

## File Structure

```
Setup/
  YTCR01_ingest.json                      ← global ingest
  Assembly/                               ← all brief versions (in/out)
    YTCR01_Assembly_v1_in.json          ← first brief from Claude
    YTCR01_Assembly_v2_out.json         ← exported markers after editing
    YTCR01_Assembly_v3_in.json          ← updated brief with editor notes
    YTCR01_Assembly_v4_out.json         ← next export...
  Ingest/                                 ← per-scene audio sync
Transcription/
  YTCR01_Arty_Dzis_transcript.json        ← merged transcript (325 clips)
  YTCR01_Arty_Dzis_transcript.xlsx        ← Excel (3 tabs)
  transcripts/                            ← full-text SRTs per timeline
    YTCR01_2_Assembly_v3_transcript.srt
    YTCR01_3_Review_v3_transcript.srt
  captions/                               ← word-grouped SRTs per timeline
    YTCR01_2_Assembly_v3_captions.srt
    YTCR01_3_Review_v3_captions.srt
  scenes/                                 ← per-scene transcripts
  per_clip/                               ← per-clip data
```

## Knowledge Files (auto-loaded by CLAUDE.md)

| File | Purpose |
|------|---------|
| `~/YTAI/CLAUDE.md` | Auto-loaded in every Claude Code chat — triggers instruction loading |
| `INSTRUCTIONS.md` | Full workflow, analysis algorithm, response format |
| `editing_rules.md` | Video structure, what to cut, color schema, pacing |
| `output_format.md` | JSON schema (segments, screens, project, changelog) |
| `example_input.json` | Example transcript input |
| `example_output.json` | Example brief output |
| `~/YTAI/YTs/{CHANNEL}.md` | Channel profile (auto-detected from project name) |
