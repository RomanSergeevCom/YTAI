# Quick Task 260317-fj4: Refactor Folder Structure - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Task Boundary

Refactor the YTAI project output folder structure:
1. Rename `edit_brief` → `pre-edit_brief` everywhere
2. Short naming: `YTCG37_` prefix instead of `YTCG37_Setup_UAE_Company_Remotely_`
3. Move all SRT captions → `Transcription/captions/`
4. Move all SRT transcripts → `Transcription/transcripts/`
5. Move `dji_sync_check.xml/.prproj` → `99_Pipeline/DJI_Audio/`
6. Setup/ = only main docs: ingest.json, pre-edit_brief.json, transcript.json, transcript.xlsx, screen_cues/, pre-edit_versions/, logs/
7. Update all pipeline scripts, UXP plugin, specs, templates
8. Reorganize YTCG37 project files on disk

</domain>

<decisions>
## Implementation Decisions

### Folder Structure
- **Setup/** contains only main working documents:
  - `{CODE}_ingest.json`
  - `{CODE}_pre-edit_brief.json`
  - `{CODE}_transcript.json`
  - `{CODE}_transcript.xlsx`
  - `screen_cues/` (PNG overlays for Premiere V2)
  - `pre-edit_versions/` (brief version history)
  - `logs/`
- **Transcription/captions/** — all `*_captions.srt` files
- **Transcription/transcripts/** — all `*_transcript.srt` files
- **99_Pipeline/DJI_Audio/** — dji_sync_check files move here alongside raw DJI WAVs

### File Naming
- Short prefix: `{YTXX##}_` (e.g. `YTCG37_`) — NOT full project name
- Applies to: ingest.json, pre-edit_brief.json, transcript.json, .xlsx, all SRTs, dji_sync_check
- `{CODE}` is derived from project folder name: regex `^(YT[A-Z]{2,4}\d+)_`

### Rename: edit_brief → pre-edit_brief
- All references in scripts, UXP plugin, specs
- File: `{CODE}_pre-edit_brief.json`
- versions/ → `pre-edit_versions/`

### Scope
- Update pipeline scripts (run_pipeline.py, extract_audio, sync_dji, transcribe, generate_uxp_ingest)
- Update UXP plugin (0500_uxp: index.js, constants.js, briefParser.js, etc.)
- Update specs (01_prepare_spec.md, 0500_uxp_spec.md, 0501_brief_spec.md, etc.)
- Reorganize actual YTCG37 project files on external drive

</decisions>

<specifics>
## Specific Details

### Target project for file reorganization
- Path: `/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely`
- Code: `YTCG37`
- Flat structure (no scenes)

### New structure for YTCG37
```
Source/
├── Setup/
│   ├── YTCG37_ingest.json
│   ├── YTCG37_pre-edit_brief.json
│   ├── YTCG37_transcript.json
│   ├── YTCG37_transcript.xlsx
│   ├── screen_cues/
│   ├── pre-edit_versions/
│   └── logs/
├── Transcription/
│   ├── captions/
│   │   ├── YTCG37_1_Ingest_captions.srt
│   │   ├── YTCG37_2_Assembly_captions.srt
│   │   └── YTCG37_3_Review_captions.srt
│   ├── transcripts/
│   │   ├── YTCG37_1_Ingest_transcript.srt
│   │   ├── YTCG37_2_Assembly_transcript.srt
│   │   └── YTCG37_3_Review_transcript.srt
│   ├── per_clip/
│   ├── YTCG37_FULL_AUDIO.wav
│   └── ...(internal)...
├── Audio/ Video/ LUT/

99_Pipeline/DJI_Audio/
├── *.wav (raw DJI)
├── YTCG37_dji_sync_check.xml
└── YTCG37_dji_sync_check.prproj
```

### Scripts that need updating
- `scripts/run_pipeline.py` — output paths, file naming
- `scripts/01_prepare/0102_extract_audio/0102_extract_audio.py` — output paths
- `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` — sync check output path
- `scripts/01_prepare/0105_generate_uxp_ingest.py` — ingest.json path
- `scripts/02_transcribe/020101_transcribe/` — transcript output paths, SRT paths
- `scripts/05_editing/0500_uxp/index.js` — auto-detect paths, brief filename
- `scripts/05_editing/0500_uxp/src/assembly/briefParser.js` — brief filename
- `scripts/05_editing/0500_uxp/src/screens/screenBuilder.js` — screen_cues path
- `scripts/05_editing/0500_uxp/src/shared/constants.js` — filenames
- `scripts/05_editing/0502_assembly/generate_assembly_captions.py` — output paths
- `scripts/05_editing/0503_review/generate_review.py` — brief name
- Specs: 01_prepare_spec.md, 0500_uxp_spec.md, 0501_brief_spec.md, etc.

</specifics>

<canonical_refs>
## Canonical References

- `scripts/01_prepare/01_prepare_spec.md` — current output structure spec
- `scripts/05_editing/0500_uxp/0500_uxp_spec.md` — UXP plugin spec
- `scripts/05_editing/0501_brief/0501_brief_spec.md` — edit brief spec
- `scripts/05_editing/0501_brief/INSTRUCTIONS.md` — Claude Desktop instructions

</canonical_refs>
