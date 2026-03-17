---
phase: 03-transcribe
plan: "02"
subsystem: transcribe
tags: [whisper, pyannote, argparse, cli, nested-project, transcript, merge]

# Dependency graph
requires:
  - phase: 03-01
    provides: "detect_scenes(), should_transcribe_scene(), transcribe_scene(), collect_scene_transcript(), merge_transcripts()"
  - phase: 02-audio-sync
    provides: "Validated nested project structure with 7 scenes, TX audio synced"
provides:
  - "CLI-runnable 0201_transcribe_nested.py with --project, --scene, --speakers, --dry-run flags"
  - "main() orchestrates scene detection, per-scene transcription, output collection, and merged_transcript.json generation"
  - "print_dry_run_summary() lists all scenes with clip counts, no Whisper invoked"
  - "Idempotent skip logic: already-transcribed scenes skipped automatically"
  - "Validated on reference project: apartment scene transcript + merged_transcript.json with scene_id"
affects: [04-brief, 05-editing, 0201_transcribe_nested, 0500_uxp]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "argparse CLI pattern mirroring 0103_sync_dji_audio.py: --project, --scene, --dry-run, -n/--speakers, -y"
    - "print_dry_run_summary() gates live processing — called before any Whisper invocation"
    - "merge_transcripts() called unconditionally after loop — always regenerates merged output"

key-files:
  created: []
  modified:
    - "scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py"

key-decisions:
  - "merge_transcripts() is called after every run (even --scene single-scene) — merged output stays current without requiring all scenes to complete first"
  - "Dry-run gate confirmed on YTCR01_Arty_Dzis: 7 scenes listed, no Whisper runs — same UX pattern as Phase 2 sync script"
  - "apartment scene (40 clips) chosen as live validation target: smallest representative scene with known good TX audio"

patterns-established:
  - "CLI pattern: --project required, --scene optional filter, --dry-run no-op preview, -y skip confirmation — consistent across all pipeline scripts"
  - "Human verification checkpoint after CLI implementation: dry-run first, then single scene live, then idempotent re-run check"

requirements-completed: [TRN-01, TRN-02, TRN-03]

# Metrics
duration: 15min
completed: 2026-03-17
---

# Phase 3 Plan 02: Transcribe CLI Orchestration Summary

**argparse CLI for 0201_transcribe_nested.py: --project/--scene/--dry-run flags wired to scene detection, per-scene Whisper transcription, and merged_transcript.json generation — validated on reference project apartment scene**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-17T07:35:00Z
- **Completed:** 2026-03-17T07:47:54Z
- **Tasks:** 2 (1 auto + 1 human-verify checkpoint)
- **Files modified:** 1

## Accomplishments

- Added main() with argparse to 0201_transcribe_nested.py — script is now CLI-runnable end-to-end
- print_dry_run_summary() prints scene list with per-scene clip counts, exits without invoking Whisper
- Validated on reference project (YTCR01_Arty_Dzis): dry-run listed 7 scenes, apartment scene produced apartment_transcript.json with word-level timecodes, merged_transcript.json contains scene_id="apartment" on all words
- Idempotent re-run confirmed: second run with --scene apartment printed "Skipping apartment (transcript exists)" — no Whisper re-run

## Task Commits

Each task was committed atomically:

1. **Task 1: Add main() CLI orchestration to 0201_transcribe_nested.py** - `b7ccf03` (feat)
2. **Task 2: Validate on reference project — dry-run + single scene live** - human-verify checkpoint, no code changes

**Plan metadata:** (this docs commit)

## Files Created/Modified

- `scripts/02_transcribe/0201_transcribe_nested/0201_transcribe_nested.py` - Added main(), print_dry_run_summary(), argparse CLI wired to all core functions

## Decisions Made

- merge_transcripts() is called after every run (even single-scene) so merged output stays current without requiring all scenes to complete first
- apartment scene chosen as live validation target because it is the smallest scene with known-good TX audio from Phase 2 validation
- Human checkpoint used after CLI implementation to confirm Whisper + Pyannote produce correct per-scene transcript on real hardware before proceeding

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 3 complete: nested transcription pipeline fully functional, validated on reference project
- 0201_transcribe_nested.py is the CLI entry point for all scene transcription in nested projects
- Phase 4 (brief) can begin: merged_transcript.json structure (version, scenes, words with scene_id + local timecodes) is the input format for brief generation
- Remaining 6 scenes on YTCR01_Arty_Dzis can be transcribed with: `python 0201_transcribe_nested.py --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis" -n 2 -y`

---
*Phase: 03-transcribe*
*Completed: 2026-03-17*
