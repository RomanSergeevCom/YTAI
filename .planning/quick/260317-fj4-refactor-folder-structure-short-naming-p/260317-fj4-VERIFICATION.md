---
phase: quick-260317-fj4
verified: 2026-03-17T12:00:00Z
status: gaps_found
score: 5/7 must-haves verified
gaps:
  - truth: "edit_brief renamed to pre-edit_brief in all scripts, specs, and UXP plugin"
    status: partial
    reason: "0500_uxp_spec.md and 0501_brief_spec.md contain 'pre_pre_edit_brief' (double-prefix typo) from the rename pass — 6 occurrences in 0500_uxp_spec.md, 4 in 0501_brief_spec.md"
    artifacts:
      - path: "scripts/05_editing/0500_uxp/0500_uxp_spec.md"
        issue: "Lines 7-9, 37, 175, 283 use 'pre_pre_edit_brief' instead of 'pre_edit_brief'"
      - path: "scripts/05_editing/0501_brief/0501_brief_spec.md"
        issue: "Lines 6, 34, 51, 52 use 'pre_pre_edit_brief' instead of 'pre_edit_brief'"
    missing:
      - "Replace all 'pre_pre_edit_brief' with 'pre_edit_brief' in 0500_uxp_spec.md"
      - "Replace all 'pre_pre_edit_brief' with 'pre_edit_brief' in 0501_brief_spec.md"
  - truth: "Setup/ contains only ingest.json, pre-edit_brief.json, transcript.json, transcript.xlsx, screen_cues/, pre-edit_versions/, logs/"
    status: partial
    reason: "Setup/ on disk also contains 'exports' subfolder which is not in the approved contents list from the plan"
    artifacts:
      - path: "/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely/01_Media/Source/Setup/"
        issue: "Directory listing shows: YTCG37_ingest.json, YTCG37_pre_edit_brief.json, YTCG37_transcript.json, YTCG37_transcript.xlsx, _archive, exports, logs, pre-edit_versions, screen_cues — 'exports' folder is extra"
    missing:
      - "Decide whether 'exports' folder belongs in Setup/ or should be moved; update CONTEXT.md or clean up"
human_verification:
  - test: "Open Premiere Pro, load UXP plugin, select YTCG37 project folder"
    expected: "Auto-detect checklist shows YTCG37_ingest.json and YTCG37_pre_edit_brief.json as found (green); no errors"
    why_human: "Cannot run Premiere Pro + UXP plugin programmatically"
---

# Quick Task 260317-fj4: Refactor Folder Structure Verification Report

**Task Goal:** Refactor folder structure: short naming (YTCG37_ prefix), rename edit_brief → pre-edit_brief, move captions/transcripts to Transcription/captions/ and Transcription/transcripts/, move dji_sync_check to 99_Pipeline/DJI_Audio/, Setup contains only main docs. Update all pipeline scripts + UXP plugin + specs + reorganize YTCG37 project files.
**Verified:** 2026-03-17T12:00:00Z
**Status:** gaps_found — 2 gaps, 1 human verification needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All output files use short CODE prefix (YTCG37_) not full project name | VERIFIED | `project_code()` + `CODE_RE` present in run_pipeline.py, 0102, 0103, 0105, transcribe_project.py, ingest_json.py; 0102 line 212: `f"{project_code(project_dir)}_FULL_AUDIO.wav"`; 0105 line 179: `f"{code}_ingest.json"` |
| 2 | edit_brief renamed to pre-edit_brief in all scripts, specs, and UXP plugin | PARTIAL | Python scripts: clean. UXP plugin (index.js, archiver.js, constants.js, briefParser.js, screenBuilder.js): clean. But 0500_uxp_spec.md has 6 occurrences of `pre_pre_edit_brief` (double-prefix typo) and 0501_brief_spec.md has 4. Note: 0504_screen_cues/ scripts were explicitly deferred in SUMMARY as out-of-scope. |
| 3 | SRT captions written to Transcription/captions/, SRT transcripts to Transcription/transcripts/ | VERIFIED | transcribe_project.py: captions_dir → `Transcription/captions/`, transcripts_dir → `Transcription/transcripts/`. index.js assembly/review/screens SRT blocks confirmed writing to both dirs. Disk: `YTCG37_1_Ingest_captions.srt` + `YTCG37_4_PreEdit_captions.srt` in captions/; 3 SRTs in transcripts/ |
| 4 | dji_sync_check files written to 99_Pipeline/DJI_Audio/ not Setup/ | VERIFIED | 0103: `DJI_SUBDIR = "99_Pipeline/DJI_Audio"`, line 1381 builds `dji_audio_dir`. Disk: `YTCG37_dji_sync_check.prproj` + `.xml` confirmed in `99_Pipeline/DJI_Audio/` |
| 5 | Setup/ contains only ingest.json, pre-edit_brief.json, transcript.json, transcript.xlsx, screen_cues/, pre-edit_versions/, logs/ | PARTIAL | Core files are correct. But disk listing also shows `exports/` and `_archive/` — `_archive/` is internal/legacy, but `exports/` is not in the approved list |
| 6 | UXP plugin auto-detects ingest.json and pre-edit_brief.json with short CODE prefix | VERIFIED | index.js extractProjectCode regex updated to `^(YT[A-Z]{2,4}\d+)_` (matches Python). autoDetectFiles tries `{code}_ingest.json` first (line 312+), `{code}_pre_edit_brief.json` first (line 346), with legacy fallbacks |
| 7 | YTCG37 project files on disk match new structure | VERIFIED | Setup/ has short-prefixed files, pre-edit_versions/ created (old versions/ gone), Transcription/captions/ + transcripts/ populated, DJI_Audio/ has sync files. Minor: exports/ folder present (gap #2) |

**Score:** 5/7 truths fully verified (2 partial)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/run_pipeline.py` | `def project_code` helper | VERIFIED | Lines 93-98: `CODE_RE` + `project_code()` |
| `scripts/01_prepare/0102_extract_audio/0102_extract_audio.py` | `project_code` helper, `{CODE}_FULL_AUDIO.wav` | VERIFIED | Lines 50-55: helper; line 212: output uses `project_code(project_dir)` |
| `scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` | dji_sync_check → 99_Pipeline/DJI_Audio/ | VERIFIED | Line 47: `DJI_SUBDIR`, lines 1381-1384: path construction |
| `scripts/05_editing/0500_uxp/index.js` | Updated regex + pre_edit_brief autoDetect | VERIFIED | extractProjectCode uses `^(YT[A-Z]{2,4}\d+)_`; brief candidates include `_pre_edit_brief.json` with legacy fallback |
| `scripts/05_editing/0500_uxp/src/shared/archiver.js` | `pre-edit_versions` folder name | VERIFIED | Line 243: `ensureSubfolder(folder, 'pre-edit_versions', ...)`, line 244: return path |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `scripts/run_pipeline.py` | `scripts/01_prepare/0105_generate_uxp_ingest.py` | `project_code()` for output filename | VERIFIED | run_pipeline.py has `project_code()`; 0105 has `PROJECT_CODE_RE` + `code` variable used in `out_path` (line 179) |
| `scripts/05_editing/0500_uxp/index.js` | `Setup/{CODE}_ingest.json` | `autoDetectFiles` uses `extractProjectCode` | VERIFIED | Line 312: `var code = extractProjectCode(projectName)` then used in ingest candidates |
| `scripts/05_editing/0500_uxp/index.js` | `Setup/{CODE}_pre_edit_brief.json` | autoDetectFiles brief detection | VERIFIED | Line 344-348: brief candidates list, CODE-based `pre_edit_brief.json` is first candidate |

---

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| REFACTOR-FOLDERS | Refactor folder structure with short naming, rename edit_brief, relocate SRTs, move dji_sync_check | MOSTLY SATISFIED | All code changes complete; 2 spec typos in double-prefix (pre_pre_edit_brief); exports/ folder unexplained on disk |

---

### Anti-Patterns Found

| File | Lines | Pattern | Severity | Impact |
|------|-------|---------|----------|--------|
| `scripts/05_editing/0500_uxp/0500_uxp_spec.md` | 7, 8, 9, 37, 175, 283 | `pre_pre_edit_brief` (double-prefix typo from rename) | Warning | Spec is inconsistent with actual filename `pre_edit_brief.json` — will confuse readers |
| `scripts/05_editing/0501_brief/0501_brief_spec.md` | 6, 34, 51, 52 | `pre_pre_edit_brief` (double-prefix typo from rename) | Warning | Same — spec docs the wrong filename |
| `scripts/05_editing/0502_assembly/generate_assembly_captions_spec.md` | 6, 23-25, 32, 93, 173, 217 | Bare `edit_brief` (not in plan's files_modified list) | Info | Out-of-scope per SUMMARY decisions; not a blocker |
| `scripts/05_editing/05_editing_spec.md` | Multiple | Bare `edit_brief` throughout | Info | Out-of-scope (not in plan's `files_modified`); not a blocker |
| `scripts/05_editing/0501_brief/0501_brief.md` | 19, 39, 47, 48, 63, 68, 69 | Bare `edit_brief` | Info | Out-of-scope (not in plan's `files_modified`); not a blocker |
| `scripts/05_editing/0504_screen_cues/generate_screen_cues.py` | Multiple | Bare `edit_brief` | Info | Explicitly deferred in SUMMARY as out-of-scope |

---

### Human Verification Required

### 1. UXP Auto-Detect with Short CODE Prefix

**Test:** Open Premiere Pro, load UXP plugin, select `/Volumes/RYA T7 Blue 2/YTCG37_Setup_UAE_Company_Remotely` as project folder
**Expected:** Checklist shows `YTCG37_ingest.json` found (green tick) and `YTCG37_pre_edit_brief.json` found (green tick)
**Why human:** Cannot run Premiere Pro + UXP plugin in automated verification

---

### Gaps Summary

**Gap 1 — Double-prefix typo in spec files (pre_pre_edit_brief):**
During the rename pass from `edit_brief` to `pre_edit_brief`, the sed/replace operation was applied to text that already had `pre_` added, resulting in `pre_pre_edit_brief` in `0500_uxp_spec.md` (6 occurrences) and `0501_brief_spec.md` (4 occurrences). These specs now document a filename that doesn't match what scripts actually produce (`pre_edit_brief.json`). Fix: replace `pre_pre_edit_brief` with `pre_edit_brief` in both files.

**Gap 2 — Unexpected `exports/` folder in Setup/:**
The disk state of `Setup/` shows an `exports/` subdirectory not mentioned in the plan's target structure. This could be legitimate (UXP plugin export output) or leftover. The plan's `done` criteria specifies only: ingest.json, pre_edit_brief.json, transcript.json, transcript.xlsx, screen_cues/, pre-edit_versions/, logs/, _archive/. The `exports/` folder is extra. Recommend: confirm whether `exports/` is expected and update CONTEXT.md/spec if so, or move it out.

---

_Verified: 2026-03-17T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
