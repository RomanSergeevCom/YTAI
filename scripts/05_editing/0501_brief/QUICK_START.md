# Assembly Brief — Quick Start

## Full Pipeline

```
transcript.json ──→ Claude Desktop ──→ v1_in.json + HTML
                                            ↓
                                      UXP: Build Assembly + Review
                                            ↓
                                      Edit in Premiere (markers)
                                            ↓
                                      Export Markers → v2_out.json
                                            ↓
                                      Claude Desktop ──→ v3_in.json + HTML (with editor notes highlighted)
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

### Step 2: Create Brief v1 (Claude Desktop)

Send `{project}_transcript.json` to Claude Desktop.

Claude returns **2 artifacts**:
1. `{CODE}_2_Assembly_v1_in.json` — brief JSON (save to `Setup/Assembly/`)
2. `{CODE}_review_v1.html` — visual review (open in browser)

**Iterate in chat:** review HTML, ask for changes, Claude updates both.

### Step 3: Build in Premiere (UXP Plugin)

1. **Select Project Folder** → auto-detects ingest + brief
2. **Load Edit Brief** → pick from Downloads → auto-saves to `Setup/Assembly/` with version
3. **Build Assembly** → builds `_2_Assembly` + auto-builds `_3_Review`
4. **Import SRTs** → imports subtitles to `02_Transcripts` bin

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

Output: `Setup/Assembly/{CODE}_2_Assembly_v{N}_out.json` + `~/Downloads/`

Contains: marker names, comments (with your notes), positions, durations — ALL data.

### Step 6: Update Brief v2 (Claude Desktop)

Send `_out.json` to Claude Desktop. Tell Claude what to change.

Claude reads your marker comments, applies changes, returns:
1. Updated `_v{N}_in.json`
2. Updated HTML with:
   - 📝 Editor notes highlighted in yellow
   - **CHANGED v2** badges on modified segments
   - ~~Strikethrough~~ on removed segments
   - Changes summary at top

### Step 7: Rebuild in Premiere

**Load Edit Brief** → pick new `_in.json` from Downloads.
Old `_2_Assembly` renamed to `_2_Assembly_v1`. New one built fresh.

---

## File Structure

```
Setup/
  YTCR01_ingest.json                      ← global ingest
  Assembly/                               ← all brief versions (in/out)
    YTCR01_2_Assembly_v1_in.json          ← first brief from Claude
    YTCR01_2_Assembly_v2_out.json         ← exported markers after editing
    YTCR01_2_Assembly_v3_in.json          ← updated brief with editor notes
    YTCR01_2_Assembly_v4_out.json         ← next export...
  Ingest/                                 ← per-scene audio sync
Transcription/
  YTCR01_Arty_Dzis_transcript.json        ← merged transcript (325 clips)
  YTCR01_Arty_Dzis_transcript.xlsx        ← Excel (3 tabs)
  scenes/                                 ← per-scene transcripts
  per_clip/                               ← per-clip data
```

## Claude Desktop Project Knowledge Files

| File | Where to Load |
|------|---------------|
| `INSTRUCTIONS.md` | Custom Instructions |
| `editing_rules.md` | Project Knowledge |
| `output_format.md` | Project Knowledge |
| `example_input.json` | Project Knowledge |
| `example_output.json` | Project Knowledge |
| `~/YTAI/YTs/YTXX.md` | Project Knowledge (channel profile) |
