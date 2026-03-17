---
phase: 03-transcribe
plan: 01
subsystem: transcription
tags: [python, pytest, tdd, subprocess, json, whisper, pyannote]

# Dependency graph
requires:
  - phase: 02-audio-sync
    provides: "Per-scene organized video structure at Source/Video/{scene}/ used by detect_scenes()"
provides:
  - "detect_scenes(): returns sorted non-hidden dirs from Source/Video/"
  - "should_transcribe_scene(): idempotent skip check for existing transcripts"
  - "transcribe_scene(): subprocess invocation of transcribe_project.py per scene"
  - "collect_scene_transcript(): shutil.copy2 from legacy flat path to canonical Transcription/{scene}_transcript.json"
  - "read_scene_words(): flat word list with scene_id tag from transcript JSON"
  - "merge_transcripts(): merged_transcript.json with scene_id + local timecodes on every word"
affects:
  - "03-02: CLI orchestrator that wires these functions with main() + argparse"
  - "04-editing: UXP plugin consumes merged_transcript.json via scene_id routing"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "importlib.util.spec_from_file_location with scope=module fixture for digit-prefixed module names (established in Phase 2, confirmed here)"
    - "Per-scene subprocess invocation: transcribe_project.py called once per scene with scene subfolder as --project (flat mode)"
    - "Legacy path collection: transcribe_project.py writes to {scene_dir}/{scene}_transcription/; wrapper copies to canonical Transcription/{scene}_transcript.json"
    - "Local timecodes preserved in merged_transcript.json: scene_id routes to Premiere timeline, start/end seek within it"

key-files:
  created:
    - scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py
    - scripts/02_transcribe/0201_transcribe_nested/merge_transcripts.py
    - scripts/02_transcribe/0201_transcribe_nested/__init__.py
    - scripts/02_transcribe/0201_transcribe_nested/tests/__init__.py
    - scripts/02_transcribe/0201_transcribe_nested/tests/conftest.py
    - scripts/02_transcribe/0201_transcribe_nested/tests/test_0201.py
    - scripts/02_transcribe/0201_transcribe_nested/tests/test_merge.py
  modified: []

key-decisions:
  - "Per-scene subprocess invocation (Option A from RESEARCH.md): transcribe_project.py called with --project pointing at scene subfolder; wrapper handles legacy output path collection"
  - "merged_transcript.json uses sorted(scene_names) for consistent output across runs"
  - "detect_scenes excludes hidden dirs (starts with '.') only — no numeric prefix requirement (consistent with Phase 1+2)"
  - "should_transcribe_scene checks canonical Transcription/ path (not legacy path) for idempotent skip logic"
  - "11 tests written (plan said 10 minimum — extra test_should_transcribe_scene_missing added for completeness)"

patterns-established:
  - "Phase 3 orchestration: detect_scenes -> [should_transcribe_scene -> transcribe_scene -> collect_scene_transcript] per scene -> merge_transcripts"
  - "Transcript path routing: transcribe_project.py flat mode output at {scene_dir}/{scene}_transcription/ gets copied to Transcription/{scene}_transcript.json by collect_scene_transcript()"

requirements-completed: [TRN-01, TRN-02, TRN-03]

# Metrics
duration: 3min
completed: 2026-03-17
---

# Phase 3 Plan 01: Transcribe Nested Summary

**Scene orchestrator (detect/transcribe/collect) + merge module delivering 7 testable functions across 2 modules, all 11 unit tests green via subprocess mocking and JSON fixture patterns**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-17T07:31:50Z
- **Completed:** 2026-03-17T07:34:50Z
- **Tasks:** 2 (RED + GREEN)
- **Files modified:** 7 created, 0 modified

## Accomplishments

- TDD RED phase: 11 failing tests written across test_0201.py and test_merge.py with conftest fixtures
- TDD GREEN phase: 0201_transcribe_nested.py and merge_transcripts.py implemented; all 11 tests pass in 0.02s
- detect_scenes, should_transcribe_scene, transcribe_scene, collect_scene_transcript, read_scene_words, merge_transcripts — all tested and verified

## Task Commits

Each task was committed atomically:

1. **Task 1: RED — Test scaffold for scene orchestration + merge** - `f43fa6f` (test)
2. **Task 2: GREEN — Implement scene orchestrator + merge modules** - `d900901` (feat)

**Plan metadata:** committed with this SUMMARY.md

_Note: TDD tasks have separate commits (test RED → feat GREEN)_

## Files Created/Modified

- `scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py` - detect_scenes, should_transcribe_scene, transcribe_scene, collect_scene_transcript, main()
- `scripts/02_transcribe/0201_transcribe_nested/merge_transcripts.py` - read_scene_words, merge_transcripts
- `scripts/02_transcribe/0201_transcribe_nested/__init__.py` - empty package init
- `scripts/02_transcribe/0201_transcribe_nested/tests/__init__.py` - empty test package init
- `scripts/02_transcribe/0201_transcribe_nested/tests/conftest.py` - fake_nested_project + sample_transcript_json fixtures
- `scripts/02_transcribe/0201_transcribe_nested/tests/test_0201.py` - 7 tests for scene orchestration functions
- `scripts/02_transcribe/0201_transcribe_nested/tests/test_merge.py` - 4 tests for merge module

## Decisions Made

- Per-scene subprocess invocation (Option A from RESEARCH.md): no changes to transcribe_project.py; wrapper handles output path routing via shutil.copy2
- merged_transcript.json uses sorted(scene_names) to ensure deterministic output
- detect_scenes excludes hidden dirs by name prefix check (no numeric prefix requirement)
- should_transcribe_scene checks canonical Transcription/ path — ensures idempotent skip logic uses the post-collection path, not the legacy flat path
- 11 tests written (plan minimum was 10) — added test_should_transcribe_scene_missing for completeness

## Deviations from Plan

None - plan executed exactly as written. The 11th test (test_should_transcribe_scene_missing) is an additive quality improvement within scope, not a deviation from the plan's required behaviors.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 6 core functions implemented and tested: ready for Plan 02 CLI orchestrator wiring
- Module importable via importlib.util for Plan 02's main() scaffolding
- No modifications to existing transcribe_project.py or ingest_json.py

---
*Phase: 03-transcribe*
*Completed: 2026-03-17*
