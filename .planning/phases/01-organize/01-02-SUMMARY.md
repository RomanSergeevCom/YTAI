---
phase: 01-organize
plan: 02
subsystem: organize
tags: [python, shutil, pathlib, tdd, pytest, file-move, media-organization]

# Dependency graph
requires:
  - phase: 01-organize plan 01
    provides: is_nested_project, detect_scenes, create_v3_skeleton, organize() skeleton
provides:
  - move_scene_clips: video clips organized into Source/Video/{scene}/ with GoPro subfolder preservation
  - move_dji_wavs: DJI WAVs moved flat into 99_Pipeline/DJI_Audio/
  - move_xml_sidecars: Sony XML sidecars placed at Transcription/per_clip/{scene}/{clip}/
  - build_clip_scene_map: clip stem to scene name mapping
  - xml_to_clip_id: progressive prefix matching for Sony XML naming (C5089M01 -> C5089)
  - complete 0100_organize.py with all ORG-02, ORG-03, ORG-04 requirements
affects: [02-transcribe, 01-03]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TDD red-green: write failing tests first, then implement"
    - "clip.relative_to(scene_dir) for subfolder-preserving moves"
    - "Progressive prefix matching for Sony XML to clip ID resolution"
    - "Collect video_stems from both source scene dirs AND destination video_dir (after move)"
    - "rmdir() for safe cleanup of empty dirs (only removes empty)"

key-files:
  created: []
  modified:
    - scripts/01_prepare/0100_organize/0100_organize.py
    - scripts/01_prepare/0100_organize/tests/test_organize.py

key-decisions:
  - "Scene for XML determined by where XML file is found (source scene dir), not where the video clip lives"
  - "video_stems must be collected from destination video_dir too, since move_scene_clips runs before move_xml_sidecars"
  - "Fallback to flat per_clip/{clip}/ for XMLs with no video stem match (backward compat)"

patterns-established:
  - "clip.relative_to(scene_dir): preserves nested subfolder structure (GoPro 100GOPRO/) inside destination"
  - "xml_to_clip_id: progressively shorter prefix matching handles Sony suffix notation (M01, M02...)"

requirements-completed: [ORG-02, ORG-03, ORG-04]

# Metrics
duration: 15min
completed: 2026-03-17
---

# Phase 01 Plan 02: File Move Logic Summary

**Complete organize script: video clips per scene with GoPro preservation, DJI WAVs flat, XML sidecars with scene layer — all 10 tests passing**

## Performance

- **Duration:** 15 min
- **Started:** 2026-03-16T22:19:22Z
- **Completed:** 2026-03-16T22:34:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `move_scene_clips()` moves MP4/MOV clips from each scene dir into `Source/Video/{scene}/` using `clip.relative_to(scene_dir)` to preserve GoPro subfolders (100GOPRO/)
- `move_dji_wavs()` collects WAVs matching DJI_RAW_RE from all TX dirs and moves them flat into `99_Pipeline/DJI_Audio/`
- `move_xml_sidecars()` places Sony XML sidecars at `Transcription/per_clip/{scene}/{clip}/` with scene determined from the XML file's source location
- `xml_to_clip_id()` resolves Sony suffix notation (C5089M01 → C5089) via progressive prefix matching against known video stems
- Empty TX dirs and scene dirs cleaned up after moves via safe `rmdir()`
- 10/10 tests pass; script idempotent (skips already-moved files)

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: failing tests for video/DJI moves** - `b80ba59` (test)
2. **Task 1 GREEN: implement move_scene_clips and move_dji_wavs** - `15d2ecc` (feat)
3. **Task 2 GREEN: implement XML sidecar moves with scene layer** - `e430889` (feat)

_Note: Task 2 RED was already present (test body was already written in the same commit as Task 1 RED)_

## Files Created/Modified
- `scripts/01_prepare/0100_organize/0100_organize.py` — Added move_scene_clips, move_dji_wavs, build_clip_scene_map, xml_to_clip_id, move_xml_sidecars; updated organize() to call all move functions
- `scripts/01_prepare/0100_organize/tests/test_organize.py` — Filled in test bodies for TestVideoMove, TestDjiWavMove, TestXmlSidecar

## Decisions Made
- **Scene for XML = source scene dir:** XML files live in scene folders (e.g. `volleyball/C5089M01.XML`). The destination scene is determined by where the XML was found, not which scene owns the matched clip ID. This correctly handles XMLs that cross scene boundaries.
- **Two-pass video_stems collection:** After `move_scene_clips()` runs, scene dirs are emptied. `move_xml_sidecars()` must scan both the (now-empty) scene dirs AND the destination `01_Media/Source/Video/` dir to build the full video stems set. This order-dependency was discovered during GREEN implementation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed video_stems collection after scene clips already moved**
- **Found during:** Task 2 (move_xml_sidecars implementation)
- **Issue:** `move_xml_sidecars()` built `video_stems` by scanning scene dirs, but by the time it runs, `move_scene_clips()` has already moved all video files out of those dirs — so `video_stems` was empty and xml_to_clip_id returned None for all XMLs
- **Fix:** Added second scan of `project / "01_Media" / "Source" / "Video"` to collect stems from already-moved clips
- **Files modified:** scripts/01_prepare/0100_organize/0100_organize.py
- **Verification:** 10/10 tests pass; debug trace confirmed correct placement
- **Committed in:** e430889 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential correctness fix discovered during implementation. No scope creep.

## Issues Encountered
- pytest not installed in environment — installed via `pip3 install pytest` (Rule 3 auto-fix, no commit needed)

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `0100_organize.py --project PATH` fully arranges a nested project into v3.0 structure
- All ORG-02, ORG-03, ORG-04 requirements implemented and tested
- Ready for Plan 03 (if any) or Phase 02 (Audio Sync)
- Phase 02 concern: cross-correlation across 325 clips is highest-risk — consider validating on single scene first

## Self-Check: PASSED

- FOUND: scripts/01_prepare/0100_organize/0100_organize.py
- FOUND: scripts/01_prepare/0100_organize/tests/test_organize.py
- FOUND: .planning/phases/01-organize/01-02-SUMMARY.md
- FOUND: b80ba59 (test: failing tests)
- FOUND: 15d2ecc (feat: move_scene_clips, move_dji_wavs)
- FOUND: e430889 (feat: move_xml_sidecars)
- 10/10 tests pass

---
*Phase: 01-organize*
*Completed: 2026-03-17*
