---
phase: 1
slug: organize
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Python stdlib) |
| **Config file** | `scripts/01_prepare/0100_organize/tests/` — Wave 0 creates |
| **Quick run command** | `python -m pytest scripts/01_prepare/0100_organize/tests/ -x -q` |
| **Full suite command** | `python -m pytest scripts/01_prepare/0100_organize/tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest scripts/01_prepare/0100_organize/tests/ -x -q`
- **After every plan wave:** Run `python -m pytest scripts/01_prepare/0100_organize/tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 0 | ORG-01 | unit | `pytest tests/test_organize.py::test_detect_nested_project -x` | ❌ W0 | ⬜ pending |
| 1-01-02 | 01 | 0 | ORG-01 | unit | `pytest tests/test_organize.py::test_detect_flat_project -x` | ❌ W0 | ⬜ pending |
| 1-01-03 | 01 | 1 | ORG-02 | unit | `pytest tests/test_organize.py::test_scene_clips_moved -x` | ❌ W0 | ⬜ pending |
| 1-01-04 | 01 | 1 | ORG-02 | unit | `pytest tests/test_organize.py::test_gopro_subfolder_preserved -x` | ❌ W0 | ⬜ pending |
| 1-01-05 | 01 | 1 | ORG-03 | unit | `pytest tests/test_organize.py::test_dji_wavs_moved_flat -x` | ❌ W0 | ⬜ pending |
| 1-01-06 | 01 | 1 | ORG-04 | unit | `pytest tests/test_organize.py::test_xml_sidecar_with_scene -x` | ❌ W0 | ⬜ pending |
| 1-01-07 | 01 | 1 | ORG-05 | unit | `pytest tests/test_organize.py::test_no_xml_no_error -x` | ❌ W0 | ⬜ pending |
| 1-01-08 | 01 | 1 | ORG-06 | unit | `pytest tests/test_organize.py::test_v3_skeleton_created -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/01_prepare/0100_organize/tests/__init__.py` — package marker
- [ ] `scripts/01_prepare/0100_organize/tests/test_organize.py` — stubs for all ORG-01..06 tests using `tmp_path` fixtures
- [ ] `scripts/01_prepare/0100_organize/tests/conftest.py` — shared fixtures (mock project tree, TX folder setup)

*pytest is stdlib-compatible; no additional install needed if Python 3.11+ venv has pytest.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Reference project YTCR_1_Arty_Dzis dry-run output | ORG-01–06 | Live volume required | Run `python 0100_organize.py --project "/Volumes/RYA T7 Black/YTCR_1_Arty_Dzis" --dry-run` and verify printed plan |
| v3.0 skeleton matches YTAI_Folder_Templates | ORG-06 | Template comparison | Inspect created dirs against `YTAI_Folder_Templates/Type2_Production/` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
