# Phase 2: Audio Sync - Research

**Researched:** 2026-03-17
**Domain:** Python audio signal processing — waveform cross-correlation, ffmpeg audio extraction, per-clip TX WAV sync
**Confidence:** HIGH (findings based on reading actual project code + verified library availability)

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| AUD-01 | Extract `{clip}_AUDIO.wav` at 48kHz stereo per clip under `Transcription/per_clip/{scene}/{clip}/` | 0102_extract_audio.py already does flat extraction; new script adds scene subfolder layer |
| AUD-02 | Concatenate per-scene clips into `{scene}_FULL_AUDIO.wav` as correlation reference | Scene grouping from AUD-01 output; ffmpeg concat demuxer pattern exists in 0102 |
| AUD-03 | Correlate all TX01 WAVs against each clip; select best candidate by waveform cross-correlation | fix_dji_sync.py `full_waveform_fine_offset()` is the exact function to reuse |
| AUD-04 | Trim winning TX01 WAV to clip duration → `01_Media/Source/Audio/{clip}_TX01.wav` | `build_ffmpeg_cmd()` in 0103 handles trim/pad/concat; same function reused |
| AUD-05 | Same for TX02 → `{clip}_TX02.wav` | Same as AUD-04, second pass over TX02 candidates |
| AUD-06 | Report sync delta in frames per clip; target ≤1F | `verify_full()` in fix_dji_sync gives residual_sec; convert to frames at clip FPS |
| AUD-07 | Per-scene ingest.json: A1=camera embed, A2=TX01_SYNC, A3=TX02_SYNC | ingest_json.py already reads `{clip}_TX*.wav` — needs scene-scoped ingest generation call |
</phase_requirements>

---

## Summary

Phase 2 is an extension of existing, working scripts — not a greenfield build. The critical insight is that `0103_sync_dji_audio.py` already handles flat projects using timestamp-based overlap detection followed by cross-correlation fine-tuning, and `fix_dji_sync.py` already implements per-clip full-waveform cross-correlation (`full_waveform_fine_offset` / `verify_full`). Phase 2 requires a new script (`0104_sync_audio_nested.py`) that replaces timestamp pre-filtering with pure waveform correlation for candidate selection, adds the scene-subfolder layer to output paths, and generates per-scene ingest.json.

The core challenge is scale: 325 clips × 16 TX WAVs × 2 TX channels = up to 10,400 candidate pairs. At 8kHz mono, each 30-minute TX WAV is ~14.4 MB in memory. Loading all 16 WAVs simultaneously = ~230 MB — feasible. The strategy is to downmix each TX WAV once to 8kHz float32 numpy array at startup, then run correlation against each clip's camera audio window. No librosa needed; scipy.signal.fftconvolve + numpy are already in `.venv_transcribe`.

**Primary recommendation:** Write `scripts/01_prepare/0104_sync_audio_nested/0104_sync_audio_nested.py` as a new standalone script that imports shared functions from `0103_sync_dji_audio.py` and `fix_dji_sync.py`. Do not modify the existing flat scripts.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy | 1.17.0 | `fftconvolve` for fast cross-correlation | Already in `.venv_transcribe`; used by existing scripts |
| numpy | 2.3.5 | Array ops, argmax, std | Already in `.venv_transcribe`; used by existing scripts |
| soundfile | 0.13.1 | Read WAV metadata/samples | Already in `.venv_transcribe` |
| ffmpeg (CLI) | system | Audio extraction, WAV trim/pad | Used by all existing scripts; installed via brew |
| ffprobe (CLI) | system | Clip duration/creation_time | Used by all existing scripts |

### Not Needed
| Library | Why Not |
|---------|---------|
| librosa | Not installed in `.venv_transcribe`; overkill for this use case; scipy+numpy is sufficient |
| pydub | Not installed; ffmpeg CLI is already the standard |

**Installation:** No new dependencies required. Use `.venv_transcribe` as-is.

**Venv to activate:**
```bash
source ~/YTAI/environment/.venv_transcribe/bin/activate
```

---

## Architecture Patterns

### Recommended Script Location
```
scripts/01_prepare/
├── 0104_sync_audio_nested/
│   ├── 0104_sync_audio_nested.py   ← new main script
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       └── test_0104.py
```

### Pattern 1: Import shared functions from existing modules

The existing code in `0103_sync_dji_audio.py` and `fix_dji_sync.py` is production-quality and handles all edge cases. Import instead of duplicating:

```python
# Same pattern as fix_dji_sync.py — import from digit-prefixed module
import sys
from pathlib import Path
import importlib.util

_SYNC_PATH = Path(__file__).resolve().parent.parent / "0103_sync_dji_audio" / "0103_sync_dji_audio.py"
spec = importlib.util.spec_from_file_location("_sync", _SYNC_PATH)
_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_sync)

extract_mono_8k = _sync.extract_mono_8k
build_ffmpeg_cmd = _sync.build_ffmpeg_cmd
get_video_clip_info = _sync.get_video_clip_info
tee_print = _sync.tee_print
# etc.
```

Note: `fix_dji_sync.py` uses `import_module("0103_sync_dji_audio")` with `sys.path.insert` — both approaches work. Use `importlib.util.spec_from_file_location` as it's more explicit (established pattern in 0100_organize tests).

### Pattern 2: Pre-load all TX WAVs at 8kHz into memory

At 8kHz mono float32, 30 minutes = 8000 × 1800 × 4 bytes ≈ 57 MB per WAV. 16 WAVs total = ~230 MB. Load once at startup, reuse for all 325 clips:

```python
# Load all TX WAVs once
tx_cache: dict[str, np.ndarray] = {}
for wav_path in dji_wav_paths:
    tx_cache[str(wav_path)] = extract_mono_8k(wav_path, 0, duration_sec)
```

This avoids repeated subprocess spawns and makes per-clip correlation fast (pure numpy).

### Pattern 3: Candidate selection via waveform correlation (AUD-03)

For each clip, iterate over ALL TX WAVs of the correct transmitter (TX01 or TX02), correlate, pick the one with highest peak. The key is using a sliding window search — for a clip of duration D seconds, the camera audio is D seconds; the TX WAV has a search window spanning the entire WAV duration. Use `scipy.signal.fftconvolve` (O(n log n)) not `scipy.signal.correlate` mode='full' which is O(n²) for large arrays:

```python
from scipy.signal import fftconvolve

def find_best_tx_candidate(
    cam_audio: np.ndarray,          # clip's camera audio at 8kHz
    tx_wav_cache: dict[str, np.ndarray],  # {path_str: full wav at 8kHz}
    tx_wavs: list[Path],
    sr: int = 8000,
) -> tuple[Path, float, float]:
    """Returns (best_tx_path, best_trim_start_sec, best_confidence)."""
    best_path = None
    best_conf = -1.0
    best_offset_sec = 0.0

    cam_n = (cam_audio - cam_audio.mean()) / (cam_audio.std() + 1e-10)
    cam_flipped = cam_n[::-1]

    for tx_path in tx_wavs:
        tx_audio = tx_wav_cache[str(tx_path)]
        if len(tx_audio) < len(cam_n):
            continue
        tx_n = (tx_audio - tx_audio.mean()) / (tx_audio.std() + 1e-10)
        corr = fftconvolve(tx_n, cam_flipped, mode="full")
        # Only look in the valid region (camera can't start before TX WAV)
        valid_start = len(cam_n) - 1   # first possible alignment
        valid_end = len(cam_n) - 1 + len(tx_audio) - len(cam_n)
        peak_idx = np.argmax(corr[valid_start:valid_end]) + valid_start
        peak_val = corr[peak_idx]
        mean_val = np.mean(np.abs(corr[valid_start:valid_end]))
        conf = peak_val / (mean_val + 1e-10)
        offset_sec = (peak_idx - (len(cam_n) - 1)) / sr
        if conf > best_conf:
            best_conf = conf
            best_path = tx_path
            best_offset_sec = offset_sec

    return best_path, best_offset_sec, best_conf
```

### Pattern 4: Sync delta reporting in frames (AUD-06)

FPS comes from ffprobe on the clip. Sony FX3 shoots at 25fps or 30fps. Convert residual_sec from `verify_full()` to frames:

```python
def sec_to_frames(residual_sec: float, fps: float) -> float:
    return abs(residual_sec) * fps

# Example: residual=0.025s at 25fps → 0.625F → report as "0.6F"
# Target: ≤1F = ≤0.040s at 25fps, ≤0.033s at 30fps
```

Use `ffprobe -show_streams -select_streams v:0` to get `r_frame_rate` per clip.

### Pattern 5: Per-scene ingest.json generation (AUD-07)

The existing `ingest_json.py` already scans `01_Media/Source/Audio/` for `{clip_id}_TX*.wav` files and adds them to `clip["dji_audio"]`. For the nested structure, the TX WAVs land at `01_Media/Source/Audio/{clip}_TX01.wav` (flat, no scene subdir based on REQUIREMENTS.md AUD-04/05). The `rglob` in `ingest_json.py` line 98 will find them.

For AUD-07 (per-scene ingest.json with A1/A2/A3 track labels), a new function is needed that writes a scene-scoped JSON. The planner should decide whether this is a new function in `ingest_json.py` or a new file. The JSON structure should be:

```json
{
  "scene": "volleyball",
  "clips": [
    {
      "clip_id": "C5089",
      "tracks": {
        "A1": {"type": "camera_embed", "path": "01_Media/Source/Video/volleyball/C5089.MP4"},
        "A2": {"type": "TX01_SYNC", "path": "01_Media/Source/Audio/C5089_TX01.wav"},
        "A3": {"type": "TX02_SYNC", "path": "01_Media/Source/Audio/C5089_TX02.wav"}
      }
    }
  ]
}
```

### Output Structure

```
project/
├── 01_Media/Source/
│   ├── Transcription/per_clip/{scene}/{clip}/
│   │   └── {clip}_AUDIO.wav           ← AUD-01
│   └── Audio/
│       ├── {clip}_TX01.wav            ← AUD-04 (flat, no scene subdir)
│       └── {clip}_TX02.wav            ← AUD-05
└── 01_Media/Source/Setup/
    └── {scene}_ingest.json            ← AUD-07
```

Note on `_AUDIO.wav` path: REQUIREMENTS.md AUD-01 says `Transcription/per_clip/{scene}/{clip}/{clip}_AUDIO.wav` — this adds the `{scene}` layer compared to the flat 0102 script which uses `per_clip/{clip}/{clip}_AUDIO.wav`. The new script must create the scene subfolder.

### Anti-Patterns to Avoid

- **Timestamp pre-filtering:** Do NOT filter TX WAV candidates by creation_time overlap before correlation. TX records continuously; timestamps are unreliable. Correlate all candidates regardless of timestamp.
- **scipy.signal.correlate with mode='full':** Quadratic complexity. Use `fftconvolve` for long signals.
- **Re-loading TX WAVs per clip:** Pre-load once at startup (Pattern 2).
- **Modifying 0102 or 0103:** Phase 2 must be additive. New standalone script only.
- **Using librosa:** Not installed in `.venv_transcribe` (only `numba` 0.63.1 is there, not librosa itself).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FFT-based cross-correlation | Custom FFT correlator | `scipy.signal.fftconvolve` | Already in venv, handles edge padding, tested |
| WAV trimming with silence pad | Custom WAV writer | `build_ffmpeg_cmd()` from 0103 | Handles multi-segment, auto-split snapping, sample-accurate atrim |
| Clip duration extraction | Custom ffprobe parser | `get_video_clip_info()` from 0103 | Handles creation_time, duration, caching |
| Audio extraction to float32 numpy | Custom audio reader | `extract_mono_8k()` from 0103 | 8kHz mono via ffmpeg pipe, already battle-tested |
| Sync verification | Custom correlation check | `verify_full()` from fix_dji_sync | Already returns residual_sec for frame delta |

**Key insight:** ~80% of the Phase 2 logic already exists in 0103_sync_dji_audio.py and fix_dji_sync.py. The new script is primarily orchestration + candidate selection + scene-layer output paths.

---

## Common Pitfalls

### Pitfall 1: AUD-01 path: scene subdir is NEW vs existing 0102

**What goes wrong:** The existing `0102_extract_audio.py` creates `per_clip/{clip}/{clip}_AUDIO.wav`. AUD-01 requires `per_clip/{scene}/{clip}/{clip}_AUDIO.wav`. If the new script reuses 0102's output unchanged, the path will be wrong and 0103's existing flat logic will also break for nested projects.
**Why it happens:** 0102 was designed for flat projects; it has no scene concept.
**How to avoid:** In the new script, always mkdir `per_clip/{scene}/{clip}/` and pass that as the output dir to the ffmpeg extraction command.
**Warning signs:** Missing `{scene}/` level in the Transcription output tree.

### Pitfall 2: Correlation peak ambiguity when clip is mostly silence

**What goes wrong:** Short clips (≤2s), clips of environmental sound without speech, or clips where TX was muted all yield flat correlation with no clear peak. Confidence score below 3.0 is the existing threshold.
**Why it happens:** Cross-correlation assumes a distinctive waveform pattern shared between camera and TX audio.
**How to avoid:** Keep the existing confidence threshold (3.0). If confidence < 3.0, fall back to timestamp-based rough offset or mark as `NO_SYNC` in the report. Do not write a silent TX WAV — write a silence-padded file with the best rough offset.
**Warning signs:** Many clips reporting confidence < 3.0, or sync delta > 5F.

### Pitfall 3: Memory OOM when loading 16 × 30min WAVs at full 48kHz

**What goes wrong:** If loading TX WAVs at 48kHz stereo (the native format), 16 files × 30min × 48000Hz × 2ch × 4bytes = ~6.6 GB — will OOM on most systems.
**Why it happens:** Correlation requires the full TX WAV in memory.
**How to avoid:** Always load via `extract_mono_8k()` at 8kHz mono. For correlation only. The 8kHz signal retains enough envelope structure for confident sync. The actual trim is still done by ffmpeg on the original 48kHz 24-bit file.
**Warning signs:** Python MemoryError or system swap usage spike during WAV pre-loading.

### Pitfall 4: Wrong TX WAV selected when two TX WAVs overlap in time

**What goes wrong:** Multiple TX01 WAVs can cover the same clip time window (e.g., TX01_MIC001 ends mid-scene, TX01_MIC002 starts). Picking the first one or the one with more time overlap is wrong — the one with higher waveform correlation wins.
**Why it happens:** Timestamp-based selection ignores waveform quality.
**How to avoid:** Always correlate ALL TX WAV files for the given transmitter (TX01 vs TX02 is determined by TX prefix, not by which WAV "wins"). Return the one with highest confidence.
**Warning signs:** Success criteria item 4 — "correct TX WAV selected even when multiple overlap."

### Pitfall 5: Scene detection regex mismatch

**What goes wrong:** The existing `0103_sync_dji_audio.py` uses `SCENE_DIR_RE = re.compile(r'^\d{2}_')` to detect scene folders. The reference project's scene names (`volleyball`, `apartment`, `al_qudra_lake`, etc.) do NOT start with `\d{2}_` — they are bare names. After Phase 1 (organize), they land in `Source/Video/{scene_name}/` without numeric prefix.
**Why it happens:** The existing regex was designed for numbered scene folders. The reference project uses bare scene names.
**How to avoid:** In the new script, any subdirectory of `Source/Video/` containing video files is a scene — do NOT require `^\d{2}_` prefix. Use `p.parent.relative_to(clips_dir).parts[0]` as scene name without regex filtering.
**Warning signs:** Script treats all clips as flat (no scene detected) despite scene subfolders existing.

### Pitfall 6: AUD-02 concatenated FULL_AUDIO is per-scene, not project-wide

**What goes wrong:** 0102_extract_audio.py creates one `{project}_FULL_AUDIO.wav`. AUD-02 requires `{scene}_FULL_AUDIO.wav` per scene. Building a single project-wide concat would mix scenes.
**Why it happens:** AUD-02 is used as the correlation reference for that scene's clips, so it must be scene-scoped.
**How to avoid:** Group clips by scene, then build one concat per scene. Save as `Transcription/{scene}_FULL_AUDIO.wav` or `Transcription/per_clip/{scene}/{scene}_FULL_AUDIO.wav`.

### Pitfall 7: GoPro clips in al_qudra_lake

**What goes wrong:** `al_qudra_lake` contains both Sony FX3 (`C5XXX.MP4`) and GoPro (`100GOPRO/GX010001.MP4`) clips. GoPro audio may have different characteristics and metadata.
**Why it happens:** The reference project has a mixed-camera scene.
**How to avoid:** GoPro clips should still attempt TX sync — GoPro and Sony both recorded the same audio environment. Include GoPro clips in the correlation pass. If GoPro clips yield low confidence (< 3.0), mark as `LOW_CONF` in report rather than failing.

---

## Code Examples

Verified patterns from existing project code:

### Audio extraction at 8kHz mono (from 0103_sync_dji_audio.py line 364)
```python
def extract_mono_8k(filepath: Path, start_sec: float,
                    duration_sec: float) -> np.ndarray:
    """Extract audio as mono 8kHz float32 numpy array via ffmpeg pipe."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0, start_sec):.6f}",
        "-t", f"{duration_sec:.6f}",
        "-i", str(filepath),
        "-ac", "1",           # mono
        "-ar", "8000",        # 8kHz for envelope analysis
        "-f", "f32le",
        "-c:a", "pcm_f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32)
```

### Full waveform correlation (from fix_dji_sync.py line 106)
```python
from scipy.signal import fftconvolve

# Normalize both signals
cam_n = (cam - cam.mean()) / cam.std()
dji_n = (dji - dji.mean()) / dji.std()

# Cross-correlate (FFT-based, O(n log n))
cam_flipped = cam_n[::-1]
corr = fftconvolve(dji_n, cam_flipped, mode="full")

# Peak location → offset in seconds
peak_idx = np.argmax(corr[search_lo:search_hi]) + search_lo
offset_samples = peak_idx - len(cam_n) + 1
offset_sec = offset_samples / SR  # SR = 8000
```

### WAV trim/pad via ffmpeg atrim filter (from 0103_sync_dji_audio.py line 597)
```python
# build_ffmpeg_cmd(segments, output_path, gaps=None, target_duration=clip_dur)
# Always re-encodes pcm_s24le (lossless, sample-accurate)
# Pads silence at end if TX audio shorter than clip
```

### Clip audio extraction at 48kHz stereo (from 0102_extract_audio.py line 263)
```python
cmd = [
    "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
    "-i", str(clip),
    "-map", "0:a:0",       # First audio stream
    "-vn", "-sn", "-dn",
    "-ar", "48000",        # 48kHz
    "-ac", "2",            # Stereo
    "-c:a", "pcm_s16le",   # 16-bit PCM
    str(wav_path),
]
```

### Delta in frames from residual seconds
```python
def residual_to_frames(residual_sec: float, fps: float) -> float:
    return abs(residual_sec) * fps

# At 25fps: 1F = 0.040s
# At 30fps: 1F = 0.033s
# Target: ≤1F → residual ≤ 0.033s at 30fps
```

---

## State of the Art

| Old Approach (0103 flat) | New Approach (Phase 2 nested) | Impact |
|--------------------------|-------------------------------|--------|
| Timestamp pre-filter → find overlapping WAVs | Full correlation over all TX WAVs | Handles TX records continuously across scenes |
| Single correction per TX globally | Per-clip fine sync | ≤1F accuracy per clip, not per session |
| `per_clip/{clip}/` flat structure | `per_clip/{scene}/{clip}/` with scene layer | Required for nested project ingest |
| Sync verified at 3 time points | sync verified once via `verify_full()` reporting residual_sec | Cleaner per-clip delta in frames |

---

## Open Questions

1. **AUD-07: Where does per-scene ingest.json live?**
   - What we know: `ingest_json.py` writes to `Setup/{project}_ingest.json`. For nested, the spec says "per-scene ingest.json".
   - What's unclear: Is it one ingest.json per scene (7 files) or one project-level ingest.json with scenes as sections?
   - Recommendation: Write one JSON per scene to `01_Media/Source/Setup/{scene}_ingest.json`. The project-level `{project}_ingest.json` can reference them. This matches TRN-01's per-scene model.

2. **AUD-02: Is scene FULL_AUDIO used as correlation reference or only for transcription?**
   - What we know: AUD-02 says "used as reference for DJI sync." But the existing 0103 approach correlates clip audio directly against TX WAVs.
   - What's unclear: Does FULL_AUDIO serve correlation or just serve as transcription input (Phase 3)?
   - Recommendation: Build FULL_AUDIO per scene primarily for Phase 3 transcription. For AUD-03 correlation, use per-clip `{clip}_AUDIO.wav` (more precise, avoids timestamp-offset complexity). FULL_AUDIO is a bonus output of AUD-01/AUD-02.

3. **FPS for frame delta reporting (AUD-06): 25 or 30?**
   - What we know: The existing `generate_prproj.py` uses `FPS = 25`. The format_timecode helper in 0103 defaults to 25fps.
   - What's unclear: Sony FX3 can shoot 25fps or 30fps or 60fps; reference project clips need to be checked.
   - Recommendation: Extract FPS via `ffprobe -show_streams -select_streams v:0 -show_entries stream=r_frame_rate` per clip. Report delta in frames using actual clip FPS. Fall back to 30fps if unknown.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 (available globally via `python3 -m pytest`) |
| Config file | none — no pytest.ini; tests run by convention |
| Quick run command | `python3 -m pytest scripts/01_prepare/0104_sync_audio_nested/tests/ -x -q` |
| Full suite command | `python3 -m pytest scripts/01_prepare/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUD-01 | Extract `{clip}_AUDIO.wav` under `per_clip/{scene}/{clip}/` | unit | `python3 -m pytest .../tests/test_0104.py::test_audio_extraction_scene_path -x` | Wave 0 |
| AUD-02 | Per-scene FULL_AUDIO.wav built from scene clips | unit | `python3 -m pytest .../tests/test_0104.py::test_scene_concat -x` | Wave 0 |
| AUD-03 | Best TX WAV selected by waveform correlation (not timestamp) | unit | `python3 -m pytest .../tests/test_0104.py::test_candidate_selection -x` | Wave 0 |
| AUD-04 | TX01 WAV trimmed to clip duration at correct offset | unit | `python3 -m pytest .../tests/test_0104.py::test_tx01_trim -x` | Wave 0 |
| AUD-05 | TX02 WAV trimmed to clip duration at correct offset | unit | `python3 -m pytest .../tests/test_0104.py::test_tx02_trim -x` | Wave 0 |
| AUD-06 | Sync delta reported in frames; ≤1F on reference project | integration (manual) | manual on YTCR_1_Arty_Dzis | manual |
| AUD-07 | Per-scene ingest.json has A1/A2/A3 tracks | unit | `python3 -m pytest .../tests/test_0104.py::test_ingest_tracks -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python3 -m pytest scripts/01_prepare/0104_sync_audio_nested/tests/ -x -q`
- **Per wave merge:** `python3 -m pytest scripts/01_prepare/ -x -q`
- **Phase gate:** All unit tests green + manual verification on `apartment` scene (40 clips, smallest non-trivial scene)

### Wave 0 Gaps
- [ ] `scripts/01_prepare/0104_sync_audio_nested/__init__.py` — module init
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/__init__.py` — test package init
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/conftest.py` — fixtures with synthetic WAV data (use numpy to generate sine waves at 8kHz to avoid real file I/O)
- [ ] `scripts/01_prepare/0104_sync_audio_nested/tests/test_0104.py` — unit tests for AUD-01 through AUD-07 logic

---

## Sources

### Primary (HIGH confidence)
- `/Users/romansergeev/YTAI/scripts/01_prepare/0103_sync_dji_audio/0103_sync_dji_audio.py` — full read; correlation functions, build_ffmpeg_cmd, get_video_clip_info, extract_mono_8k
- `/Users/romansergeev/YTAI/scripts/01_prepare/0103_sync_dji_audio/fix_dji_sync.py` — full read; full_waveform_fine_offset, verify_full
- `/Users/romansergeev/YTAI/scripts/01_prepare/0102_extract_audio/0102_extract_audio.py` — full read; ffmpeg extraction pattern, per_clip structure
- `/Users/romansergeev/YTAI/scripts/02_transcribe/020101_transcribe/ingest_json.py` — full read; ingest.json generation, dji_audio field structure
- `/Users/romansergeev/YTAI/scripts/01_prepare/0103_sync_dji_audio/generate_prproj.py` — full read; FPS=25 constant, multi-scene XML structure
- `pip list` in `.venv_transcribe` — confirmed: scipy 1.17.0, numpy 2.3.5, soundfile 0.13.1, numba 0.63.1 (no librosa)
- Reference project inspection — confirmed: TX WAV timestamps (TX01_MIC001 starts 10:22:11 local), volleyball clips start 02:53:05 UTC; confirms timestamps unreliable without TZ; waveform correlation required
- `.planning/REQUIREMENTS.md` — AUD-01 through AUD-07 confirmed

### Secondary (MEDIUM confidence)
- `scripts/01_prepare/0100_organize/tests/conftest.py` — test patterns with importlib.util, fake_nested_project fixture structure
- Reference project file listing — 3 TX01 WAVs, 9 TX02 WAVs, 4 TX02_2 WAVs = 16 total; scene names without `^\d{2}_` prefix

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified via pip list in the actual venv
- Architecture: HIGH — based on reading existing production scripts, not speculation
- Pitfalls: HIGH — pitfalls derived from reading actual code edge cases
- Validation: HIGH — pytest 9.0.2 confirmed working, existing test suite confirmed passing

**Research date:** 2026-03-17
**Valid until:** 2026-06-17 (stable domain — library versions won't change in venv)
