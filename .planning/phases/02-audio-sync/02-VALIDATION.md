---
phase: 2
slug: audio-sync
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-03-17
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 (`python3 -m pytest`) |
| **Config file** | `scripts/01_prepare/0104_sync_audio_nested/tests/` — Wave 0 creates |
| **Quick run command** | `python3 -m pytest scripts/01_prepare/0104_sync_audio_nested/tests/ -x -q` |
| **Full suite command** | `python3 -m pytest scripts/01_prepare/ -x -q` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python3 -m pytest scripts/01_prepare/0104_sync_audio_nested/tests/ -x -q`
- **After every plan wave:** Run `python3 -m pytest scripts/01_prepare/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green + manual verification on `apartment` scene
- **Max feedback latency:** ~10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 0 | AUD-01 | unit | `pytest tests/test_0104.py::test_extract_clip_audio_path -x` | W0 | pending |
| 2-01-02 | 01 | 0 | AUD-02 | unit | `pytest tests/test_0104.py::test_build_scene_concat -x` | W0 | pending |
| 2-01-03 | 01 | 0 | AUD-03 | unit | `pytest tests/test_0104.py::test_find_best_tx_candidate -x` | W0 | pending |
| 2-01-04 | 01 | 0 | AUD-04 | unit | `pytest tests/test_0104.py::test_trim_tx_to_clip -x` | W0 | pending |
| 2-01-05 | 01 | 0 | AUD-05 | unit | `pytest tests/test_0104.py::test_trim_tx_to_clip -x` | W0 | pending |
| 2-01-06 | 01 | 1 | AUD-06 | manual | manual on YTCR_1_Arty_Dzis apartment scene | manual | pending |
| 2-01-07 | 01 | 0 | AUD-07 | unit | `pytest tests/test_0104.py::test_generate_ingest_json -x` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `scripts/01_prepare/0104_sync_audio_nested/__init__.py` — module init
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/__init__.py` — test package init
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/conftest.py` — fixtures with synthetic WAV data (numpy sine waves at 8kHz, fake nested project tree)
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py` — stubs for AUD-01 through AUD-07 tests

*pytest 9.0.2 confirmed in `.venv_transcribe`; no additional install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Sync delta <=1F per clip on reference project | AUD-06 | Live volume + real audio correlation required | Run `python 0104_sync_audio_nested.py --project "/Volumes/RYA T7 Black/YTCR_1_Arty_Dzis" --scene apartment` and verify sync report shows <=1F for all 40 clips |
| Correct TX WAV selected when overlapping | AUD-03 | Requires real TX WAVs crossing scene boundaries | Inspect sync report — verify TX01 candidate path differs across clips if TX01_MIC001 ends mid-scene |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 10s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
