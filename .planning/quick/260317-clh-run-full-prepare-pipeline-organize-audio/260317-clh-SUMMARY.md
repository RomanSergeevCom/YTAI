---
quick_task: 260317-clh
subsystem: pipeline
tags: [pipeline, organize, audio-sync, transcription, uxp, YTCG37]
dependency_graph:
  requires: [run_pipeline.py, 0103_sync_dji_audio.py, transcribe_project.py, ingest_json.py]
  provides: [YTCG37 prepared project with ingest.json]
  affects: [Premiere Pro UXP ingest panel]
tech_stack:
  patterns: [flat-project pipeline, cross-correlation DJI sync, Whisper+Pyannote transcription]
key_files:
  created:
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_ingest.json
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.json
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.srt
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.xlsx
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Audio/RYA-FX3-0099_TX02.wav
    - /Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Audio/RYA-FX3-0100_TX02.wav
  modified: []
decisions:
  - "UXP ingest.json for flat projects is generated directly by transcribe pipeline (ingest_json.py), not 0105_generate_uxp_ingest.py (which is for nested/multi-scene projects)"
metrics:
  duration: 22 min
  completed_date: "2026-03-17"
  tasks_completed: 2
  files_created: 6
---

# Quick Task 260317-clh: Run Full Prepare Pipeline on YTCG37

**One-liner:** Full flat-project pipeline run on YTCG37 — v3.0 folder structure, TX02 DJI audio synced (confidence=16.9, max_error=0.004s), 37:02 Whisper+Pyannote 2-speaker transcription, UXP ingest.json ready for Premiere Pro.

## What Was Done

Ran the full YTAI prepare pipeline on `/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely`, a flat project with 2 FX3 clips and 2 DJI TX WAVs.

### Pipeline Stages Completed

1. **Init v3.0 folder structure** — Created 18 directories (01_Media, 02_Exports, etc.) and moved files:
   - 2 MP4 video clips → `01_Media/Source/Video/`
   - 2 DJI TX WAVs → `99_Pipeline/DJI_Audio/`
   - 2 XML sidecars → `Transcription/per_clip/{clip}/`

2. **Extract audio** — Extracted per-clip WAVs (406.9 MB total) + concatenated FULL_AUDIO (37:02, 406.9 MB)

3. **DJI sync** — Auto-detected timezone UTC+4, cross-correlation on RYA-FX3-0100 (reference clip):
   - Metadata offset: 207.0s → Refined: 214.5s (correction: +7.500s)
   - Confidence: 16.9 (threshold=3.0) — excellent match
   - Spanning TX: RYA-FX3-0100 spans TX02_MIC037 + TX02_MIC038 (auto-split snapped)
   - Phase 3 verification: max_error=0.004s (<1 frame) — SYNC OK
   - Output: `RYA-FX3-0099_TX02.wav` (2.4 MB), `RYA-FX3-0100_TX02.wav` (302.8 MB)

4. **Transcription** — Whisper large model + Pyannote 2-speaker diarization on 37:02 audio:
   - Diarization: 1m 11s (plan 1m 22s)
   - Whisper: ~19 min
   - Output: per-clip JSONs, SRTs, combined transcript, XLSX, UXP ingest.json

### Output Files

| File | Location |
|------|----------|
| ingest.json (UXP) | `01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_ingest.json` |
| transcript.json | `01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.json` |
| transcript.srt | `01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.srt` |
| transcript.xlsx | `01_Media/Source/YTCG37_Setup_UAE_Company_Remotely_transcript.xlsx` |
| RYA-FX3-0099_TX02.wav | `01_Media/Source/Audio/` (2.4 MB, 0:17) |
| RYA-FX3-0100_TX02.wav | `01_Media/Source/Audio/` (302.8 MB, 36:44) |

### ingest.json Clips

- `RYA-FX3-0099`: 17.76s, TX02 synced, premiere_transcript linked
- `RYA-FX3-0100`: 2204.64s (36:44), TX02 synced (spanning 2 DJI files), premiere_transcript linked

## Deviations from Plan

### Auto-resolved: 0105_generate_uxp_ingest.py not applicable

- **Found during:** Task 2
- **Issue:** `0105_generate_uxp_ingest.py` expects per-scene ingest.json files in `Setup/` — designed for nested projects (YTCR01 style). Flat project has no scenes.
- **Resolution:** The transcription pipeline's `ingest_json.py` already generates UXP-format ingest.json directly at `Source/`. The output at `Source/YTCG37_Setup_UAE_Company_Remotely_ingest.json` is the correct UXP artifact. No additional generation needed.
- **Impact:** None — UXP ingest.json is complete and correct.

### Note: system Python vs venv

- First pipeline run used system Python 3.11 which had a torchaudio/torch symbol mismatch
- Fixed by using `.venv_transcribe` for the full run: `environment/.venv_transcribe/bin/python3`

## Checkpoint Verification (Auto-approved)

All key output files verified to exist:
- [x] v3.0 folder structure: `01_Media/Source/Video/`, `Audio/`, `Setup/`, `Transcription/`
- [x] 2 synced DJI WAV files in `Audio/`
- [x] `ingest.json` with 2 clips, sync offsets (`offset` field), transcription references
- [x] Speaker diarization: 2 speakers (SPEAKER_00, SPEAKER_01)
- [x] UXP ingest.json at `Source/` (flat project convention)

## Next Steps

1. Speaker ID via Claude Desktop project — assign speaker names to SPEAKER_00/SPEAKER_01
2. Import in Premiere Pro via UXP panel using the ingest.json
3. Open sync check project: `Setup/YTCG37_Setup_UAE_Company_Remotely_dji_sync_check.prproj`

## Self-Check: PASSED

- [x] `YTCG37_Setup_UAE_Company_Remotely_ingest.json` — EXISTS (2.2 KB)
- [x] `YTCG37_Setup_UAE_Company_Remotely_transcript.json` — EXISTS (1.2 MB)
- [x] `Audio/RYA-FX3-0099_TX02.wav` — EXISTS (2.4 MB)
- [x] `Audio/RYA-FX3-0100_TX02.wav` — EXISTS (302.8 MB)
- [x] Commit fc73021 — EXISTS
