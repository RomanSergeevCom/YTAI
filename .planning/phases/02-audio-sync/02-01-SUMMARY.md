---
phase: 02-audio-sync
plan: 01
subsystem: audio
tags: [scipy, numpy, fftconvolve, cross-correlation, ffmpeg, tdd, pytest]

# Dependency graph
requires:
  - phase: 01-organize
    provides: Organized project structure with scene subdirs and 99_Pipeline/DJI_Audio/

provides:
  - TDD test scaffold: 9 unit tests with synthetic sine-wave fixtures
  - detect_scenes: scene discovery without numeric-prefix requirement
  - extract_clip_audio: per-clip camera audio extraction at 48kHz stereo PCM
  - build_scene_concat: ffmpeg concat demuxer for scene-level WAV creation
  - preload_tx_cache: loads TX WAVs at 8kHz mono into path-keyed dict
  - find_best_tx_candidate: fftconvolve cross-correlation picks best TX WAV
  - trim_tx_to_clip: ffmpeg trim TX to clip duration at sync offset
  - residual_to_frames: converts residual seconds to frame delta at clip FPS
  - Importable module 0104_sync_audio_nested.py for Plan 02 orchestration

affects:
  - 02-02 (CLI orchestration will import these functions)

# Tech tracking
tech-stack:
  added:
    - scipy.signal.fftconvolve (cross-correlation engine)
    - importlib.util.spec_from_file_location (digit-prefixed module loading)
  patterns:
    - TDD with synthetic audio: sine-wave fixtures embedded in noise arrays
    - Module fixture (scope="module") defers import to test setup for RED phase
    - Normalized cross-correlation: zero-mean, unit-variance both signals before fftconvolve

key-files:
  created:
    - scripts/01_prepare/0104_sync_audio_nested/__init__.py
    - scripts/01_prepare/0104_sync_audio_nested/tests/__init__.py
    - scripts/01_prepare/0104_sync_audio_nested/tests/conftest.py
    - scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py
    - scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py
  modified: []

key-decisions:
  - "Module fixture (scope=module) defers import to test setup so --collect-only works in RED phase"
  - "Scene detection by video-file presence (not prefix regex) — consistent with 01-01 decision"
  - "fftconvolve valid region: corr[len(cam)-1 : len(cam)-1 + len(tx)-len(cam)+1] isolates fully-overlapping positions"
  - "preload_tx_cache uses soundfile for duration, falls back to 1800s if unavailable"

patterns-established:
  - "Pattern 1: Defer importlib module load to pytest fixture (scope=module) for TDD RED compatibility"
  - "Pattern 2: Synthetic audio = 440Hz sine (SNR ~100x over 0.01-amplitude noise) gives reliable correlation confidence > 3.0"
  - "Pattern 3: Cross-correlation valid_region slicing avoids edge artifacts at boundaries"

requirements-completed: [AUD-01, AUD-02, AUD-03, AUD-04, AUD-05, AUD-06]

# Metrics
duration: 8min
completed: 2026-03-17
---

# Phase 2 Plan 1: Audio Sync Core Functions Summary

**fftconvolve cross-correlation core for nested audio sync: 7 functions (detect_scenes through residual_to_frames) with 9 passing TDD unit tests using synthetic 440Hz sine-wave fixtures**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-16T23:12:44Z
- **Completed:** 2026-03-16T23:20:55Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 5

## Accomplishments

- Created 9-test TDD scaffold with synthetic sine-wave fixtures in conftest.py, all tests RED before implementation
- Implemented 7 core functions: detect_scenes, get_scene_clips, extract_clip_audio, build_scene_concat, preload_tx_cache, find_best_tx_candidate, trim_tx_to_clip, residual_to_frames
- Cross-correlation correctly identifies a 440Hz sine embedded at 10.0s within a 30-second noise TX array with confidence > 3.0 and offset within 0.05s — no real audio files required

## Task Commits

Each task was committed atomically:

1. **Task 1: Test scaffold + synthetic fixtures (RED)** - `4794242` (test)
2. **Task 2: Implement core functions (GREEN)** - `5561626` (feat)

_Note: TDD tasks — RED commit then GREEN commit_

## Files Created/Modified

- `scripts/01_prepare/0104_sync_audio_nested/__init__.py` - Package init (empty)
- `scripts/01_prepare/0104_sync_audio_nested/tests/__init__.py` - Tests package init (empty)
- `scripts/01_prepare/0104_sync_audio_nested/tests/conftest.py` - Synthetic audio fixtures (fake_nested_organized, synthetic_cam_audio, synthetic_tx_with_cam_embedded, synthetic_tx_noise_only)
- `scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py` - 9 unit tests covering AUD-01 through AUD-06 + preload_tx_cache
- `scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py` - Core implementation (336 lines): all 7 functions + imports from 0103_sync_dji_audio via importlib.util

## Decisions Made

- **Module fixture for TDD RED compatibility:** Using `@pytest.fixture(scope="module")` to defer the importlib module load means `--collect-only` succeeds at 0 exit code even when the implementation file doesn't yet exist. The error appears at test setup time, not collection time.
- **Scene detection without prefix regex:** Consistent with the 01-01 decision — `detect_scenes` discovers any subdirectory containing `.MP4` or `.MOV` files, regardless of whether the name starts with `\d{2}_`.
- **fftconvolve valid_region slicing:** The correlation output spans `len(cam)+len(tx)-1` samples. Slicing `corr[len(cam)-1 : len(cam)-1+len(tx)-len(cam)+1]` isolates positions where the camera window is fully inside the TX array, avoiding boundary artifacts that would inflate confidence.

## Deviations from Plan

None — plan executed exactly as written. The module fixture approach for TDD RED compatibility was anticipated by the plan's `--collect-only` acceptance criterion.

## Issues Encountered

None — synthetic 440Hz sine with 0.01-amplitude noise background produced reliable correlation confidence well above the 3.0 threshold on both test cases.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All 7 core functions are importable and tested; Plan 02 can import them via importlib.util
- The cross-correlation approach (Pattern 3 from 02-RESEARCH.md) is validated against synthetic signals
- No modifications to 0102 or 0103 scripts (constraint satisfied)
- Concern: real TX WAVs may have varying SNR; the confidence threshold 3.0 should be validated on actual project data before running on all 325 clips

---
*Phase: 02-audio-sync*
*Completed: 2026-03-17*

## Self-Check: PASSED

- FOUND: scripts/01_prepare/0104_sync_audio_nested/__init__.py
- FOUND: scripts/01_prepare/0104_sync_audio_nested/tests/__init__.py
- FOUND: scripts/01_prepare/0104_sync_audio_nested/tests/conftest.py
- FOUND: scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py
- FOUND: scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py
- FOUND: .planning/phases/02-audio-sync/02-01-SUMMARY.md
- FOUND: commit 4794242 (test RED)
- FOUND: commit 5561626 (feat GREEN)
