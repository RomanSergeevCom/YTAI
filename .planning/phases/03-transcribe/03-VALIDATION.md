---
phase: 3
slug: transcribe
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-17
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | scripts/02_transcribe/020201_transcribe_nested/ (Wave 0 creates) |
| **Quick run command** | `python -m pytest scripts/02_transcribe/020201_transcribe_nested/tests/ -x -q` |
| **Full suite command** | `python -m pytest scripts/02_transcribe/020201_transcribe_nested/tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest scripts/02_transcribe/020201_transcribe_nested/tests/ -x -q`
- **After every plan wave:** Run `python -m pytest scripts/02_transcribe/020201_transcribe_nested/tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | TRN-01 | unit | `pytest tests/test_transcribe_nested.py::test_detect_scenes -x -q` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | TRN-01 | unit | `pytest tests/test_transcribe_nested.py::test_find_audio_input -x -q` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 1 | TRN-01 | unit | `pytest tests/test_transcribe_nested.py::test_transcribe_scene -x -q` | ❌ W0 | ⬜ pending |
| 3-02-01 | 02 | 1 | TRN-02 | unit | `pytest tests/test_merge_transcript.py::test_merge_scenes -x -q` | ❌ W0 | ⬜ pending |
| 3-02-02 | 02 | 1 | TRN-02 | unit | `pytest tests/test_merge_transcript.py::test_scene_id_field -x -q` | ❌ W0 | ⬜ pending |
| 3-02-03 | 02 | 1 | TRN-02 | unit | `pytest tests/test_merge_transcript.py::test_local_timecode -x -q` | ❌ W0 | ⬜ pending |
| 3-03-01 | 03 | 2 | TRN-03 | integration | `pytest tests/test_integration.py::test_idempotent_rerun -x -q` | ❌ W0 | ⬜ pending |
| 3-03-02 | 03 | 2 | TRN-01 | manual | human verification on reference project | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_transcribe_nested.py` — stubs for TRN-01 (scene detection, audio input selection, per-scene transcription routing)
- [ ] `tests/test_merge_transcript.py` — stubs for TRN-02 (merge logic, scene_id field, local timecode)
- [ ] `tests/test_integration.py` — stubs for TRN-03 (idempotent rerun on single scene)
- [ ] `tests/conftest.py` — shared fixtures (mock project structure, sample ingest.json)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| All 7 scenes produce transcript JSON on reference project | TRN-01 | Requires real project on external drive; Whisper runtime | Run `python transcribe_nested.py --project /Volumes/.../YTCR01_Arty_Dzis --dry-run`, then live on one scene |
| merged_transcript.json word entries have correct scene timecodes | TRN-02 | Requires real transcript output | Inspect merged output for `scene_id` and local timecode fields |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
