---
phase: 02-audio-sync
plan: 02
subsystem: audio
tags: [scipy, numpy, fftconvolve, cross-correlation, ffmpeg, argparse, json, tdd, pytest, importlib]

# Dependency graph
requires:
  - phase: 02-audio-sync
    plan: 01
    provides: Core functions (detect_scenes through residual_to_frames) with TDD scaffold

provides:
  - generate_ingest_json: per-scene ingest.json with A1=camera_embed, A2=TX01_SYNC, A3=TX02_SYNC
  - process_clip: orchestrates one clip (extract, correlate, trim TX WAVs, verify with verify_full)
  - process_scene: orchestrates all clips in scene + concat + ingest.json
  - main(): CLI with --project, --scene, --dry-run
  - verify_full integration: real sync delta in frames (not hardcoded)
  - Complete runnable script 0104_sync_audio_nested.py (12 functions, 430+ lines)

affects:
  - 02-03 (validation plan will test this CLI against real project data)
  - 05-editing (ingest.json consumed by UXP timeline builder)

# Tech tracking
tech-stack:
  added:
    - argparse (CLI argument parsing)
    - json (ingest.json serialization)
    - importlib.util.spec_from_file_location (loading fix_dji_sync.py for verify_full)
  patterns:
    - verify_full called after trim_tx_to_clip to compute real sync residual (not correlation offset)
    - LOW_CONF fallback: clips below CONFIDENCE_THRESHOLD=3.0 get null paths in ingest.json (not failures)
    - Ingest.json written even in dry_run (metadata only, no large files)

key-files:
  created: []
  modified:
    - scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py
    - scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py

key-decisions:
  - "verify_full returns float|None (residual_sec), not dict — adapted process_clip to use return value directly with clip_duration arg"
  - "Ingest.json written in dry_run mode (small metadata file, useful for inspection without triggering ffmpeg)"
  - "process_clip uses get_video_clip_info['duration'] key (not 'duration_sec') matching 0103 convention"

patterns-established:
  - "Pattern 4: verify_full(clip_path, out_tx, clip_duration) — 3-arg call; return value is float|None residual_sec"
  - "Pattern 5: LOW_CONF clips produce null path in ingest.json A2/A3 tracks, never raise exceptions"

requirements-completed: [AUD-01, AUD-02, AUD-03, AUD-04, AUD-05, AUD-06, AUD-07]

# Metrics
duration: 3min
completed: 2026-03-17
---

# Phase 2 Plan 2: Audio Sync Orchestration Summary

**CLI script 0104_sync_audio_nested.py wiring cross-correlation core into process_clip/process_scene/main with verify_full sync delta, generate_ingest_json writing A1/A2/A3 track structure per scene**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-17T09:43:14Z
- **Completed:** 2026-03-17T09:46:20Z
- **Tasks:** 2 (TDD Task 1 + straight Task 2)
- **Files modified:** 2

## Accomplishments

- Implemented generate_ingest_json() writing Setup/{scene}_ingest.json with camera_embed/TX01_SYNC/TX02_SYNC tracks and LOW_CONF fallback
- Wired process_clip() with full pipeline: extract audio, cross-correlate both TX caches, trim TX WAVs, verify with verify_full() for real frame delta
- Added main() CLI with argparse (--project, --scene, --dry-run) and scene/TX prefix auto-detection
- All 12 unit tests passing: 9 prior + 2 ingest.json tests + 1 CLI args test

## Task Commits

Each task was committed atomically:

1. **Task 1: RED tests for generate_ingest_json** - `e2b46a3` (test)
2. **Task 1: GREEN — implement generate_ingest_json** - `0f652f9` (feat)
3. **Task 2: process_clip, process_scene, main() orchestration** - `3ad5614` (feat)

_Note: Task 1 used TDD — RED commit then GREEN commit_

## Files Created/Modified

- `scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py` - Complete CLI script (430+ lines, 12 functions): added generate_ingest_json, process_clip, process_scene, main(), verify_full import, argparse, json, sys imports
- `scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py` - Added test_generate_ingest_json, test_generate_ingest_json_low_conf, test_cli_args_parse (12 total tests)

## Decisions Made

- **verify_full interface mismatch (auto-fixed):** The plan spec said `verify_full` returns `{"residual_sec": ..., "confidence": ...}` but the actual `fix_dji_sync.py::verify_full` returns `float | None`. Adapted `process_clip` to use the return value directly as `residual_sec` and added the required `clip_duration` positional argument.
- **Ingest.json in dry_run:** Writing the ingest.json even in dry_run mode — it's a small metadata file that lets the user inspect what would be synced without running ffmpeg. This is more useful than skipping it entirely.
- **fps from get_video_clip_info:** The 0103 module's `get_video_clip_info` doesn't return `fps` directly — only `clip_id`, `path`, `duration`, `creation_utc`. Added `float(info.get("fps", 25.0))` with 25.0 fallback matching Sony FX3 default.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] verify_full returns float|None, not dict**
- **Found during:** Task 2 (process_clip implementation)
- **Issue:** Plan's code used `residual["residual_sec"]` but `fix_dji_sync.py::verify_full` returns a plain `float | None` value (residual_sec directly). Also plan omitted the required `clip_duration` positional argument.
- **Fix:** Changed `residual["residual_sec"]` to `residual_sec` (direct return value); added `clip_duration` as 3rd arg to `verify_full(clip_path, out_tx01, clip_duration)`
- **Files modified:** `scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py`
- **Verification:** Module imports successfully; `--help` works; all 12 tests pass
- **Committed in:** 3ad5614 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - interface mismatch between plan spec and actual verify_full signature)
**Impact on plan:** Auto-fix necessary for correct operation. No scope creep.

## Issues Encountered

None — the verify_full interface mismatch was caught during implementation and fixed inline under deviation Rule 1.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- Complete CLI script ready for validation against real project data
- Run `python3 0104_sync_audio_nested.py --project /path/to/project --scene apartment --dry-run` to inspect without writing
- Concern carried from Plan 01: real TX WAVs may have varying SNR; validate confidence threshold 3.0 on a single scene before full 325-clip run
- ingest.json output format is the contract consumed by Phase 5 (UXP timeline builder)

---
*Phase: 02-audio-sync*
*Completed: 2026-03-17*

## Self-Check: PASSED

- FOUND: scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py
- FOUND: scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py
- FOUND: .planning/phases/02-audio-sync/02-02-SUMMARY.md
- FOUND: commit e2b46a3 (test RED)
- FOUND: commit 0f652f9 (feat GREEN)
- FOUND: commit 3ad5614 (feat orchestration)
