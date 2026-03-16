# ARCHITECTURE.md — System Architecture

## Pattern

**Sequential Pipeline Architecture** — numbered stages (00–08) that transform raw media into a published YouTube video. Each stage is independently runnable. The UXP plugin bridges Python pipeline outputs into Adobe Premiere Pro.

```
Raw Media
    │
    ▼
[00] Init         → Folder structure creation
    │
    ▼
[01] Prepare      → Audio extraction, DJI sync
    │
    ▼
[02] Transcribe   → Whisper ASR + Pyannote diarization → transcript.json / .srt
    │
    ▼
[03] Speaker ID   → Speaker labeling (via Claude Desktop / Ollama)
    │
    ▼
[04] Video Analy  → Scene detection, emotion, gesture, B-roll detection
    │
    ▼
[05] Editing      → UXP Plugin (Premiere Pro) + supporting Python generators
    │             → Reads: ingest.json, edit_brief.json, transcript
    │             → Writes: markers, captions, sequences into Premiere
    ▼
[06] Thumbnails   → Title gen, thumbnail composition
    │
    ▼
[07] Shorts       → Moment detection, clip export, captions
    │
    ▼
[08] YouTube      → Description, chapters, tags
```

## Entry Points

| Entry Point | Purpose |
|---|---|
| `scripts/run_pipeline.py` | Unified CLI runner for phases 1–2 |
| `scripts/05_editing/0500_uxp/index.js` | UXP plugin root (loaded by Premiere Pro) |
| `scripts/02_transcribe/020101_transcribe/transcribe_project.py` | Transcription runner |
| `scripts/03_speaker_id/00_process_all.py` | Speaker ID pipeline |

## UXP Plugin Architecture

The plugin (`scripts/05_editing/0500_uxp/`) is the most complex component — a single-page Adobe UXP app with module separation:

```
index.js              — Plugin entry point, screen routing, event wiring
index.html            — UXP panel HTML

src/
├── shared/
│   ├── constants.js  — Shared constants (track names, colors, IDs)
│   └── archiver.js   — State archiving utilities
├── ingest/
│   ├── timelineBuilder.js    — Builds Premiere timeline from ingest.json
│   └── transcriptImporter.js — Imports transcript as captions/markers
├── assembly/
│   └── briefParser.js        — Parses edit_brief.json for assembly guidance
├── review/
│   └── reviewBuilder.js      — Builds review sequence with markers
└── screens/
    ├── screenBuilder.js      — Creates screen cue markers/sequences
    └── screenParser.js       — Parses screen cue data
```

**Screen flow:** INGEST → ASSEMBLY → REVIEW → SCREENS (checklist-driven)

## Data Contracts

| File | Producer | Consumer | Contents |
|---|---|---|---|
| `ingest.json` | Python prepare scripts | UXP INGEST module | Clip list, timecodes, audio tracks |
| `transcript.json` | `02_transcribe` | UXP, `03_speaker_id`, `05_editing` | Full transcript with speaker labels, timestamps |
| `edit_brief.json` | `05_editing/0502_assembly` | UXP ASSEMBLY module | Highlight selections, chapter suggestions |
| `.srt` files | `02_transcribe` | Premiere Pro (captions) | Subtitle timecodes |

## Layers

1. **CLI layer** — `run_pipeline.py`, individual script CLIs
2. **Processing layer** — Python scripts per stage (ML inference, file ops)
3. **Data layer** — JSON files as inter-stage contracts, stored in project folder
4. **UI layer** — Adobe UXP plugin as the editing interface

## Project Folder Convention

All pipeline I/O is relative to a **project root** passed as CLI argument:

```
/Volumes/Drive/ProjectName/
├── 01_Media/
│   └── Source/
│       ├── Video/          ← Input video clips
│       ├── Audio/          ← DJI audio files
│       ├── Transcription/  ← transcript.json, .srt outputs
│       ├── Setup/          ← logs, ingest.json
│       └── LUT/            ← Color LUTs
└── (Premiere project file)
```

## Key Design Decisions

- **No shared database** — JSON files as the integration layer between stages
- **Scripts are independent** — each stage can be rerun without affecting others
- **UXP plugin is stateless** — reads JSON files from disk on each operation
- **Venvs are stage-isolated** — transcription deps don't pollute other stages
