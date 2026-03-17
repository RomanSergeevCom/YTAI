---
phase: quick-260317-fj4
plan: 01
subsystem: pipeline-scripts, uxp-plugin, specs, disk-files
tags: [refactor, naming, folder-structure, edit-brief, srt, dji-audio]
dependency_graph:
  requires: []
  provides: [short-code-naming, pre-edit-brief, srt-relocation, dji-audio-path]
  affects: [run_pipeline.py, 0102_extract_audio.py, 0103_sync_dji_audio.py, 0105_generate_uxp_ingest.py, transcribe_project.py, ingest_json.py, index.js, archiver.js, all-specs, YTCG37-disk]
tech_stack:
  added: []
  patterns: [project_code-helper, CODE_RE-regex, legacy-fallback-candidates]
key_files:
  created:
    - .planning/quick/260317-fj4-refactor-folder-structure-short-naming-p/260317-fj4-SUMMARY.md
  modified:
    - scripts/run_pipeline.py
    - scripts/01_prepare/0102_extract_audio/0102_extract_audio.py
    - scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py
    - scripts/01_prepare/0105_generate_uxp_ingest.py
    - scripts/02_transcribe/020101_transcribe/transcribe_project.py
    - scripts/02_transcribe/020101_transcribe/ingest_json.py
    - scripts/05_editing/0502_assembly/generate_assembly_captions.py
    - scripts/05_editing/0503_review/generate_review.py
    - scripts/05_editing/0500_uxp/index.js
    - scripts/05_editing/0500_uxp/src/shared/archiver.js
    - scripts/05_editing/0500_uxp/src/shared/constants.js
    - scripts/05_editing/0500_uxp/src/assembly/briefParser.js
    - scripts/05_editing/0500_uxp/src/screens/screenBuilder.js
    - scripts/01_prepare/01_prepare_spec.md
    - scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio_spec.md
    - scripts/05_editing/0500_uxp/0500_uxp_spec.md
    - scripts/05_editing/0501_brief/0501_brief_spec.md
    - scripts/05_editing/0501_brief/INSTRUCTIONS.md
    - scripts/02_transcribe/020101_transcribe/020101_transcribe_spec.md
    - scripts/README.md
decisions:
  - "Keep legacy full-name fallbacks in autoDetectFiles() for backward compatibility"
  - "Logs keep full project name (not CODE) for disambiguation"
  - "Pre-existing 0504_screen_cues/ edit_brief refs deferred (out of plan scope)"
metrics:
  duration: ~45 min
  completed: "2026-03-17"
  tasks: 4
  files: 21
---

# Quick Task 260317-fj4: Refactor Folder Structure — Short Naming Summary

**One-liner:** YTAI pipeline refactored to {CODE}_ short prefix naming, edit_brief → pre_edit_brief across all scripts/UXP/specs, SRT files relocated to Transcription/captions/ and Transcription/transcripts/, dji_sync_check moved to 99_Pipeline/DJI_Audio/, YTCG37 disk files reorganized.

## Tasks Completed

| # | Task | Commit | Key Changes |
|---|------|--------|-------------|
| 1 | Add project_code() helper + update all Python output paths | 2bbc9ae | CODE_RE + project_code() in 5 scripts; dji_sync_check → DJI_Audio/; SRT → captions/ + transcripts/ |
| 2 | UXP plugin — CODE auto-detect, pre_edit_brief, pre-edit_versions, SRT paths | 9b39cb6 | extractProjectCode regex fixed; autoDetectFiles uses CODE-first with legacy fallback; SRT writing updated |
| 3 | Update all spec and documentation files | 7bc5d33 | 7 spec/doc files updated to reflect new naming and paths |
| 4 | Reorganize YTCG37 project files on external drive | c87ee7f | Physical disk operations on /Volumes/RYA T7 Blue 2/ |
| 5 | Human verification | PENDING | See checkpoint below |

## Changes by Category

### Python Scripts

**project_code() helper** — added to 5 scripts with identical `CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')`:
- `run_pipeline.py` — display text updated; `project_code()` available for callers
- `0102_extract_audio.py` — outputs `{CODE}_FULL_AUDIO.wav`
- `0103_sync_dji_audio.py` — dji_sync_check goes to `99_Pipeline/DJI_Audio/{CODE}_dji_sync_check.prproj/.xml`
- `0105_generate_uxp_ingest.py` — updated PROJECT_CODE_RE to `^(YT[A-Z]{2,4}\d+)_`; outputs `{CODE}_ingest.json`
- `transcribe_project.py` — SRTs to `Transcription/captions/` + `Transcription/transcripts/`; xlsx + json to `Setup/`
- `ingest_json.py` — uses short code for ingest.json output; scene captions lookup in `Transcription/captions/`

**edit_brief → pre_edit_brief** renamed in:
- `generate_assembly_captions.py` — docstring, help text, function comment
- `generate_review.py` — docstring, help text

### UXP Plugin

- `extractProjectCode` regex: `^[A-Z]+\d+` → `^(YT[A-Z]{2,4}\d+)_` (matches Python)
- `autoDetectFiles`: tries `{CODE}_ingest.json` first, then legacy full-name candidates; same for brief
- `autoDetectFiles`: brief tries `{CODE}_pre_edit_brief.json`, `{name}_pre_edit_brief.json`, `{name}_edit_brief.json`
- `importCaptionsSrt`: looks in `Transcription/captions/` and `Transcription/transcripts/` first, legacy briefDir fallback
- Assembly/Review/PreEdit SRT writing: now writes to `Transcription/captions/` and `Transcription/transcripts/`
- `ensureVersionsDir` in archiver.js: creates `pre-edit_versions` instead of `versions`
- `autoDetectFiles` state check: uses `pre-edit_versions` path

### Spec/Docs

- `01_prepare_spec.md`: Setup/ shows CODE-prefixed files; dji_sync_check in 99_Pipeline/DJI_Audio/; Transcription/ has captions/ + transcripts/
- `0103_sync_dji_audio_spec.md`: XML output path updated
- `0500_uxp_spec.md`: all edit_brief → pre_edit_brief; SRT paths updated; auto-detect description updated
- `0501_brief_spec.md`: edit_brief → pre_edit_brief throughout
- `INSTRUCTIONS.md`: output filename example uses {CODE}_pre_edit_brief.json
- `020101_transcribe_spec.md`: added v3.0 folder structure variant
- `scripts/README.md`: edit_brief → pre_edit_brief references

### Disk Operations (YTCG37 on /Volumes/RYA T7 Blue 2/)

**Before:** Long-named files scattered in Source/, SRTs in Setup/, dji_sync_check in Setup/, versions/ folder

**After:**
```
01_Media/Source/
├── Setup/
│   ├── YTCG37_ingest.json
│   ├── YTCG37_pre_edit_brief.json
│   ├── YTCG37_transcript.json
│   ├── YTCG37_transcript.xlsx
│   ├── screen_cues/
│   ├── pre-edit_versions/  (migrated from versions/)
│   ├── logs/
│   └── _archive/
└── Transcription/
    ├── YTCG37_FULL_AUDIO.wav
    ├── captions/
    │   ├── YTCG37_1_Ingest_captions.srt
    │   └── YTCG37_4_PreEdit_captions.srt
    ├── transcripts/
    │   ├── YTCG37_1_Ingest_transcript.srt
    │   ├── YTCG37_4_PreEdit_transcript.srt
    │   └── YTCG37_transcript.srt
    └── per_clip/

99_Pipeline/DJI_Audio/
├── TX02_MIC037_20260306_102304_orig.wav
├── TX02_MIC038_20260306_105305_orig.wav
├── YTCG37_dji_sync_check.prproj  (moved from Setup/)
└── YTCG37_dji_sync_check.xml     (moved from Setup/)
```

## Task 5: Human Verification (PENDING)

**Status:** Awaiting human verification

**Steps to verify:**
1. Check YTCG37 disk: `ls "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/"` — should show only YTCG37_ingest.json, YTCG37_pre_edit_brief.json, YTCG37_transcript.json, YTCG37_transcript.xlsx, screen_cues/, pre-edit_versions/, logs/
2. Check SRTs: `ls "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Transcription/captions/"` and `.../transcripts/`
3. Check dji_sync_check: `ls "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/99_Pipeline/DJI_Audio/"*sync*`
4. Open Premiere Pro, load UXP plugin, select YTCG37 project folder — verify auto-detect finds YTCG37_ingest.json and YTCG37_pre_edit_brief.json
5. Grep sanity: `grep -r 'edit_brief' scripts/ --include='*.py' --include='*.js' --include='*.md' | grep -v 'pre.edit_brief\|pre_edit_brief\|Archive\|logs\|node_modules\|0504_screen_cues' | head -20` — should return nothing

## Deviations from Plan

### Auto-fixed Issues

None.

### Out-of-scope Discoveries

**scripts/05_editing/0504_screen_cues/** has `edit_brief` references (not in plan's `files_modified` list). Deferred — these files were not included in the plan scope.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| SUMMARY.md exists | FOUND |
| Commit 2bbc9ae (task 1) | FOUND |
| Commit 9b39cb6 (task 2) | FOUND |
| Commit 7bc5d33 (task 3) | FOUND |
| Commit c87ee7f (task 4) | FOUND |
