# Roadmap: YTAI — Multi-Scene Nested Projects (v1.0)

## Overview

This milestone extends the existing flat-project pipeline to handle multi-scene nested projects. The work moves in one direction: organize raw footage by scene, sync per-clip DJI audio via waveform correlation, transcribe per-scene and merge, update the UXP plugin to navigate across scenes, then wire everything together in the pipeline runner. Every phase is additive — flat projects continue to work unchanged.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Organize** - Detect nested project and arrange files into v3.0 folder structure (completed 2026-03-16)
- [x] **Phase 2: Audio Sync** - Extract per-clip audio and sync all TX WAV files via waveform cross-correlation (completed 2026-03-17)
- [x] **Phase 3: Transcribe** - Run Whisper per-scene and merge into cross-scene transcript (completed 2026-03-17)
- [ ] **Phase 4: UXP Plugin** - Update Premiere Pro plugin to ingest multi-scene projects and enable cross-scene editing
- [ ] **Phase 5: Pipeline Integration** - Wire nested-mode auto-detection into run_pipeline.py with backward compatibility

## Phase Details

### Phase 1: Organize
**Goal**: Raw nested project files are arranged into the standard v3.0 structure, ready for audio and transcription steps
**Depends on**: Nothing (first phase)
**Requirements**: ORG-01, ORG-02, ORG-03, ORG-04, ORG-05, ORG-06
**Success Criteria** (what must be TRUE):
  1. Running the organize script on the reference project (`YTCR01_Arty_Dzis`) produces scene subfolders under `01_Media/Source/Video/` with all MP4 clips correctly placed
  2. All WAV files from TX01/, TX02/, TX02_2/ land flat in `99_Pipeline/DJI_Audio/` with original filenames preserved
  3. Sony XML sidecars land in `01_Media/Source/Transcription/per_clip/{scene}/{clip}/` and are not present in the Video folder
  4. Absence of XML sidecars does not error — the script runs to completion gracefully
  5. The full v3.0 folder skeleton (Audio/, Transcription/, Setup/logs/, LUT/) is present even for scenes with no sidecar
**Plans:** 3/3 plans complete

Plans:
- [x] 01-01-PLAN.md — Test scaffolding + core detection functions (is_nested_project, detect_scenes, v3.0 skeleton)
- [x] 01-02-PLAN.md — File move implementation (video clips per scene, DJI WAVs flat, XML sidecars with scene layer)
- [x] 01-03-PLAN.md — Dry-run summary output + human verification on reference project

### Phase 2: Audio Sync
**Goal**: Every clip in every scene has precisely synced TX01 and TX02 WAV files trimmed to clip duration, with sync accuracy reported per clip
**Depends on**: Phase 1
**Requirements**: AUD-01, AUD-02, AUD-03, AUD-04, AUD-05, AUD-06, AUD-07
**Success Criteria** (what must be TRUE):
  1. Each clip has a `{clip}_AUDIO.wav` extracted at 48kHz stereo under `Transcription/per_clip/{scene}/{clip}/`
  2. Each clip has `{clip}_TX01.wav` and `{clip}_TX02.wav` under `01_Media/Source/Audio/`, trimmed to the clip's duration
  3. The sync report for each clip shows delta in frames; all clips on the reference project achieve ≤1F delta
  4. The correct TX WAV candidate is selected per clip even when multiple TX files overlap in time (waveform correlation wins over timestamp proximity)
  5. Per-scene `ingest.json` lists A1=camera embed, A2=TX01_SYNC, A3=TX02_SYNC for every clip in the scene
**Plans:** 3/3 plans complete

Plans:
- [x] 02-01-PLAN.md — Test scaffold + core functions (detect_scenes, extract, correlate, trim, delta reporting)
- [x] 02-02-PLAN.md — CLI orchestration + ingest.json generation (process_scene, process_clip, main, --project/--scene/--dry-run)
- [x] 02-03-PLAN.md — Integration test on reference project apartment scene + human verification

### Phase 3: Transcribe
**Goal**: Every scene has a word-level transcript JSON, and all scenes are merged into a single cross-scene transcript
**Depends on**: Phase 2
**Requirements**: TRN-01, TRN-02, TRN-03
**Success Criteria** (what must be TRUE):
  1. Running transcription on the reference project produces `{scene}_transcript.json` for each of the 7 scenes under `01_Media/Source/Transcription/`
  2. `merged_transcript.json` exists and every word entry carries both `scene_id` and a local timecode within its scene
  3. Transcription can be re-run on a single scene without overwriting other scenes' outputs
**Plans:** 2/2 plans complete

Plans:
- [ ] 03-01-PLAN.md — TDD: scene orchestrator core functions + cross-scene transcript merger (detect_scenes, transcribe_scene, collect, merge)
- [ ] 03-02-PLAN.md — CLI orchestration (main, --project/--scene/--dry-run) + human verification on reference project apartment scene

### Phase 4: UXP Plugin
**Goal**: The Premiere Pro plugin ingests a multi-scene project, builds per-scene timelines, and lets the editor find and cut words across all scenes
**Depends on**: Phase 3
**Requirements**: UXP-01, UXP-02, UXP-03, UXP-04
**Success Criteria** (what must be TRUE):
  1. Loading a multi-scene `{project}_ingest.json` in the UXP panel creates a separate Premiere timeline and captions layer for each scene without manual steps
  2. The BRIEF screen populates from `merged_transcript.json` and search results show words with their originating scene
  3. Clicking a word in ASSEMBLY inserts the correct clip from the correct scene's timeline at the right timecode
  4. Flat single-scene projects load and edit identically to before (no regression)
**Plans**: TBD

### Phase 5: Pipeline Integration
**Goal**: `run_pipeline.py` auto-detects nested projects and orchestrates the full multi-scene pipeline end-to-end with a working dry-run mode
**Depends on**: Phase 4
**Requirements**: PIPE-01, PIPE-02, PIPE-03
**Success Criteria** (what must be TRUE):
  1. Running `run_pipeline.py` on the reference project (which has TX01/ folder) automatically selects nested mode and runs all nested-mode scripts in correct order
  2. Running `run_pipeline.py` on a flat project (no TX1/ folder) runs the original flat scripts unchanged
  3. `run_pipeline.py --dry-run` on the reference project prints: scenes found, clip counts per scene, TX folders detected — no files are moved
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Organize | 3/3 | Complete    | 2026-03-16 |
| 2. Audio Sync | 3/3 | Complete   | 2026-03-17 |
| 3. Transcribe | 2/2 | Complete   | 2026-03-17 |
| 4. UXP Plugin | TBD | Not started | - |
| 5. Pipeline Integration | TBD | Not started | - |
