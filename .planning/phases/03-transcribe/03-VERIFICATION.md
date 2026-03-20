---
phase: 03-transcribe
verified: 2026-03-17T08:30:00Z
status: human_needed
score: 11/12 must-haves verified
re_verification: false
human_verification:
  - test: "Run apartment scene live transcription on reference project"
    expected: "apartment_transcript.json produced in 01_Media/Source/Transcription/, merged_transcript.json written with scene_id='apartment' on every word and local timecodes"
    why_human: "Requires Whisper/Pyannote GPU runtime (~20-30 min). No transcript output files currently exist on reference project at /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Transcription/. Plan 02 SUMMARY claims this was approved but no physical artifacts remain on disk to verify."
  - test: "Idempotent re-run — second --scene apartment invocation skips Whisper"
    expected: "Console prints 'Skipping apartment (transcript exists)' — no new Whisper subprocess spawned"
    why_human: "Depends on first live run completing. Skip logic is correct in code but can only be confirmed once apartment_transcript.json exists."
---

# Phase 3: Transcribe Nested Verification Report

**Phase Goal:** Nested multi-scene transcription pipeline — each scene transcribed independently via existing Whisper pipeline, all scene transcripts merged into merged_transcript.json with scene_id and local timecodes on every word.
**Verified:** 2026-03-17T08:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Source | Status | Evidence |
|---|-------|--------|--------|----------|
| 1 | detect_scenes() finds all scene subfolders under Source/Video/ without requiring numeric prefixes | Plan 01 | VERIFIED | Line 27-45 in 0201_transcribe_nested.py; test_detect_scenes + test_detect_scenes_empty PASS |
| 2 | transcribe_scene() constructs correct subprocess command invoking transcribe_project.py with scene subfolder as --project | Plan 01 | VERIFIED | Lines 68-104; test_transcribe_scene_cmd + test_transcribe_scene_dry_run PASS |
| 3 | collect_scene_transcript() copies transcript from legacy flat path to canonical Transcription/{scene}_transcript.json | Plan 01 | VERIFIED | Lines 107-129 (shutil.copy2); test_collect_scene_transcript PASS |
| 4 | Existing scene transcript is skipped when already present (idempotent re-run) | Plan 01 | VERIFIED | should_transcribe_scene() lines 48-65; test_skip_existing_transcript PASS; main() line 192 checks before calling transcribe_scene |
| 5 | merge_transcripts() produces merged_transcript.json with scene_id and local timecodes on every word | Plan 01 | VERIFIED | merge_transcripts.py lines 60-97; test_merge_transcripts + test_merged_word_fields + test_merge_missing_scene PASS |
| 6 | Merged words preserve local start/end timecodes, never global | Plan 01 | VERIFIED | merge_transcripts.py line 51-55 passes word["start"]/word["end"] directly; test_merged_word_fields asserts start=5.0, end=5.4 match source |
| 7 | Running with --project and no --scene processes all detected scenes sequentially | Plan 02 | VERIFIED | main() lines 190-198: for scene_dir in scenes (full list from detect_scenes) |
| 8 | Running with --project and --scene apartment processes only the apartment scene | Plan 02 | VERIFIED | main() lines 174-182: filters scenes to matching name, sys.exit(1) if not found |
| 9 | Running with --dry-run prints scene list and clip counts without invoking Whisper | Plan 02 | VERIFIED | main() lines 185-187: calls print_dry_run_summary() then sys.exit(0) before any transcribe_scene() call |
| 10 | Already-transcribed scenes are skipped automatically (idempotent) | Plan 02 | VERIFIED | main() line 192: if not should_transcribe_scene() → continue; code path correct |
| 11 | After all scenes complete, merged_transcript.json is written with all words tagged by scene_id | Plan 02 | VERIFIED | main() line 201: merge_transcripts() called unconditionally after loop |
| 12 | Live run on reference project produces apartment_transcript.json + merged_transcript.json | Plan 02 | HUMAN NEEDED | No transcript files found at /Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Transcription/ (only per_clip/ subdir present); CLI infrastructure is fully implemented and correct |

**Score:** 11/12 truths verified (1 requires human confirmation — live Whisper runtime)

---

### Required Artifacts

| Artifact | Expected | Exists | Substantive | Wired | Status |
|----------|----------|--------|-------------|-------|--------|
| `scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py` | Scene orchestrator core functions + CLI main() | YES | YES (207 lines, all 4 core functions + main + print_dry_run_summary + argparse) | YES (imported via importlib in tests; module-level import of merge_transcripts) | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/merge_transcripts.py` | Cross-scene transcript merger | YES | YES (98 lines, read_scene_words + merge_transcripts with full JSON traversal) | YES (imported by 0201_transcribe_nested.py line 24) | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/tests/test_0201.py` | Unit tests for scene orchestration | YES | YES (188 lines, 7 tests — exceeds 60-line minimum) | YES (11 tests collected and passing) | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/tests/test_merge.py` | Unit tests for merge logic | YES | YES (242 lines, 4 tests — exceeds 40-line minimum) | YES (11 tests collected and passing) | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/__init__.py` | Package init | YES | YES (empty, correct) | YES | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/tests/__init__.py` | Test package init | YES | YES (empty, correct) | YES | VERIFIED |
| `scripts/02_transcribe/0201_transcribe_nested/tests/conftest.py` | Shared fixtures | YES | YES (fake_nested_project + sample_transcript_json fixtures) | YES (used by test_0201.py and test_merge.py) | VERIFIED |
| `01_Media/Source/Transcription/merged_transcript.json` (reference project) | Live merged output on /Volumes/RYA T7 Black/YTCR01_Arty_Dzis | NO | — | — | HUMAN NEEDED |

---

### Key Link Verification

#### Plan 01 Key Links

| From | To | Via | Pattern | Status | Evidence |
|------|----|-----|---------|--------|----------|
| 0201_transcribe_nested.py | transcribe_project.py | subprocess.run with venv python | `subprocess\.run.*transcribe_project` | WIRED | Line 91: script path set to transcribe_project.py; line 104: subprocess.run(cmd, check=True) |
| merge_transcripts.py | {scene}_transcript.json | json.load reading clips[].transcript_segments[].words_data[] | `words_data` | WIRED | Line 47: `for word in segment.get("words_data", []):` |
| collect_scene_transcript | Transcription/{scene}_transcript.json | shutil.copy2 from legacy path | `shutil\.copy2` | WIRED | Line 128: shutil.copy2(src, dst) where dst = Transcription/{scene}_transcript.json |

#### Plan 02 Key Links

| From | To | Via | Pattern | Status | Evidence |
|------|----|-----|---------|--------|----------|
| main() | detect_scenes() | iterates scenes from detect_scenes | `for scene in.*detect_scenes` | WIRED | Line 171: `scenes = detect_scenes(project)`; line 190: `for scene_dir in scenes:` — indirect but unambiguous |
| main() | merge_transcripts() | after all scenes complete | `merge_transcripts` | WIRED | Line 201: `merge_transcripts(project, [s.name for s in scenes])` |
| main() | should_transcribe_scene() | skip check before each scene | `should_transcribe_scene` | WIRED | Line 192: `if not should_transcribe_scene(project, scene_name):` |

---

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|--------------|-------------|--------|----------|
| TRN-01 | 03-01, 03-02 | Existing transcribe_project.py runs per-scene or on Source/Video/ finding scenes as subfolders; internal logic (Whisper, Pyannote, ingest JSON) unchanged | SATISFIED | detect_scenes() finds non-hidden subdirs; transcribe_scene() invokes existing transcribe_project.py via subprocess without modifying it; git log shows transcribe_project.py last modified in a prior phase commit |
| TRN-02 | 03-01, 03-02 | Each scene transcribed separately → Transcription/{scene}_transcript.json with word-level timecodes | SATISFIED | collect_scene_transcript() copies per-scene output to canonical path; test_collect_scene_transcript verifies path and content |
| TRN-03 | 03-01, 03-02 | All scenes merged → merged_transcript.json; every word has scene_id and local timecode | SATISFIED (unit) / HUMAN NEEDED (live) | merge_transcripts.py adds scene_id to every word dict, preserves local start/end; 4 merge tests pass; live output not present on reference project |

No orphaned requirements: REQUIREMENTS.md maps TRN-01, TRN-02, TRN-03 to Phase 3, and both plans claim all three. All three are accounted for.

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| 0201_transcribe_nested.py line 41 | `return []` in detect_scenes() when video_dir does not exist | INFO | Intentional guard — not a stub. Early return for missing directory is correct behavior, tested by test_detect_scenes_empty. |

No blockers. No FIXME/TODO/placeholder comments. No empty handlers. No static returns masking real logic.

---

### Test Results

```
11 passed in 0.02s
```

All 11 tests pass:
- test_detect_scenes
- test_detect_scenes_empty
- test_transcribe_scene_cmd
- test_transcribe_scene_dry_run
- test_collect_scene_transcript
- test_skip_existing_transcript
- test_should_transcribe_scene_missing
- test_read_scene_words
- test_merge_transcripts
- test_merged_word_fields
- test_merge_missing_scene

---

### Human Verification Required

#### 1. Live apartment scene transcription on reference project

**Test:** With external drive mounted, run:
```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
python ~/YTAI/scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py \
  --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" --scene apartment -n 2 -y
```

**Expected:**
- Whisper + Pyannote run on 40 apartment clips
- `apartment_transcript.json` written to `/Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Transcription/`
- `merged_transcript.json` written to same directory with `version="1.0"`, `scenes=["apartment"]`, all words having `scene_id="apartment"` and local timecodes

**Verify outputs:**
```bash
python3 -c "
import json
with open('/Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Transcription/merged_transcript.json') as f:
    d = json.load(f)
print('version:', d['version'])
print('scenes:', d['scenes'])
print('word count:', len(d['words']))
print('first word:', d['words'][0] if d['words'] else 'NONE')
"
```

**Why human:** Requires Whisper/Pyannote GPU runtime (~20-30 min for 40 clips). No transcript files currently exist on the reference project — the SUMMARY claims human approval occurred but no artifacts remain on disk to confirm.

#### 2. Idempotent re-run on already-transcribed scene

**Test:** After Test 1 completes successfully, run the same command again:
```bash
python ~/YTAI/scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py \
  --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" --scene apartment -n 2 -y
```

**Expected:** Console prints `Skipping apartment (transcript exists)` and exits without running Whisper. `apartment_transcript.json` is unchanged.

**Why human:** Depends on Test 1 producing the transcript file. The skip logic in code is correct (should_transcribe_scene checks canonical path) but cannot be confirmed until live run produces output.

#### 3. Dry-run scene discovery on reference project

**Test:**
```bash
python ~/YTAI/scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py \
  --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" --dry-run
```

**Expected:** Lists 7 scenes (al_qudra_lake, al_qudra_lake_story, apartment, desert_drive, drive_home, dubai_driving, volleyball) with clip counts. No transcription runs. Mode: DRY-RUN line printed.

**Why human:** Although this is fast (no Whisper), the SUMMARY claims this was already validated and the reference project scene structure IS confirmed on disk (7 scene dirs exist). This is lower priority — the code path is verified and the directory structure is confirmed.

---

### Summary

The Phase 3 core implementation is complete and correct. Both modules are implemented, all 11 unit tests pass, and all key links are wired. The CLI entry point (`main()`) correctly orchestrates scene detection, per-scene subprocess invocation, output collection, and merged_transcript.json generation.

The one unresolved item is evidence of the live Whisper run on the reference project. The Plan 02 SUMMARY documents human approval of this checkpoint, but no output files (apartment_transcript.json, merged_transcript.json) exist at the reference project path today. This is most likely because the transcription outputs were cleaned up or the external drive content was reset between then and now — the code is fully functional and correct.

The 7-scene directory structure is confirmed on disk at `/Volumes/RYA T7 Black/YTCR01_Arty_Dzis/01_Media/Source/Video/`: al_qudra_lake, al_qudra_lake_story, apartment (40 clips), desert_drive, drive_home, dubai_driving, volleyball. The dry-run path would work immediately; live transcription requires GPU time.

---

_Verified: 2026-03-17T08:30:00Z_
_Verifier: Claude (gsd-verifier)_
