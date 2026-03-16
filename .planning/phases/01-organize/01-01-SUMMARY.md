---
phase: 01-organize
plan: 01
subsystem: organize
tags: [python, pytest, pathlib, organize, nested-project, scene-detection]

# Dependency graph
requires: []
provides:
  - is_nested_project() function detecting TX01/TX02/TX02_2/ folders at project root
  - detect_scenes() function finding bare-name scene folders containing video files
  - create_v3_skeleton() function deep-merging Type2_Production template into project
  - organize() orchestrator function (file moves stubbed for Plan 02)
  - Full pytest test suite with 10 tests (6 active, 4 stubs for Plan 02)
affects: [01-02, 02-transcribe, 05-editing]

# Tech tracking
tech-stack:
  added: [pytest]
  patterns: [importlib.util for modules with digit-prefixed names, tmp_path fixtures for fake project trees]

key-files:
  created:
    - scripts/01_prepare/0100_organize/0100_organize.py
    - scripts/01_prepare/0100_organize/__init__.py
    - scripts/01_prepare/0100_organize/tests/__init__.py
    - scripts/01_prepare/0100_organize/tests/conftest.py
    - scripts/01_prepare/0100_organize/tests/test_organize.py
  modified: []

key-decisions:
  - "Standalone script (not extension of run_pipeline.py) follows existing script-per-stage convention"
  - "TX folder presence (TX_FOLDER_RE=r'^TX\d+') is the nested-project trigger, not scene count"
  - "Scene detection: any non-system, non-managed, non-TX directory containing video files is a scene"
  - "importlib.util.spec_from_file_location used in tests because module name starts with digit"

patterns-established:
  - "Pattern 1: TX_FOLDER_RE = re.compile(r'^TX\d+', re.IGNORECASE) for all TX folder detection"
  - "Pattern 2: Scene detection by video-file presence (rglob), not by numeric prefix"
  - "Pattern 3: create_v3_skeleton replicates _deep_merge_template from run_pipeline.py"
  - "Pattern 4: 4 file-move test stubs left as pass for Plan 02 to fill in"

requirements-completed: [ORG-01, ORG-05, ORG-06]

# Metrics
duration: 3min
completed: 2026-03-16
---

# Phase 1 Plan 01: Organize — Detection and Skeleton Summary

**Standalone 0100_organize.py with TX-based nested detection, bare-name scene detection, and v3.0 folder skeleton creation from Type2_Production template**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-16T22:14:24Z
- **Completed:** 2026-03-16T22:16:59Z
- **Tasks:** 2 of 2
- **Files modified:** 5 created

## Accomplishments

- Created test scaffolding with realistic fake_nested_project (TX01/TX02/TX02_2 + 3 scenes + GoPro subfolder) and fake_flat_project fixtures
- Implemented is_nested_project(), detect_scenes(), create_v3_skeleton(), organize() and main()
- All 10 tests pass: 6 active assertions for detection/skeleton, 4 stubs reserved for Plan 02 file moves

## Task Commits

Each task was committed atomically:

1. **Task 1: Test scaffolding with conftest fixtures and 10 ORG test stubs** - `d9d6514` (test)
2. **Task 2: Implement core detection functions and v3.0 skeleton creation** - `47a66c1` (feat)

**Plan metadata:** (docs commit follows)

_Note: Task 2 used TDD flow: RED (FileNotFoundError confirmed), GREEN (all 10 pass)_

## Files Created/Modified

- `scripts/01_prepare/0100_organize/0100_organize.py` - Standalone organize script with is_nested_project, detect_scenes, create_v3_skeleton, organize, main
- `scripts/01_prepare/0100_organize/__init__.py` - Package marker (empty)
- `scripts/01_prepare/0100_organize/tests/__init__.py` - Package marker (empty)
- `scripts/01_prepare/0100_organize/tests/conftest.py` - fake_nested_project and fake_flat_project fixtures using tmp_path
- `scripts/01_prepare/0100_organize/tests/test_organize.py` - 10 tests (6 active, 4 stubs)

## Decisions Made

- Used importlib.util.spec_from_file_location() for loading 0100_organize in tests, since Python cannot import modules with a digit-leading name via the standard import statement
- Installed pytest into .venv_ytai (was not present; stdlib-only claim in RESEARCH.md was incorrect for this venv)
- Left 4 test stubs (test_scene_clips_moved, test_gopro_subfolder_preserved, test_dji_wavs_moved_flat, test_xml_sidecar_with_scene) as `pass` per plan — Plan 02 fills in file-move logic

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed missing pytest into .venv_ytai**
- **Found during:** Task 1 verification
- **Issue:** pytest not installed in .venv_ytai; `python -m pytest` returned "No module named pytest"
- **Fix:** Ran `.venv_ytai/bin/pip install pytest` — was already present as a dependency (pytest 9.0.2 installed via transitive requirement), pip reported "Requirement already satisfied" on second attempt
- **Files modified:** None (venv install)
- **Verification:** `.venv_ytai/bin/python -m pytest --co` succeeds
- **Committed in:** Not committed (venv install, not source change)

---

**Total deviations:** 1 auto-fixed (1 blocking — missing tool)
**Impact on plan:** Required to run tests; no source code scope change.

## Issues Encountered

None beyond the pytest install noted above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 02 can immediately implement file-move logic (move_scene_clips, move_dji_wavs, move_xml_sidecars) against the 4 green stub tests
- organize() stub returns True and calls create_v3_skeleton() — Plan 02 adds shutil.move calls
- Template path resolution verified: `Path(__file__).resolve().parent.parent.parent.parent / "YTAI_Folder_Templates" / "Type2_Production"` points to correct location

---
*Phase: 01-organize*
*Completed: 2026-03-16*
