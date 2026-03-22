# 0105 Multiwindow DJI Sync — Specification

**Version:** 1.0.0
**Status:** Production
**Replaces:** 0103_sync_dji_audio (metadata-based), 0104_sync_audio_nested (single-window correlation)

## Overview

Synchronizes DJI wireless microphone recordings with camera video clips using
multi-window cross-correlation with consistency scoring. Handles DJI Mic 2
auto-split at ~30 minutes (spanning across 2–3 files).

## Problem

DJI Mic 2 records mono WAV (24-bit, 48kHz) with auto-split every ~30 min.
Previous approaches failed when:

| Approach | Failure mode |
|----------|-------------|
| **0103** (metadata timestamps) | Camera and DJI clocks out of sync (observed: ~1 hour drift on indoor scenes) |
| **0104** (single-window correlation) | `CONFIDENCE_THRESHOLD=50` too high for indoor acoustics; `search_margin=120s` too small for spanning clips |

## Algorithm: Multi-window consistency scoring

### Step 1: Load DJI audio

All DJI WAV files loaded into memory at 8kHz mono (~57 MB per 30-min file).
Grouped by TX prefix (TX01, TX02).

### Step 2: Build candidates

For each TX group, build three types of candidates:

| Type | Description | Example |
|------|-------------|---------|
| **Single** | Individual DJI file | MIC029 (30 min) |
| **Pair** | Two consecutive same-date files concatenated | MIC029+MIC030 (60 min) |
| **Triple** | Three consecutive same-date files concatenated | MIC033+MIC034+MIC035 (87 min) |

Same-date filter: parse `YYYYMMDD` from filename (e.g. `TX02_MIC029_20260228_121017_orig.wav` → `20260228`).

### Step 3: Multi-window scoring

Camera audio is divided into overlapping 60-second windows every 30 seconds:

```
Window 0:   cam[0:60s]    → correlate → offset_0 in DJI candidate
Window 1:   cam[30:90s]   → correlate → offset_1 in DJI candidate
Window 2:   cam[60:120s]  → correlate → offset_2 in DJI candidate
...
Window 25:  cam[720:780s] → correlate → offset_25 in DJI candidate
```

For each window, `scipy.signal.fftconvolve` finds the best alignment position.

**Adjusted offset**: `adjusted_i = raw_offset_i - window_start_i`

For a true match, all adjusted offsets converge to the same value (the global offset
where the camera audio starts within the DJI recording).

**Metrics:**
- `consistency%` = percentage of windows where `|adjusted - median| < 2.0 seconds`
- `mean_confidence` = average peak/mean ratio of consistent windows
- `score = consistency% × mean_confidence / 100`

### Why consistency works

| Candidate | Consistency | Reason |
|-----------|-------------|--------|
| MIC029 (single) | 0% | First 5:33 of camera in MIC029, remaining 8:01 not → offsets scatter |
| MIC030 (single) | 62% | Most of camera in MIC030, but start is missing |
| **MIC029+MIC030 (pair)** | **100%** | Full 13:34 covered → all 26 windows agree |

### Short clips (< 90 seconds)

For clips shorter than 90 seconds, multi-window gives too few data points.
Fallback: single full-length cross-correlation, score = confidence directly.
Works reliably for outdoor scenes.

### Step 4: EXTEND

After selecting winner, check: `offset + clip_duration > candidate_duration`?

If yes — the clip extends past the candidate's end. Automatically append the
next consecutive DJI file(s) of the same date.

Example: C5402 (2:36) matched in pair MIC034+MIC035 at offset 57:30.
Remaining in MIC035: 2:30. Clip needs 2:36. Shortage: 6s.
→ EXTEND with MIC036 → full coverage.

### Step 5: Trim + Verify

**Trim**: FFmpeg `atrim` per contributing file → `concat` → `atrim` to exact
video duration. Output: PCM 24-bit 48kHz WAV (native DJI format).

**Verify**: Cross-correlate first 60s of output vs camera audio. Residual < 0.01s
indicates perfect alignment.

## Output

### File naming

```
{clip_id}_{TX}_{MIC1}[_{MIC2}[_{MIC3}]].wav
```

Examples:
- `C5237_TX02_MIC029_MIC030.wav` — spanning two files
- `C5403_TX02_MIC036.wav` — single file
- `C5402_TX02_MIC035_MIC036.wav` — extended with next file

### Directory structure

```
01_Media/Source/Audio/
├── 01_apartment/
│   └── C5237_TX02_MIC029_MIC030.wav
└── 02_outdoor/
    ├── C5402_TX02_MIC035_MIC036.wav
    └── C5403_TX02_MIC036.wav
```

## CLI

```bash
python 0105_multiwindow_sync_dji.py --project "/path/to/project"
python 0105_multiwindow_sync_dji.py --project "/path/to/project" --overwrite
python 0105_multiwindow_sync_dji.py --project "/path/to/project" --dry-run
```

| Flag | Description |
|------|-------------|
| `--project PATH` | Project root (required) |
| `--overwrite` | Re-sync even if output files exist |
| `--dry-run` | Score candidates only, no trimming |

## Project structure support

Detects both raw and organized layouts:

| Layout | Video location | DJI location |
|--------|---------------|--------------|
| **Raw** | `project/{scene}/*.MP4` | `project/DJI_Audio/` |
| **Organized** (v3.0) | `project/01_Media/Source/Video/{scene}/` | `project/99_Pipeline/DJI_Audio/` |

## Pipeline integration

`run_pipeline.py` calls this script as the `sync_dji` stage:

```python
# scripts/run_pipeline.py line 143
"script": "01_prepare/0105_multiwindow_sync_dji/0105_multiwindow_sync_dji.py",
```

Pipeline passes: `--project`, optionally `--overwrite`.

## Dependencies

- Python 3.10+
- numpy
- scipy (fftconvolve)
- ffmpeg / ffprobe

Imports from existing scripts via `importlib.util`:
- `extract_mono_8k`, `get_video_clip_info` from `0103_sync_dji_audio.py`
- `verify_full` from `fix_dji_sync.py`

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `SR` | 8000 | Sample rate for correlation (8kHz mono) |
| `WINDOW_SEC` | 60.0 | Correlation window length |
| `STEP_SEC` | 30.0 | Window step (50% overlap) |
| `CONSISTENCY_TOL` | 2.0 | Max deviation from median (seconds) |
| `SHORT_CLIP_THRESHOLD` | 90.0 | Below this, use single correlation |

## Performance

| Project | Clips | DJI files | Time |
|---------|-------|-----------|------|
| YTXX01 (3 clips, 17 min total) | 3 | 16 (TX01×3, TX02×13) | ~12 min |

Memory: ~900 MB for 16 DJI files at 8kHz.

Bottleneck: FFT convolution of 60s window against 60-min concatenated pair (~28M samples).

## Changelog

### v1.0.0 (2026-03-22)
- Initial release
- Multi-window consistency scoring
- Spanning pairs + triples
- EXTEND for boundary clips
- Rich terminal output with progress/ETA
- Pipeline integration (replaces 0103 in run_pipeline.py)
