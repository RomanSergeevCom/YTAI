# Quick Task 260317-clh: Run full prepare pipeline for YTCG37 - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Task Boundary

Run the complete YTAI pipeline for project `/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely`:
1. Prepare (init folders, extract audio, DJI sync)
2. Transcribe (Whisper + Pyannote diarization)
3. Generate UXP ingest brief for pre-edit

Project has flat structure (no scene folders). Files in root:
- RYA-FX3-0099.MP4, RYA-FX3-0099M01.XML
- RYA-FX3-0100.MP4, RYA-FX3-0100M01.XML
- TX02_MIC037_20260306_102304_orig.wav
- TX02_MIC038_20260306_105305_orig.wav

</domain>

<decisions>
## Implementation Decisions

### Pipeline Scope
- Run full pipeline: prepare → transcribe → generate UXP ingest brief
- All prepare stages: init folders, extract audio, DJI sync

### Speaker Configuration
- 2 speakers for Pyannote diarization
- Language: English

### Claude's Discretion
- DJI TX mapping (TX02 has 2 WAV files — MIC037 and MIC038)
- Timezone offset for DJI sync (auto-detect)

</decisions>

<specifics>
## Specific Ideas

- Project path: `/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely`
- Flat structure — no scene folders
- Use `run_pipeline.py --all --speakers 2` for end-to-end execution

</specifics>
