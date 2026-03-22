#!/usr/bin/env python3
"""
YTAI: Sync DJI audio with camera video clips

DJI wireless mics record mono WAV (24-bit, 48kHz) with a maximum of 30 minutes per file.
This script trims and concatenates DJI WAV files to match each camera video clip,
using metadata timestamps for synchronization.

Usage:
    python 0103_sync_dji_audio.py --project "/path/to/project"
    python 0103_sync_dji_audio.py --project "/path/to/project" --tz-offset 4
    python 0103_sync_dji_audio.py --project "/path/to/project" --dry-run

Output:
    01_Media/Source/Audio/
    ├── RYA-FX3-0099_TX02.wav     (trimmed DJI WAV for clip 0099)
    ├── RYA-FX3-0100_TX02.wav     (concat + trim for clip 0100)
    └── ...

    01_Media/Source/Setup/logs/
    └── YTCG37_Project_sync_dji_audio_20260311_120000.log
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np


# ============================================================================
# Configuration
# ============================================================================

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

WAV_EXTS = {".wav", ".WAV"}

CLIPS_SUBDIR = "01_Media/Source/Video"
DJI_SUBDIR = "99_Pipeline/DJI_Audio"
AUDIO_SUBDIR = "01_Media/Source/Audio"
LOGS_SUBDIR = "01_Media/Source/Setup/logs"

MIN_OK_BYTES = 100_000  # 100KB minimum for a valid WAV

SCENE_DIR_RE = re.compile(r'^\d{2}_')

CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')


def project_code(project_dir: Path) -> str:
    """Extract short code (e.g. 'YTCG37') from project folder name."""
    m = CODE_RE.match(project_dir.name)
    return m.group(1) if m else project_dir.name


# ============================================================================
# Utilities
# ============================================================================

def natural_key(s: str):
    """Natural sort for strings with numbers: clip1, clip2, clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _find_video_path(clip_id: str, video_path_map: dict[str, Path],
                     clips_dir: Path) -> Path | None:
    """Find video file path for a clip_id, using prebuilt map or fallback scan."""
    vpath = video_path_map.get(clip_id)
    if vpath and vpath.exists():
        return vpath
    # Fallback: try all extensions in clips_dir (flat)
    for ext in VIDEO_EXTS:
        vpath = clips_dir / f"{clip_id}{ext}"
        if vpath.exists():
            return vpath
    return None


def _scene_out_dir(clip_id: str, clip_scene_map: dict[str, str],
                   out_dir: Path) -> Path:
    """Return scene-aware output directory: out_dir/{scene}/ or out_dir/."""
    scene = clip_scene_map.get(clip_id)
    d = (out_dir / scene) if scene else out_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def ffmpeg_exists() -> bool:
    """Check whether ffmpeg/ffprobe is available."""
    try:
        subprocess.run(["ffprobe", "-version"], check=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences for plain-text log file."""
    return re.sub(r"\033\[[0-9;]*m", "", s)


def tee_print(log_f, msg: str) -> None:
    """Print to both console (with ANSI) and log file (plain)."""
    print(msg)
    if log_f:
        log_f.write(_strip_ansi(msg) + "\n")
        log_f.flush()


# ── ANSI color constants ──
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[97m"
BG_GREEN = "\033[42m"
BG_RED = "\033[41m"
RST = "\033[0m"


def run_ffmpeg(cmd: list[str], log_f, verbose: bool = False) -> int:
    """Run an ffmpeg command with logging."""
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None

    output_lines = []
    for line in p.stdout:
        output_lines.append(line.rstrip("\n"))
        if verbose:
            tee_print(log_f, f"    {line.rstrip()}")

    rc = p.wait()

    if rc != 0 and not verbose:
        tee_print(log_f, "    FFmpeg output:")
        for line in output_lines[-5:]:
            tee_print(log_f, f"    {line}")

    return rc


def format_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def format_duration(seconds: float) -> str:
    """Format duration as HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_timecode(seconds: float, fps: int = 25) -> str:
    """Format duration as SMPTE timecode HH:MM:SS:FF at given fps."""
    total_frames = int(seconds * fps)
    ff = total_frames % fps
    total_secs = total_frames // fps
    ss = total_secs % 60
    mm = (total_secs // 60) % 60
    hh = total_secs // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# ============================================================================
# ffprobe helpers
# ============================================================================

def ffprobe_json(filepath: Path) -> dict:
    """Get metadata via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(filepath),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {filepath}: {result.stderr}")
    return json.loads(result.stdout)


def get_video_clip_info(filepath: Path) -> dict:
    """Get creation_time (UTC) and duration of a video clip."""
    info = ffprobe_json(filepath)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))
    tags = fmt.get("tags", {})

    creation_time_str = tags.get("creation_time", "")
    creation_utc = None
    if creation_time_str:
        # Format: "2026-03-06T06:26:08.000000Z"
        for fmt_str in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                creation_utc = datetime.strptime(creation_time_str, fmt_str).replace(
                    tzinfo=timezone.utc
                )
                break
            except ValueError:
                continue

    return {
        "clip_id": filepath.stem,
        "path": filepath,
        "duration": duration,
        "creation_utc": creation_utc,
    }


def get_dji_wav_info_raw(filepath: Path) -> dict:
    """Get DJI WAV metadata WITHOUT timezone conversion.

    Returns local_naive (naive datetime, no tz) for auto-detection.
    """
    info = ffprobe_json(filepath)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))
    tags = fmt.get("tags", {})

    # Parse tx_id from filename: TX02_MIC037_20260306_102304_orig.wav
    name = filepath.stem
    tx_match = re.match(r"(TX\d+)", name, re.IGNORECASE)
    tx_id = tx_match.group(1).upper() if tx_match else "TX00"

    # Parse local time from tags
    local_naive = None
    date_str = tags.get("date", "")
    time_str = tags.get("creation_time", "")
    if date_str and time_str:
        try:
            local_naive = datetime.strptime(
                f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    # Fallback: parse from filename
    if local_naive is None:
        ts_match = re.search(r"(\d{8})_(\d{6})", name)
        if ts_match:
            try:
                local_naive = datetime.strptime(
                    f"{ts_match.group(1)}_{ts_match.group(2)}",
                    "%Y%m%d_%H%M%S")
            except ValueError:
                pass

    # Audio stream properties
    audio_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"),
        {}
    )

    return {
        "tx_id": tx_id,
        "path": filepath,
        "duration": duration,
        "local_naive": local_naive,
        "sample_rate": int(audio_stream.get("sample_rate", 48000)),
        "bits_per_sample": int(audio_stream.get("bits_per_sample", 24)),
        "channels": int(audio_stream.get("channels", 1)),
    }


def get_dji_wav_info(filepath: Path, tz_offset_hours: float) -> dict:
    """Get DJI WAV metadata with timezone conversion to UTC."""
    raw = get_dji_wav_info_raw(filepath)
    creation_utc = None
    if raw["local_naive"] is not None:
        local_tz = timezone(timedelta(hours=tz_offset_hours))
        local_dt = raw["local_naive"].replace(tzinfo=local_tz)
        creation_utc = local_dt.astimezone(timezone.utc)
    result = dict(raw)
    del result["local_naive"]
    result["creation_utc"] = creation_utc
    return result


# ============================================================================
# Auto-detect timezone
# ============================================================================

def auto_detect_tz_offset(clips: list, raw_wavs: list) -> tuple:
    """Auto-detect timezone offset by maximizing DJI-video overlaps.

    For each candidate offset (-12 to +14 in 0.5h steps), convert DJI local
    timestamps to UTC and count how many DJI files overlap with at least one
    video clip.  The offset with the most overlaps wins.

    Args:
        clips: video clip dicts with creation_utc and duration.
        raw_wavs: raw DJI dicts with local_naive and duration.

    Returns:
        (best_offset | None, overlap_count, total_wavs)
    """
    valid_clips = [c for c in clips if c.get("creation_utc") is not None]
    valid_wavs = [w for w in raw_wavs if w.get("local_naive") is not None]

    if not valid_clips or not valid_wavs:
        return (None, 0, 0)

    # Pre-compute clip time ranges (UTC)
    clip_ranges = []
    for c in valid_clips:
        s = c["creation_utc"]
        clip_ranges.append((s, s + timedelta(seconds=c["duration"])))

    best_offset = 0.0
    best_count = 0

    # Brute-force: -12.0 to +14.0 in 0.5h steps (53 candidates)
    for half_h in range(-24, 29):
        offset = half_h / 2.0
        count = 0
        for raw in valid_wavs:
            tz = timezone(timedelta(hours=offset))
            ws = raw["local_naive"].replace(tzinfo=tz).astimezone(
                timezone.utc)
            we = ws + timedelta(seconds=raw["duration"])
            for cs, ce in clip_ranges:
                if max(cs, ws) < min(ce, we):
                    count += 1
                    break  # this WAV overlaps at least one clip
        if count > best_count:
            best_count = count
            best_offset = offset

    if best_count == 0:
        return (None, 0, len(valid_wavs))
    return (best_offset, best_count, len(valid_wavs))


# ============================================================================
# Cross-correlation fine sync
# ============================================================================

def _log(log_f, msg: str):
    """Log helper: tee_print if log_f is available."""
    if log_f:
        tee_print(log_f, msg)


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
        "-f", "f32le",        # raw float32 little-endian
        "-c:a", "pcm_f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32)


def compute_envelope(audio: np.ndarray, sr: int = 8000,
                     window_ms: float = 50.0) -> np.ndarray:
    """Amplitude envelope: abs + running-average smoothing."""
    if len(audio) < 100:
        return audio
    env = np.abs(audio)
    win = max(1, int(sr * window_ms / 1000))
    kernel = np.ones(win) / win
    return np.convolve(env, kernel, mode="same")


def find_fine_offset(
    camera_path: Path,
    dji_path: Path,
    rough_offset: float,
    analysis_dur: float = 60.0,
    search_window: float = 10.0,
    log_f=None,
) -> tuple:
    """Find precise DJI offset via cross-correlation of audio envelopes.

    Compares camera audio (from clip start) with DJI audio (around the
    metadata-based rough_offset) to find the exact time alignment.

    Each stage is logged with [EXTRACT]/[ENVELOPE]/[CORRELATE]/[RESULT] tags.

    Returns:
        (refined_offset_sec, confidence)
    """
    SR = 8000

    # ---- [EXTRACT] Camera audio ----
    _log(log_f, f"    [EXTRACT] Camera: {camera_path.name}")
    _log(log_f, f"             range: 0s → {analysis_dur}s")
    cam = extract_mono_8k(camera_path, 0, analysis_dur)
    cam_dur = len(cam) / SR if len(cam) > 0 else 0
    if len(cam) < SR * 2:
        _log(log_f, f"             ✗ Too short ({cam_dur:.1f}s, need ≥2s)")
        return (rough_offset, 0.0)
    _log(log_f, f"             ✓ {len(cam)} samples ({cam_dur:.1f}s)")

    # ---- [EXTRACT] DJI audio ----
    dji_start = max(0, rough_offset - search_window)
    dji_dur = analysis_dur + 2 * search_window
    _log(log_f, f"    [EXTRACT] DJI: {dji_path.name}")
    _log(log_f, f"             range: {dji_start:.1f}s → {dji_start + dji_dur:.1f}s")
    dji = extract_mono_8k(dji_path, dji_start, dji_dur)
    dji_actual = len(dji) / SR if len(dji) > 0 else 0
    if len(dji) < SR * 2:
        _log(log_f, f"             ✗ Too short ({dji_actual:.1f}s)")
        return (rough_offset, 0.0)
    _log(log_f, f"             ✓ {len(dji)} samples ({dji_actual:.1f}s)")

    # ---- [ENVELOPE] ----
    cam_env = compute_envelope(cam, SR)
    dji_env = compute_envelope(dji, SR)
    _log(log_f, f"    [ENVELOPE] Camera: min={cam_env.min():.4f} "
                f"max={cam_env.max():.4f} std={cam_env.std():.4f}")
    _log(log_f, f"    [ENVELOPE] DJI:    min={dji_env.min():.4f} "
                f"max={dji_env.max():.4f} std={dji_env.std():.4f}")

    if cam_env.std() < 1e-6 or dji_env.std() < 1e-6:
        _log(log_f, "    [ENVELOPE] ✗ Silence detected — skip correlation")
        return (rough_offset, 0.0)

    # Normalize to zero-mean, unit-variance
    cam_env = (cam_env - cam_env.mean()) / cam_env.std()
    dji_env = (dji_env - dji_env.mean()) / dji_env.std()

    # ---- [CORRELATE] ----
    from scipy.signal import correlate
    corr = correlate(dji_env, cam_env, mode="full")

    peak_idx = np.argmax(corr)
    peak_val = corr[peak_idx]
    mean_val = np.mean(np.abs(corr))
    confidence = peak_val / (mean_val + 1e-10)

    # Convert peak index to time offset in the DJI file
    offset_samples = peak_idx - len(cam_env) + 1
    offset_sec = offset_samples / SR
    refined_offset = dji_start + offset_sec
    correction = refined_offset - rough_offset

    _log(log_f, f"    [CORRELATE] Peak index: {peak_idx}/{len(corr)}  "
                f"value={peak_val:.1f}")
    _log(log_f, f"    [CORRELATE] Mean correlation: {mean_val:.1f}")
    _log(log_f, f"    [CORRELATE] Confidence: {confidence:.1f} "
                f"(threshold=3.0)")

    if confidence < 3.0:
        _log(log_f, "    [RESULT] ✗ Low confidence — keeping metadata offset")
        return (rough_offset, confidence)

    _log(log_f, f"    [RESULT] ✓ Metadata: {rough_offset:.3f}s → "
                f"Refined: {refined_offset:.3f}s  "
                f"(correction: {correction:+.3f}s)")

    return (refined_offset, confidence)


def verify_sync_quality(
    camera_path: Path,
    dji_output_path: Path,
    check_points: list,
    analysis_dur: float = 10.0,
    log_f=None,
) -> list:
    """Verify sync quality at multiple time points.

    Cross-correlates camera audio vs DJI output at each point.
    Returns list of {time, offset_error, confidence} dicts.
    """
    SR = 8000
    results = []

    for t in check_points:
        _log(log_f,
            f"      [CHECK] t={format_duration(t)} ({t:.1f}s)")

        # Extract camera audio at this point
        cam = extract_mono_8k(camera_path, t, analysis_dur)
        if len(cam) < SR * 2:
            _log(log_f, "        Camera: too short, skip")
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0})
            continue

        # DJI output: extract wider window (±2s) to find offset
        search_margin = 2.0
        dji = extract_mono_8k(dji_output_path,
                              max(0, t - search_margin),
                              analysis_dur + 2 * search_margin)
        if len(dji) < SR * 2:
            _log(log_f, "        DJI output: too short, skip")
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0})
            continue

        # Envelopes
        cam_env = compute_envelope(cam, SR)
        dji_env = compute_envelope(dji, SR)

        if cam_env.std() < 1e-6 or dji_env.std() < 1e-6:
            _log(log_f, "        Silence, skip")
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0})
            continue

        cam_env = (cam_env - cam_env.mean()) / cam_env.std()
        dji_env = (dji_env - dji_env.mean()) / dji_env.std()

        from scipy.signal import correlate
        corr = correlate(dji_env, cam_env, mode="full")

        # Constrain peak search to ±max_search around expected position
        # Expected: DJI starts search_margin before camera → peak at
        # (len(cam_env) - 1 + search_margin * SR)
        max_search = MAX_DRIFT_SEC + 0.5  # slightly wider than threshold
        expected_idx = len(cam_env) - 1 + int(search_margin * SR)
        search_lo = max(0, expected_idx - int(max_search * SR))
        search_hi = min(len(corr), expected_idx + int(max_search * SR))

        window_corr = corr[search_lo:search_hi]
        if len(window_corr) == 0:
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0})
            continue

        local_peak = np.argmax(window_corr)
        peak_idx = search_lo + local_peak
        peak_val = window_corr[local_peak]
        mean_val = np.mean(np.abs(corr))
        confidence = peak_val / (mean_val + 1e-10)

        offset_samples = peak_idx - len(cam_env) + 1
        offset_sec = offset_samples / SR
        # Perfect alignment: DJI starts search_margin before camera
        offset_error = offset_sec - search_margin

        status = ("OK" if abs(offset_error) < MAX_DRIFT_SEC
                  and confidence > 3.0
                  else "DRIFT" if confidence > 3.0
                  else "LOW_CONF")
        _log(log_f,
            f"        Error: {offset_error:+.3f}s  "
            f"Conf: {confidence:.1f}  [{status}]")

        results.append({"time": t, "offset_error": offset_error,
                        "confidence": confidence})

    return results


# ============================================================================
# Dense verification + enforcement
# ============================================================================

# Thresholds for dense verification
VERIFY_INTERVAL = 5.0       # Check every 5 seconds
VERIFY_WINDOW = 10.0        # Analysis window per check point
MAX_DRIFT_SEC = 0.5         # Max acceptable sync error
SEARCH_MARGIN = 2.0         # Search margin for correlation


def extract_full_mono_8k(filepath: Path) -> np.ndarray:
    """Extract full audio file as mono 8kHz float32 (single ffmpeg call)."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(filepath),
        "-ac", "1", "-ar", "8000",
        "-f", "f32le", "-c:a", "pcm_f32le",
        "pipe:1",
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(result.stdout, dtype=np.float32)


def _slice_array(arr: np.ndarray, start_sec: float, dur_sec: float,
                 sr: int = 8000) -> np.ndarray:
    """Slice numpy array by time (seconds)."""
    s = max(0, int(start_sec * sr))
    e = min(len(arr), int((start_sec + dur_sec) * sr))
    return arr[s:e] if s < e else np.array([], dtype=arr.dtype)


def verify_sync_dense(
    cam_8k: np.ndarray,
    dji_8k: np.ndarray,
    clip_duration: float,
    interval: float = VERIFY_INTERVAL,
    window: float = VERIFY_WINDOW,
    log_f=None,
) -> list:
    """Dense sync verification using pre-loaded 8kHz arrays.

    Checks every `interval` seconds. Returns list of
    {time, offset_error, confidence, ok} dicts.
    """
    SR = 8000
    search_margin = SEARCH_MARGIN
    results = []

    # Generate check points
    pts = [5.0]
    t = interval
    while t + window + 2.0 < clip_duration:
        pts.append(t)
        t += interval
    pts = sorted(set(pts))

    for t in pts:
        cam_chunk = _slice_array(cam_8k, t, window)
        if len(cam_chunk) < SR * 2:
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0, "ok": True})
            continue

        dji_chunk = _slice_array(dji_8k,
                                 max(0, t - search_margin),
                                 window + 2 * search_margin)
        if len(dji_chunk) < SR * 2:
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0, "ok": True})
            continue

        cam_env = compute_envelope(cam_chunk, SR)
        dji_env = compute_envelope(dji_chunk, SR)

        if cam_env.std() < 1e-6 or dji_env.std() < 1e-6:
            # Silence — can't verify, assume ok
            results.append({"time": t, "offset_error": None,
                            "confidence": 0.0, "ok": True})
            continue

        cam_env = (cam_env - cam_env.mean()) / cam_env.std()
        dji_env = (dji_env - dji_env.mean()) / dji_env.std()

        from scipy.signal import correlate
        corr = correlate(dji_env, cam_env, mode="full")
        peak_idx = np.argmax(corr)
        peak_val = corr[peak_idx]
        mean_val = np.mean(np.abs(corr))
        confidence = peak_val / (mean_val + 1e-10)

        offset_samples = peak_idx - len(cam_env) + 1
        offset_sec = offset_samples / SR
        offset_error = offset_sec - search_margin

        ok = abs(offset_error) < MAX_DRIFT_SEC or confidence < 3.0
        results.append({"time": t, "offset_error": offset_error,
                        "confidence": confidence, "ok": ok})

    return results


def find_bad_regions(results: list, interval: float = VERIFY_INTERVAL
                     ) -> list:
    """Find contiguous bad regions from dense verify results.

    Returns list of (start_sec, end_sec) tuples where sync is bad.
    """
    bad = [r for r in results
           if not r["ok"] and r["offset_error"] is not None]
    if not bad:
        return []

    regions = []
    for r in bad:
        start = max(0, r["time"] - interval / 2)
        end = r["time"] + interval / 2
        if regions and start <= regions[-1][1] + interval:
            # Merge with previous
            regions[-1] = (regions[-1][0], end)
        else:
            regions.append((start, end))

    return regions


def silence_bad_regions(
    wav_path: Path,
    bad_regions: list,
    log_f=None,
) -> bool:
    """Replace bad regions in WAV file with silence using ffmpeg.

    Args:
        wav_path: Path to the synced WAV file to patch.
        bad_regions: List of (start_sec, end_sec) tuples.

    Returns True if successful.
    """
    if not bad_regions or not wav_path.exists():
        return True

    # Build ffmpeg volume filter: mute bad regions
    # volume=enable='between(t,S1,E1)+between(t,S2,E2)':volume=0
    conditions = "+".join(
        f"between(t\\,{s:.3f}\\,{e:.3f})" for s, e in bad_regions)
    af = f"volume=enable='{conditions}':volume=0"

    tmp_path = wav_path.with_suffix(".tmp.wav")
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(wav_path),
        "-af", af,
        "-c:a", "pcm_s24le",
        str(tmp_path),
    ]

    rc = subprocess.run(cmd, capture_output=True).returncode
    if rc != 0:
        tmp_path.unlink(missing_ok=True)
        _log(log_f, f"    [ENFORCE] ✗ Failed to silence bad regions")
        return False

    # Replace original
    tmp_path.replace(wav_path)
    total_silenced = sum(e - s for s, e in bad_regions)
    _log(log_f,
        f"    [ENFORCE] ✓ Silenced {len(bad_regions)} region(s) "
        f"({total_silenced:.1f}s) in {wav_path.name}")
    return True


def resync_clip(
    clip: dict,
    tx: str,
    dji_wavs: list,
    cam_wav: Path,
    output_path: Path,
    global_correction: float,
    log_f=None,
) -> bool:
    """Try per-clip fine-sync when global correction produces drift.

    1. Find DJI WAV overlapping this clip (using metadata only, no correction)
    2. Correlate camera audio vs DJI audio for THIS clip
    3. If confident, re-trim with per-clip correction
    4. Return True if re-synced successfully.
    """
    from copy import deepcopy

    # Find overlapping DJI WAV for this clip (uncorrected first)
    segments = find_overlapping_wavs(clip, dji_wavs)
    if not segments:
        return False

    first_dji = segments[0]["wav"]["path"]
    rough = segments[0]["trim_start"]

    _log(log_f, f"    [RESYNC] Per-clip fine-sync: {clip['clip_id']} × {tx}")
    _log(log_f, f"    [RESYNC] DJI: {first_dji.name}, rough={rough:.3f}s")

    refined, conf = find_fine_offset(
        cam_wav, first_dji, rough,
        analysis_dur=min(60.0, clip["duration"]),
        search_window=20.0,
        log_f=log_f)

    if conf < 3.0:
        _log(log_f,
            f"    [RESYNC] ✗ Low confidence ({conf:.1f}) — cannot re-sync")
        return False

    per_clip_correction = refined - rough
    _log(log_f,
        f"    [RESYNC] Per-clip correction: {per_clip_correction:+.3f}s "
        f"(was global: {global_correction:+.3f}s)")

    # Apply per-clip correction to DJI timestamps
    corrected_wavs = []
    for w in dji_wavs:
        wc = deepcopy(w)
        wc["creation_utc"] = (w["creation_utc"]
                              - timedelta(seconds=per_clip_correction))
        corrected_wavs.append(wc)

    # Re-find overlapping segments with per-clip correction
    new_segments = find_overlapping_wavs(clip, corrected_wavs)
    if not new_segments:
        _log(log_f, f"    [RESYNC] ✗ No overlap after per-clip correction")
        return False

    # Calculate gaps
    seg_gaps = []
    for si in range(1, len(new_segments)):
        prev_end = (new_segments[si-1]["wav"]["creation_utc"]
                    + timedelta(seconds=new_segments[si-1]["trim_start"]
                                + new_segments[si-1]["trim_duration"]))
        curr_start = (new_segments[si]["wav"]["creation_utc"]
                      + timedelta(seconds=new_segments[si]["trim_start"]))
        gap = (curr_start - prev_end).total_seconds()
        seg_gaps.append(max(0, gap))

    # Re-trim
    cmd = build_ffmpeg_cmd(
        new_segments, output_path,
        gaps=seg_gaps if seg_gaps else None,
        target_duration=clip["duration"])

    rc = subprocess.run(cmd, capture_output=True).returncode
    if rc != 0 or not output_path.exists():
        _log(log_f, f"    [RESYNC] ✗ ffmpeg failed")
        return False

    _log(log_f,
        f"    [RESYNC] ✓ Re-synced {output_path.name} "
        f"(correction: {per_clip_correction:+.3f}s)")
    return True


# ============================================================================
# Sync logic
# ============================================================================

def find_overlapping_wavs(clip: dict, wavs: list[dict]) -> list[dict]:
    """Find DJI WAV files that overlap with the clip's time range.

    Returns:
        List of dicts: [{wav, trim_start, trim_duration}, ...]
    """
    clip_start = clip["creation_utc"]
    clip_end = clip_start + timedelta(seconds=clip["duration"])
    segments = []

    for wav in wavs:
        wav_start = wav["creation_utc"]
        wav_end = wav_start + timedelta(seconds=wav["duration"])

        # Overlap?
        overlap_start = max(clip_start, wav_start)
        overlap_end = min(clip_end, wav_end)

        if overlap_start < overlap_end:
            trim_start = (overlap_start - wav_start).total_seconds()
            trim_duration = (overlap_end - overlap_start).total_seconds()
            segments.append({
                "wav": wav,
                "trim_start": trim_start,
                "trim_duration": trim_duration,
            })

    # Sort by overlap start time
    segments.sort(key=lambda s: s["wav"]["creation_utc"])
    return segments


def build_ffmpeg_cmd(segments: list[dict], output_path: Path,
                     gaps: list[float] | None = None,
                     target_duration: float | None = None) -> list[str]:
    """Build ffmpeg command using atrim filter for sample-accurate trim.

    Always re-encodes to pcm_s24le (lossless, 24-bit).
    Never uses -c copy (not sample-accurate for WAV seeking).

    If target_duration is set and audio is shorter, pads with silence
    at the end so output exactly matches video duration.

    Args:
        segments: List of segment dicts (can be empty for silence-only).
        output_path: Where to save output.
        gaps: Gap durations between consecutive segments. >2s filled with silence.
        target_duration: Target output duration (seconds). Pads silence at end.
    """
    sample_rate = (segments[0]["wav"]["sample_rate"]
                   if segments else 48000)
    bits = (segments[0]["wav"]["bits_per_sample"]
            if segments else 24)
    num_channels = 1  # DJI mono
    ch_layout = "mono" if num_channels == 1 else "stereo"

    inputs = []
    filter_parts = []
    concat_inputs = []
    silence_idx = 0
    total_audio = 0.0

    for i, seg in enumerate(segments):
        inputs.extend(["-i", str(seg["wav"]["path"])])
        label = f"a{i}"
        # Defensive clamp: don't let atrim exceed file duration
        trim_end = seg["trim_start"] + seg["trim_duration"]
        if seg["wav"].get("duration"):
            trim_end = min(trim_end, seg["wav"]["duration"])
        filter_parts.append(
            f"[{i}]atrim=start={seg['trim_start']:.6f}:"
            f"end={trim_end:.6f},"
            f"asetpts=N/SR/TB[{label}]"
        )
        concat_inputs.append(f"[{label}]")
        total_audio += trim_end - seg["trim_start"]

        # Insert silence pad for REAL gaps (> 2s) between segments
        # Small gaps from DJI auto-split are already snapped to 0
        if gaps and i < len(gaps) and gaps[i] > 2.0:
            sil_label = f"sil{silence_idx}"
            filter_parts.append(
                f"anullsrc=channel_layout={ch_layout}:"
                f"sample_rate={sample_rate},"
                f"atrim=duration={gaps[i]:.6f},"
                f"asetpts=N/SR/TB[{sil_label}]"
            )
            concat_inputs.append(f"[{sil_label}]")
            total_audio += gaps[i]
            silence_idx += 1

    # Pad silence at end to match target_duration (video length)
    if target_duration and target_duration - total_audio > 0.01:
        pad = target_duration - total_audio
        sil_label = f"sil{silence_idx}"
        filter_parts.append(
            f"anullsrc=channel_layout={ch_layout}:"
            f"sample_rate={sample_rate},"
            f"atrim=duration={pad:.6f},"
            f"asetpts=N/SR/TB[{sil_label}]"
        )
        concat_inputs.append(f"[{sil_label}]")

    n = len(concat_inputs)
    if n == 0:
        # Fully silent file (no DJI segments at all)
        dur = target_duration or 1.0
        filter_str = (
            f"anullsrc=channel_layout={ch_layout}:"
            f"sample_rate={sample_rate},"
            f"atrim=duration={dur:.6f},"
            f"asetpts=N/SR/TB[out]"
        )
    elif target_duration and total_audio > target_duration + 0.001:
        # Truncate to exact video duration (multi-segment overshoot)
        filter_str = (
            ";".join(filter_parts)
            + f";{''.join(concat_inputs)}concat=n={n}:v=0:a=1[raw]"
            f";[raw]atrim=end={target_duration:.6f},"
            f"asetpts=N/SR/TB[out]"
        )
    else:
        filter_str = (
            ";".join(filter_parts)
            + f";{''.join(concat_inputs)}concat=n={n}:v=0:a=1[out]"
        )

    codec = f"pcm_s{bits}le"

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",
        "-y",
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-c:a", codec,
        "-ar", str(sample_rate),
        str(output_path),
    ]


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="YTAI: Sync DJI audio with camera video clips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    export PROJECT="$HOME/YTAI/scripts/05_editing/999_testing_project/YTCG37_Setup_UAE_Company_Remotely"

    source ~/YTAI/environment/.venv_transcribe/bin/activate && \\
      python3 %(prog)s --project "$PROJECT"                     # auto-detect TZ

    source ~/YTAI/environment/.venv_transcribe/bin/activate && \\
      python3 %(prog)s --project "$PROJECT" --tz-offset 4       # explicit TZ

    source ~/YTAI/environment/.venv_transcribe/bin/activate && \\
      python3 %(prog)s --project "$PROJECT" --dry-run           # preview only
        """
    )
    ap.add_argument("--project", required=True,
                   help="Path to the project folder")
    ap.add_argument("--tz-offset", type=float, default=None,
                   help="Timezone offset (UTC+N). Auto-detected if omitted. "
                        "Example: 4 for Dubai, 3 for Moscow")
    ap.add_argument("--clips-dir", default=CLIPS_SUBDIR,
                   help=f'Folder with video clips (default: "{CLIPS_SUBDIR}")')
    ap.add_argument("--dji-dir", default=DJI_SUBDIR,
                   help=f'Folder with DJI WAV files (default: "{DJI_SUBDIR}")')
    ap.add_argument("--out-dir", default=AUDIO_SUBDIR,
                   help=f'Output folder (default: "{AUDIO_SUBDIR}")')
    ap.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing files")
    ap.add_argument("--dry-run", action="store_true",
                   help="Show what would be done without executing")
    ap.add_argument("--verbose", action="store_true",
                   help="Show ffmpeg output")
    args = ap.parse_args()

    # ---- Validate paths ----
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project folder not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    if not ffmpeg_exists():
        print("ERROR: ffprobe/ffmpeg not found. Install with: brew install ffmpeg",
              file=sys.stderr)
        sys.exit(1)

    clips_dir = (project_dir / args.clips_dir).resolve()
    if not clips_dir.exists():
        print(f"ERROR: Video clips folder not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    dji_dir = (project_dir / args.dji_dir).resolve()
    if not dji_dir.exists():
        print(f"ERROR: DJI WAV folder not found: {dji_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = (project_dir / LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # ---- Gather data ----
    video_files = sorted(
        [p for p in clips_dir.rglob("*")
         if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name)
    )
    dji_files = sorted(
        [p for p in dji_dir.iterdir()
         if p.is_file() and p.suffix in WAV_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name)
    )

    # Build clip_id → video path map and clip_id → scene map
    video_path_map: dict[str, Path] = {}
    clip_scene_map: dict[str, str] = {}
    for vf in video_files:
        video_path_map[vf.stem] = vf
        # Check if video is inside a scene subfolder (e.g. 01_Interview/)
        try:
            rel = vf.parent.relative_to(clips_dir)
            top = rel.parts[0] if rel.parts else None
            if top and SCENE_DIR_RE.match(top):
                clip_scene_map[vf.stem] = top
        except ValueError:
            pass

    if not video_files:
        print(f"ERROR: No video clips found in: {clips_dir}", file=sys.stderr)
        sys.exit(1)
    if not dji_files:
        print(f"ERROR: No DJI WAV files found in: {dji_dir}", file=sys.stderr)
        sys.exit(1)

    # ---- Logging ----
    project_name = project_dir.name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{project_name}_sync_dji_audio_{ts}.log"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}  YTAI: DJI AUDIO SYNC{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")
        tee_print(log_f, f"  {DIM}Timestamp{RST}  : {ts}")
        tee_print(log_f, f"  {DIM}Project{RST}    : {BOLD}{project_name}{RST}")
        tee_print(log_f, f"  {DIM}Video{RST}      : {clips_dir} ({len(video_files)} files)")
        tee_print(log_f, f"  {DIM}DJI WAV{RST}    : {dji_dir} ({len(dji_files)} files)")
        tee_print(log_f, f"  {DIM}Output{RST}     : {out_dir}")

        if args.dry_run:
            tee_print(log_f, "")
            tee_print(log_f, f"  {BOLD}{YELLOW}*** DRY-RUN MODE ***{RST}")

        # ============================================================
        # PHASE 0: Resolve timezone offset
        # ============================================================
        tz_offset = args.tz_offset

        # Pre-fetch metadata (reused in Phase 1 to avoid double ffprobe)
        clips = []
        for vf in video_files:
            try:
                clips.append(get_video_clip_info(vf))
            except Exception as e:
                tee_print(log_f, f"  ✗ {vf.name}: {e}")

        raw_wavs = []
        for df in dji_files:
            try:
                raw_wavs.append(get_dji_wav_info_raw(df))
            except Exception as e:
                tee_print(log_f, f"  ✗ {df.name}: {e}")

        if tz_offset is None:
            tee_print(log_f, "")
            tee_print(log_f,
                f"{BOLD}{MAGENTA}AUTO-DETECTING TIMEZONE{RST}")
            tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
            detected, count, total = auto_detect_tz_offset(clips, raw_wavs)
            if detected is not None:
                tz_offset = detected
                sign = "+" if tz_offset >= 0 else ""
                tee_print(log_f,
                    f"  Detected : UTC{sign}{tz_offset:g}  "
                    f"({count}/{total} DJI files overlap with video)")
            else:
                tee_print(log_f, "  ✗ Cannot auto-detect timezone")
                tee_print(log_f, "    No time overlap found between DJI and video.")
                tee_print(log_f, "    Pass --tz-offset manually:")
                tee_print(log_f, "      --tz-offset 4   (Dubai, UTC+4)")
                tee_print(log_f, "      --tz-offset 3   (Moscow, UTC+3)")
                sys.exit(1)

        sign = "+" if tz_offset >= 0 else ""
        tee_print(log_f, f"TZ offset  : UTC{sign}{tz_offset:g}")
        tee_print(log_f, f"Log        : {log_path}")
        tee_print(log_f, "")

        # ============================================================
        # PHASE 1: Collect metadata (using resolved tz_offset)
        # ============================================================
        tee_print(log_f,
            f"{BOLD}{MAGENTA}PHASE 1: Collecting metadata{RST}")
        tee_print(log_f, f"{DIM}{'-' * 60}{RST}")

        for info in clips:
            tee_print(log_f,
                f"  Video: {info['path'].name}  "
                f"dur={format_duration(info['duration'])}  "
                f"created={info['creation_utc'].strftime('%H:%M:%S') if info['creation_utc'] else '?'} UTC"
            )

        # Convert raw DJI data using resolved tz_offset
        dji_wavs = []
        for raw in raw_wavs:
            creation_utc = None
            if raw["local_naive"] is not None:
                local_tz = timezone(timedelta(hours=tz_offset))
                local_dt = raw["local_naive"].replace(tzinfo=local_tz)
                creation_utc = local_dt.astimezone(timezone.utc)
            info = dict(raw)
            del info["local_naive"]
            info["creation_utc"] = creation_utc
            dji_wavs.append(info)
            tee_print(log_f,
                f"  DJI:   {raw['path'].name}  "
                f"dur={format_duration(raw['duration'])}  "
                f"created={creation_utc.strftime('%H:%M:%S') if creation_utc else '?'} UTC  "
                f"tx={raw['tx_id']}  "
                f"{raw['bits_per_sample']}bit/{raw['sample_rate']}Hz"
            )

        tee_print(log_f, "")

        # Check that all entries have timestamps
        clips_ok = [c for c in clips if c["creation_utc"] is not None]
        wavs_ok = [w for w in dji_wavs if w["creation_utc"] is not None]

        if not clips_ok:
            tee_print(log_f, "ERROR: No video clips contain creation_time!")
            sys.exit(1)
        if not wavs_ok:
            tee_print(log_f, "ERROR: No DJI WAV files contain creation_time!")
            sys.exit(1)

        if len(clips_ok) < len(clips):
            tee_print(log_f,
                f"WARNING: {len(clips) - len(clips_ok)} video(s) without creation_time -- skipped")
        if len(wavs_ok) < len(dji_wavs):
            tee_print(log_f,
                f"WARNING: {len(dji_wavs) - len(wavs_ok)} DJI WAV(s) without creation_time -- skipped")

        # Group DJI files by transmitter
        dji_by_tx: dict[str, list[dict]] = {}
        for wav in wavs_ok:
            tx = wav["tx_id"]
            dji_by_tx.setdefault(tx, []).append(wav)
        # Sort by time within each group
        for tx in dji_by_tx:
            dji_by_tx[tx].sort(key=lambda w: w["creation_utc"])

        tx_ids = sorted(dji_by_tx.keys())
        tee_print(log_f, f"Transmitters: {', '.join(tx_ids)}")
        for tx in tx_ids:
            tee_print(log_f, f"  {tx}: {len(dji_by_tx[tx])} file(s)")
        tee_print(log_f, "")

        # ============================================================
        # PHASE 1.5: Fine sync via cross-correlation
        # ============================================================
        per_clip_dir = (project_dir / "01_Media" / "Source"
                        / "Transcription" / "per_clip")
        sync_correction = {}  # {tx_id: correction_sec}

        # Find correction from the longest clip (most reliable)
        longest_clip = max(clips_ok, key=lambda c: c["duration"])
        camera_wav = (per_clip_dir / longest_clip["clip_id"]
                      / f"{longest_clip['clip_id']}_AUDIO.wav")

        # Fallback: use MP4 video directly if per_clip WAV not available
        if not camera_wav.exists():
            camera_wav = _find_video_path(
                longest_clip['clip_id'], video_path_map, clips_dir)
            if camera_wav is None:
                camera_wav = clips_dir / f"{longest_clip['clip_id']}.MP4"

        if camera_wav.exists() and not args.dry_run:
            tee_print(log_f,
                f"{BOLD}{MAGENTA}FINE SYNC: Cross-correlation{RST}")
            tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
            tee_print(log_f,
                f"  [INFO] Reference clip: {longest_clip['clip_id']} "
                f"({format_duration(longest_clip['duration'])})")
            tee_print(log_f,
                f"  [INFO] Camera audio: {camera_wav.name}")
            tee_print(log_f,
                f"  [INFO] Source: "
                f"{'per_clip WAV' if camera_wav.suffix.lower() == '.wav' else 'MP4 video'}")
            tee_print(log_f, "")

            for tx in tx_ids:
                tee_print(log_f, f"  === {tx} ===")
                ref_segments = find_overlapping_wavs(
                    longest_clip, dji_by_tx[tx])
                if not ref_segments:
                    tee_print(log_f, f"  [SKIP] No overlap with {tx}")
                    continue

                rough = ref_segments[0]["trim_start"]
                tee_print(log_f,
                    f"  [INFO] DJI file: "
                    f"{ref_segments[0]['wav']['path'].name}")
                tee_print(log_f,
                    f"  [INFO] Metadata offset: {rough:.3f}s")

                refined, conf = find_fine_offset(
                    camera_wav, ref_segments[0]["wav"]["path"],
                    rough, analysis_dur=60.0, search_window=10.0,
                    log_f=log_f)

                correction = refined - rough

                if conf < 3.0:
                    tee_print(log_f,
                        f"  [WARN] Confidence too low ({conf:.1f} < 3.0)"
                        f" — not applying correction")
                    tee_print(log_f,
                        f"  [WARN] Using metadata offset: {rough:.3f}s")
                else:
                    sync_correction[tx] = correction
                    tee_print(log_f,
                        f"  [OK] Correction: {correction:+.3f}s "
                        f"(confidence={conf:.1f})")
                tee_print(log_f, "")
        elif not args.dry_run:
            tee_print(log_f,
                f"{DIM}FINE SYNC: Skipped{RST}")
            tee_print(log_f,
                f"  [SKIP] Camera audio not found: {camera_wav}")
            tee_print(log_f,
                "  [SKIP] Using metadata-only sync")
            tee_print(log_f, "")

        # ============================================================
        # Apply corrections to DJI timestamps BEFORE overlap calc
        # ============================================================
        dji_by_tx_corrected = {}
        if sync_correction:
            tee_print(log_f,
                f"{BOLD}{MAGENTA}TIMESTAMP CORRECTION{RST}")
            tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
        for tx in tx_ids:
            corr = sync_correction.get(tx, 0.0)
            if corr != 0.0:
                tee_print(log_f,
                    f"  {tx}: correction={corr:+.3f}s "
                    f"→ DJI timestamps shifted by {-corr:+.3f}s")
                corrected = []
                for wav in dji_by_tx[tx]:
                    w = dict(wav)
                    orig_utc = wav["creation_utc"]
                    w["creation_utc"] = orig_utc - timedelta(seconds=corr)
                    tee_print(log_f,
                        f"    {wav['path'].name}: "
                        f"{orig_utc.strftime('%H:%M:%S.%f')[:-3]} UTC → "
                        f"{w['creation_utc'].strftime('%H:%M:%S.%f')[:-3]} UTC")
                    corrected.append(w)
                dji_by_tx_corrected[tx] = corrected
            else:
                dji_by_tx_corrected[tx] = dji_by_tx[tx]
        if sync_correction:
            tee_print(log_f, "")

        # ============================================================
        # Snap auto-split DJI files (continuous recording across files)
        # ============================================================
        # DJI mics auto-split every ~30 min. The timestamp gap between
        # files is a file-creation artifact, NOT a real silence gap.
        # Snapping eliminates the fake gap so segments concatenate
        # seamlessly without drift.
        AUTO_SPLIT_DUR = 1790.0  # first file must be ~30 min
        AUTO_SPLIT_GAP_MAX = 5.0  # max gap to consider as auto-split

        for tx in tx_ids:
            files = dji_by_tx_corrected[tx]
            if len(files) < 2:
                continue
            files.sort(key=lambda w: w["creation_utc"])
            snapped = False
            for i in range(1, len(files)):
                prev = files[i - 1]
                cur = files[i]
                prev_end = (prev["creation_utc"]
                            + timedelta(seconds=prev["duration"]))
                gap = (cur["creation_utc"] - prev_end).total_seconds()
                # Auto-split: previous file is ~30 min AND gap is small
                if (prev["duration"] >= AUTO_SPLIT_DUR
                        and 0 < gap < AUTO_SPLIT_GAP_MAX):
                    old_ts = cur["creation_utc"]
                    cur["creation_utc"] = prev_end
                    if not snapped:
                        tee_print(log_f,
                            f"{BOLD}{MAGENTA}AUTO-SPLIT SNAP{RST}")
                        tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
                        snapped = True
                    tee_print(log_f,
                        f"  {tx}: {cur['path'].name} snapped "
                        f"{old_ts.strftime('%H:%M:%S.%f')[:-3]} → "
                        f"{cur['creation_utc'].strftime('%H:%M:%S.%f')[:-3]} "
                        f"UTC (gap {gap:.3f}s → 0.000s)")
            if snapped:
                tee_print(log_f, "")

        # ============================================================
        # PHASE 2: Sync and trim (per-clip fine-sync)
        # ============================================================
        tee_print(log_f,
            f"{BOLD}{MAGENTA}PHASE 2: Sync and trim{RST}")
        tee_print(log_f, f"{DIM}{'-' * 60}{RST}")

        success_count = 0
        skip_count = 0
        fail_count = 0
        no_overlap_count = 0
        no_overlap_clips = []  # [{clip_id, tx, scene, duration}]
        total_size = 0
        output_durations = {}  # {(clip_id, tx): duration_sec}

        for clip in clips_ok:
            # --- Per-clip camera audio ---
            clip_cam_wav = (per_clip_dir / clip["clip_id"]
                            / f"{clip['clip_id']}_AUDIO.wav")
            if not clip_cam_wav.exists():
                clip_cam_wav = _find_video_path(
                    clip['clip_id'], video_path_map, clips_dir)
                if clip_cam_wav is None:
                    clip_cam_wav = clips_dir / f"{clip['clip_id']}.MP4"

            for tx in tx_ids:
                output_name = f"{clip['clip_id']}_{tx}.wav"
                clip_out_dir = _scene_out_dir(
                    clip['clip_id'], clip_scene_map, out_dir)
                output_path = clip_out_dir / output_name

                # Skip if already exists
                if output_path.exists() and not args.overwrite:
                    size = output_path.stat().st_size
                    if size >= MIN_OK_BYTES:
                        tee_print(log_f,
                            f"  {clip['clip_id']} × {tx} → SKIP (already exists)")
                        skip_count += 1
                        total_size += size
                        continue

                # --- Per-clip fine-sync ---
                # Start from global-corrected timestamps, then refine
                # per-clip if camera audio is available
                clip_dji_wavs = dji_by_tx_corrected[tx]
                global_corr = sync_correction.get(tx, 0.0)

                if (clip_cam_wav.exists() and not args.dry_run
                        and clip["clip_id"] != longest_clip["clip_id"]):
                    # Find overlapping DJI for this clip (global correction)
                    ref_segs = find_overlapping_wavs(
                        clip, clip_dji_wavs)
                    if ref_segs:
                        rough = ref_segs[0]["trim_start"]
                        refined, conf = find_fine_offset(
                            clip_cam_wav,
                            ref_segs[0]["wav"]["path"],
                            rough,
                            analysis_dur=min(60.0, clip["duration"]),
                            search_window=20.0,
                            log_f=log_f)
                        if conf >= 3.0:
                            per_clip_corr = refined - rough
                            delta = per_clip_corr - global_corr
                            if abs(delta) > 0.1:
                                tee_print(log_f,
                                    f"  [PER-CLIP] {clip['clip_id']} × {tx}: "
                                    f"correction={per_clip_corr:+.3f}s "
                                    f"(global was {global_corr:+.3f}s, "
                                    f"Δ={delta:+.3f}s)")
                                # Re-correct DJI timestamps for this clip
                                from copy import deepcopy
                                clip_dji_wavs = []
                                for w in dji_by_tx[tx]:
                                    wc = deepcopy(w)
                                    wc["creation_utc"] = (
                                        w["creation_utc"]
                                        - timedelta(seconds=per_clip_corr))
                                    clip_dji_wavs.append(wc)
                                # Re-apply auto-split snap
                                clip_dji_wavs.sort(
                                    key=lambda w: w["creation_utc"])
                                for i in range(1, len(clip_dji_wavs)):
                                    prev = clip_dji_wavs[i - 1]
                                    cur = clip_dji_wavs[i]
                                    prev_end = (
                                        prev["creation_utc"]
                                        + timedelta(
                                            seconds=prev["duration"]))
                                    gap = (cur["creation_utc"]
                                           - prev_end).total_seconds()
                                    if (prev["duration"] >= AUTO_SPLIT_DUR
                                            and 0 < gap
                                            < AUTO_SPLIT_GAP_MAX):
                                        cur["creation_utc"] = prev_end

                # Find overlapping WAV files
                segments = find_overlapping_wavs(
                    clip, clip_dji_wavs)

                if not segments:
                    tee_print(log_f,
                        f"  {clip['clip_id']} × {tx} → no overlap with DJI")
                    no_overlap_count += 1
                    no_overlap_clips.append({
                        "clip_id": clip["clip_id"],
                        "tx": tx,
                        "scene": clip_scene_map.get(clip["clip_id"], ""),
                        "duration": clip["duration"],
                    })
                    continue

                # Detailed segment logging
                clip_end_utc = (clip["creation_utc"]
                                + timedelta(seconds=clip["duration"]))
                corr = sync_correction.get(tx, 0.0)

                tee_print(log_f, f"  {clip['clip_id']} × {tx}:")
                tee_print(log_f,
                    f"    [DEBUG] Clip: "
                    f"{clip['creation_utc'].strftime('%H:%M:%S')} → "
                    f"{clip_end_utc.strftime('%H:%M:%S')} UTC "
                    f"({clip['duration']:.2f}s)")
                if corr != 0.0:
                    tee_print(log_f,
                        f"    [DEBUG] Correction: {corr:+.3f}s "
                        f"(DJI shifted {-corr:+.3f}s)")

                total_covered = 0.0
                total_gaps = 0.0
                seg_gaps = []  # gap durations between consecutive segs
                for si, seg in enumerate(segments):
                    wav = seg["wav"]
                    wav_end_utc = (wav["creation_utc"]
                                   + timedelta(seconds=wav["duration"]))
                    trim_end = seg["trim_start"] + seg["trim_duration"]
                    overflow = trim_end > wav["duration"] + 0.01

                    tee_print(log_f,
                        f"    [DEBUG] Seg {si}: {wav['path'].name}  "
                        f"WAV={wav['creation_utc'].strftime('%H:%M:%S.%f')[:-3]}"
                        f"→{wav_end_utc.strftime('%H:%M:%S.%f')[:-3]}  "
                        f"trim={seg['trim_start']:.3f}→{trim_end:.3f} "
                        f"({seg['trim_duration']:.2f}s)  "
                        f"file_dur={wav['duration']:.2f}s  "
                        f"{'⚠ OVERFLOW' if overflow else '✓'}")
                    if overflow:
                        tee_print(log_f,
                            f"    [WARN] trim_end ({trim_end:.3f}s) > "
                            f"file duration ({wav['duration']:.3f}s) — "
                            f"overflow {trim_end - wav['duration']:.3f}s!")

                    # Check gap between segments
                    if si > 0:
                        prev = segments[si - 1]
                        prev_wav_end = (prev["wav"]["creation_utc"]
                                        + timedelta(
                                            seconds=prev["trim_start"]
                                            + prev["trim_duration"]))
                        cur_wav_start = (wav["creation_utc"]
                                         + timedelta(
                                             seconds=seg["trim_start"]))
                        gap = (cur_wav_start - prev_wav_end).total_seconds()
                        seg_gaps.append(max(gap, 0.0))
                        if gap > 2.0:
                            tee_print(log_f,
                                f"    [DEBUG] Gap seg {si-1}→{si}: "
                                f"{gap:.3f}s (filled with silence)"
                                f"  ⚠ LARGE GAP")
                            total_gaps += gap
                        elif gap > 0.01:
                            tee_print(log_f,
                                f"    [DEBUG] Gap seg {si-1}→{si}: "
                                f"{gap:.3f}s (seamless)")
                            # Small gaps from auto-split snap: don't pad

                    total_covered += seg["trim_duration"]

                total_with_gaps = total_covered + total_gaps
                coverage_pct = (total_with_gaps / clip["duration"]) * 100
                tee_print(log_f,
                    f"    [DEBUG] Total: "
                    f"{format_duration(total_with_gaps)} / "
                    f"{format_duration(clip['duration'])} "
                    f"({coverage_pct:.1f}%)"
                    f"{f'  (gaps: {total_gaps:.3f}s silence)' if total_gaps > 0 else ''}")

                if args.dry_run:
                    tee_print(log_f, f"    → {output_name} (dry-run)")
                    success_count += 1
                    continue

                # Build and run ffmpeg (sample-accurate, pad to video duration)
                cmd = build_ffmpeg_cmd(
                    segments, output_path,
                    gaps=seg_gaps if seg_gaps else None,
                    target_duration=clip["duration"])

                if args.verbose:
                    tee_print(log_f, f"    cmd: {' '.join(shlex.quote(a) for a in cmd)}")

                rc = run_ffmpeg(cmd, log_f, verbose=args.verbose)

                if rc != 0 or not output_path.exists() or output_path.stat().st_size < MIN_OK_BYTES:
                    tee_print(log_f, f"    ✗ ERROR!")
                    fail_count += 1
                    if output_path.exists():
                        output_path.unlink()
                else:
                    size = output_path.stat().st_size
                    total_size += size
                    tee_print(log_f,
                        f"    ✓ {output_name} ({format_size(size)})")
                    # Validate output duration
                    try:
                        probe = subprocess.run(
                            ["ffprobe", "-v", "error",
                             "-show_entries", "format=duration",
                             "-of", "csv=p=0",
                             str(output_path)],
                            capture_output=True, text=True)
                        out_dur = float(probe.stdout.strip())
                        expected_dur = clip["duration"]
                        delta = abs(out_dur - expected_dur)
                        output_durations[
                            (clip["clip_id"], tx)] = out_dur
                        status = "✓" if delta < 0.5 else "⚠ MISMATCH"
                        tee_print(log_f,
                            f"    [VERIFY] Output: {out_dur:.3f}s  "
                            f"Expected: {expected_dur:.3f}s  "
                            f"Δ={delta:.3f}s  {status}")
                    except Exception:
                        pass
                    success_count += 1

        # ============================================================
        # PHASE 3: Sync verification (30s windows, reliable)
        # ============================================================
        phase3_summary = {}  # {tx: max_error_sec}
        removed_count = 0

        if (success_count > 0 and not args.dry_run
                and per_clip_dir.exists()):
            tee_print(log_f, "")
            tee_print(log_f,
                f"{BOLD}{MAGENTA}PHASE 3: Sync Verification{RST}")
            tee_print(log_f, f"{DIM}{'-' * 60}{RST}")

            for clip in clips_ok:
                cam_wav = (per_clip_dir / clip["clip_id"]
                           / f"{clip['clip_id']}_AUDIO.wav")
                if not cam_wav.exists():
                    cam_wav = _find_video_path(
                        clip['clip_id'], video_path_map, clips_dir)
                if not cam_wav or not cam_wav.exists():
                    continue

                for tx in tx_ids:
                    clip_out = _scene_out_dir(
                        clip['clip_id'], clip_scene_map, out_dir)
                    out_path = clip_out / f"{clip['clip_id']}_{tx}.wav"
                    if not out_path.exists():
                        continue

                    dur = clip["duration"]
                    if dur < 30:
                        tee_print(log_f,
                            f"  {clip['clip_id']} × {tx}: "
                            f"skip (too short {dur:.0f}s)")
                        continue

                    # Check every 60s with 30s analysis windows
                    verify_window = 30.0
                    pts = [5.0]
                    t = 60.0
                    while t + verify_window + 5.0 < dur:
                        pts.append(t)
                        t += 60.0
                    pts = sorted(set(pts))

                    tee_print(log_f,
                        f"  {clip['clip_id']} × {tx}: "
                        f"{len(pts)} check points")

                    results = verify_sync_quality(
                        cam_wav, out_path, pts,
                        analysis_dur=verify_window, log_f=log_f)

                    valid = [r for r in results
                             if r["offset_error"] is not None]
                    if valid:
                        max_err = max(
                            abs(r["offset_error"]) for r in valid)
                        avg_err = (sum(abs(r["offset_error"])
                                       for r in valid) / len(valid))
                        min_conf = min(
                            r["confidence"] for r in valid)

                        if max_err < MAX_DRIFT_SEC:
                            status = f"{GREEN}SYNC OK{RST}"
                        else:
                            status = f"{RED}⚠ DRIFT DETECTED{RST}"

                        tee_print(log_f,
                            f"    Summary: max_error={max_err:.3f}s  "
                            f"avg_error={avg_err:.3f}s  "
                            f"min_conf={min_conf:.1f}  [{status}]")

                        # Report drift details (informational only)
                        if max_err > MAX_DRIFT_SEC:
                            confident = [r for r in valid
                                         if r["confidence"] >= 3.0]
                            bad = [r for r in confident
                                   if abs(r["offset_error"])
                                   > MAX_DRIFT_SEC]
                            n_conf = len(confident)
                            tee_print(log_f,
                                f"    ⚠ {len(bad)}/{n_conf} "
                                f"confident points exceed "
                                f"{MAX_DRIFT_SEC}s (keeping file)")

                        prev = phase3_summary.get(tx, 0.0)
                        phase3_summary[tx] = max(prev, max_err)
                    tee_print(log_f, "")

            if removed_count:
                tee_print(log_f,
                    f"  Phase 3: {removed_count} file(s) removed "
                    f"due to drift")

        # ============================================================
        # PHASE 4: Generate Premiere Pro project for verification
        # ============================================================
        prproj_path = None
        xml_path = None
        if success_count > 0 and not args.dry_run:
            # Import generator module
            _gen_mod = None
            try:
                import generate_prproj as _gen_mod
            except ImportError:
                gen_path = Path(__file__).parent / "generate_prproj.py"
                if gen_path.exists():
                    import importlib.util
                    spec = importlib.util.spec_from_file_location(
                        "generate_prproj", gen_path)
                    _gen_mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(_gen_mod)

            if _gen_mod:
                tee_print(log_f, "")
                tee_print(log_f,
                    f"{BOLD}{MAGENTA}PHASE 4: Generate Premiere project{RST}")
                tee_print(log_f, f"{DIM}{'-' * 60}{RST}")

                dji_audio_dir = project_dir / "99_Pipeline" / "DJI_Audio"
                dji_audio_dir.mkdir(parents=True, exist_ok=True)
                prproj_name = (f"{project_code(project_dir)}"
                               f"_dji_sync_check.prproj")
                prproj_path = dji_audio_dir / prproj_name
                xml_path = prproj_path.with_suffix(".xml")

                # Check if we have scene folders → multi-scene mode
                has_scenes = any(
                    v for v in clip_scene_map.values() if v)

                if has_scenes:
                    # ── Multi-scene: one sequence per scene ──
                    scenes_data: dict[str, dict] = {}
                    for clip in clips_ok:
                        scene = clip_scene_map.get(
                            clip['clip_id'], '_unsorted')
                        if scene not in scenes_data:
                            scenes_data[scene] = {
                                "video_clips": [],
                                "dji_audio_clips": [],
                                "tx_ids": set(),
                            }
                        vpath = _find_video_path(
                            clip['clip_id'], video_path_map, clips_dir)
                        if vpath:
                            scenes_data[scene]["video_clips"].append({
                                "path": vpath,
                                "duration": clip["duration"],
                                "clip_id": clip["clip_id"],
                            })
                        for tx in tx_ids:
                            clip_out = _scene_out_dir(
                                clip['clip_id'], clip_scene_map,
                                out_dir)
                            apath = (clip_out
                                     / f"{clip['clip_id']}_{tx}.wav")
                            if apath.exists():
                                adur = output_durations.get(
                                    (clip["clip_id"], tx),
                                    clip["duration"])
                                scenes_data[scene][
                                    "dji_audio_clips"].append({
                                    "path": apath,
                                    "duration": adur,
                                    "clip_id": clip["clip_id"],
                                    "tx": tx,
                                })
                                scenes_data[scene]["tx_ids"].add(tx)

                    # Remove empty scenes
                    scenes_data = {
                        k: v for k, v in scenes_data.items()
                        if v["video_clips"]}

                    if scenes_data:
                        ok = _gen_mod.generate_multi_scene_prproj(
                            scenes_data, prproj_path)

                        if ok:
                            if prproj_path.exists():
                                tee_print(log_f,
                                    f"  {GREEN}✓{RST} "
                                    f"{prproj_path.name}"
                                    f"  {DIM}(Premiere project)"
                                    f"{RST}")
                            if xml_path.exists():
                                tee_print(log_f,
                                    f"  {GREEN}✓{RST} "
                                    f"{xml_path.name}"
                                    f"  {DIM}(FCP XML){RST}")
                            for sn in sorted(scenes_data.keys()):
                                sd = scenes_data[sn]
                                n_v = len(sd["video_clips"])
                                n_a = len(sd["dji_audio_clips"])
                                txs = sorted(sd["tx_ids"])
                                tee_print(log_f,
                                    f"    {DIM}Sequence "
                                    f"\"{sn}\": "
                                    f"{n_v} clips, "
                                    f"{n_a} DJI "
                                    f"({', '.join(txs)}){RST}")
                        else:
                            tee_print(log_f,
                                f"  {RED}✗ Failed to generate "
                                f"project{RST}")
                else:
                    # ── Legacy single-sequence mode ──
                    vc_list = []
                    for clip in clips_ok:
                        vpath = _find_video_path(
                            clip['clip_id'], video_path_map, clips_dir)
                        if vpath:
                            vc_list.append({
                                "path": vpath,
                                "duration": clip["duration"],
                                "clip_id": clip["clip_id"],
                            })

                    ac_list = []
                    for clip in clips_ok:
                        for tx in tx_ids:
                            clip_out = _scene_out_dir(
                                clip['clip_id'], clip_scene_map,
                                out_dir)
                            apath = (clip_out
                                     / f"{clip['clip_id']}_{tx}.wav")
                            if apath.exists():
                                adur = output_durations.get(
                                    (clip["clip_id"], tx),
                                    clip["duration"])
                                ac_list.append({
                                    "path": apath,
                                    "duration": adur,
                                    "clip_id": clip["clip_id"],
                                })

                    if vc_list:
                        ok = _gen_mod.generate_prproj(
                            vc_list, ac_list, prproj_path,
                            sequence_name="DJI Sync Check")

                        if ok:
                            if prproj_path.exists():
                                tee_print(log_f,
                                    f"  {GREEN}✓{RST} "
                                    f"{prproj_path.name}"
                                    f"  {DIM}(Premiere project)"
                                    f"{RST}")
                            if xml_path.exists():
                                tee_print(log_f,
                                    f"  {GREEN}✓{RST} "
                                    f"{xml_path.name}"
                                    f"  {DIM}(FCP XML sequence)"
                                    f"{RST}")
                            tee_print(log_f,
                                f"    {DIM}Sequence: "
                                f"\"DJI Sync Check\"{RST}")
                        else:
                            tee_print(log_f,
                                f"  {RED}✗ Failed to generate "
                                f"project{RST}")

        # ============================================================
        # FINAL SUMMARY (comprehensive, at the very end)
        # ============================================================
        FPS = 25
        BAR_W = 50
        _venv = (Path.home() / "YTAI" / "environment"
                 / ".venv_transcribe" / "bin" / "activate")
        _pipeline = (Path.home() / "YTAI" / "scripts"
                     / "run_pipeline.py")

        tee_print(log_f, "")
        tee_print(log_f, f"{BOLD}{CYAN}{'═' * 60}{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}  SUMMARY{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}{'═' * 60}{RST}")

        # ── Result counts ──
        tee_print(log_f, "")
        if success_count > 0:
            tee_print(log_f,
                f"  {GREEN}✓ Succeeded{RST}  : "
                f"{BOLD}{success_count}{RST}")
        if skip_count > 0:
            tee_print(log_f,
                f"  {YELLOW}⊘ Skipped{RST}    : {skip_count}")
        if no_overlap_count > 0:
            tee_print(log_f,
                f"  {YELLOW}○ No overlap{RST} : {no_overlap_count}")
        if fail_count > 0:
            tee_print(log_f,
                f"  {RED}✗ Errors{RST}     : {fail_count}")
        if not args.dry_run and total_size > 0:
            tee_print(log_f,
                f"  {DIM}Total size{RST}   : {format_size(total_size)}")

        # ── No-overlap clips detail ──
        if no_overlap_clips:
            # Deduplicate by clip_id (show once per clip, list TX channels)
            seen = {}
            for noc in no_overlap_clips:
                cid = noc["clip_id"]
                if cid not in seen:
                    seen[cid] = {
                        "scene": noc["scene"],
                        "duration": noc["duration"],
                        "tx_list": [noc["tx"]],
                    }
                else:
                    seen[cid]["tx_list"].append(noc["tx"])

            uncovered_dur = sum(v["duration"] for v in seen.values())
            tee_print(log_f, "")
            tee_print(log_f,
                f"{BOLD}{YELLOW}  Clips Without DJI Coverage "
                f"({len(seen)} clips, "
                f"{format_timecode(uncovered_dur, FPS)}){RST}")
            tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")
            tee_print(log_f,
                f"  {DIM}{'Clip':20s}  {'Scene':16s}  "
                f"{'Duration':>12s}  TX{RST}")
            for cid in sorted(seen):
                info = seen[cid]
                txs = ", ".join(info["tx_list"])
                scene = info["scene"] or "—"
                tee_print(log_f,
                    f"  {YELLOW}{cid:20s}{RST}  {scene:16s}  "
                    f"{format_timecode(info['duration'], FPS):>12s}  "
                    f"{txs}")
            tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")
            tee_print(log_f,
                f"  {DIM}Camera audio available in "
                f"Transcription/per_clip/ for these clips{RST}")

        # ── Video & Audio statistics ──
        tee_print(log_f, "")
        tee_print(log_f,
            f"{BOLD}{BLUE}  Media Statistics{RST}")
        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")

        # Video files
        total_video_size = 0
        total_video_dur = 0.0
        for clip in clips_ok:
            vpath = _find_video_path(
                clip['clip_id'], video_path_map, clips_dir)
            vsize = vpath.stat().st_size if vpath else 0
            total_video_size += vsize
            total_video_dur += clip["duration"]
            vsuffix = vpath.suffix if vpath else ".MP4"
            tee_print(log_f,
                f"  {CYAN}V{RST}  {clip['clip_id']}{vsuffix}  "
                f"{DIM}{format_size(vsize)}{RST}  "
                f"{format_timecode(clip['duration'], FPS)}")

        # DJI synced audio files
        total_audio_size = 0
        total_audio_dur = 0.0
        for clip in clips_ok:
            for tx in tx_ids:
                clip_out = _scene_out_dir(
                    clip['clip_id'], clip_scene_map, out_dir)
                apath = clip_out / f"{clip['clip_id']}_{tx}.wav"
                if apath.exists():
                    asize = apath.stat().st_size
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)
                    total_audio_size += asize
                    total_audio_dur += adur
                    tee_print(log_f,
                        f"  {GREEN}A{RST}  {apath.name}  "
                        f"{DIM}{format_size(asize)}{RST}  "
                        f"{format_timecode(adur, FPS)}")

        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")
        tee_print(log_f,
            f"  {BOLD}Video{RST}: {len(clips_ok)} clips  "
            f"{format_size(total_video_size)}  "
            f"{format_timecode(total_video_dur, FPS)}")
        tee_print(log_f,
            f"  {BOLD}Audio{RST}: {success_count} synced  "
            f"{format_size(total_audio_size)}  "
            f"{format_timecode(total_audio_dur, FPS)}")

        # ── Per-clip SYNC VISUALIZATION + TRACK COMPARISON ──
        if success_count > 0 and clips_ok:
            for tx in tx_ids:
                tee_print(log_f, "")
                tee_print(log_f,
                    f"{BOLD}{BLUE}  Sync Visualization ({tx}){RST}")
                tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")

                for clip in clips_ok:
                    vdur = clip["duration"]
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)

                    vtc = format_timecode(vdur, FPS)
                    atc = format_timecode(adur, FPS)
                    vframes = int(vdur * FPS)
                    aframes = int(adur * FPS)
                    frame_delta = abs(vframes - aframes)

                    tee_print(log_f,
                        f"  {BOLD}{clip['clip_id']}{RST} × {tx}:")

                    # V1 bar (always full, cyan)
                    v_bar = f"{CYAN}{'█' * BAR_W}{RST}"
                    tee_print(log_f,
                        f"    V1 |{v_bar}| {vtc}")

                    # A2 bar (green or red for missing)
                    if adur > 0 and vdur > 0:
                        ratio = min(adur / vdur, 1.0)
                        a_chars = max(1, int(ratio * BAR_W))
                        gap_chars = BAR_W - a_chars
                        if gap_chars > 0:
                            a_bar = (f"{GREEN}{'█' * a_chars}{RST}"
                                     f"{RED}{'░' * gap_chars}{RST}")
                            mark = f"{YELLOW}Δ={frame_delta}f ⚠{RST}"
                        else:
                            a_bar = f"{GREEN}{'█' * BAR_W}{RST}"
                            if frame_delta == 0:
                                mark = f"{GREEN}Δ=0f ✓{RST}"
                            else:
                                mark = f"{YELLOW}Δ={frame_delta}f ⚠{RST}"
                    else:
                        a_bar = f"{RED}{'░' * BAR_W}{RST}"
                        mark = f"{RED}MISSING ✗{RST}"
                    tee_print(log_f,
                        f"    A2 |{a_bar}| {atc}  {mark}")
                    tee_print(log_f, "")

                # ── TRACK COMPARISON table ──
                sep = f"  {DIM}{'─' * 68}{RST}"
                tee_print(log_f,
                    f"{BOLD}{BLUE}  Track Comparison ({FPS}fps){RST}")
                tee_print(log_f, sep)
                tee_print(log_f,
                    f"  {BOLD}{'Clip':20s}  {'V1 (video)':>14s}  "
                    f"{'A2 (' + tx + ')':>14s}  {'Delta':>7s}{RST}")
                tee_print(log_f, sep)

                total_vdur = 0.0
                total_adur = 0.0
                all_ok = True

                for clip in clips_ok:
                    vdur = clip["duration"]
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)
                    total_vdur += vdur
                    total_adur += adur

                    vframes = int(vdur * FPS)
                    aframes = int(adur * FPS)
                    fdelta = abs(vframes - aframes)
                    if fdelta > 0:
                        all_ok = False
                    if fdelta == 0:
                        mark = f"{GREEN}✓{RST}"
                    else:
                        mark = f"{YELLOW}⚠{RST}"
                    tee_print(log_f,
                        f"  {clip['clip_id']:20s}  "
                        f"{format_timecode(vdur, FPS):>14s}  "
                        f"{format_timecode(adur, FPS):>14s}  "
                        f"{fdelta:>3d}f {mark}")

                tee_print(log_f, sep)

                # TOTAL row
                tvf = int(total_vdur * FPS)
                taf = int(total_adur * FPS)
                tfd = abs(tvf - taf)
                if tfd == 0:
                    tmark = f"{GREEN}✓{RST}"
                else:
                    tmark = f"{YELLOW}⚠{RST}"
                tee_print(log_f,
                    f"  {BOLD}{'TOTAL':20s}{RST}  "
                    f"{format_timecode(total_vdur, FPS):>14s}  "
                    f"{format_timecode(total_adur, FPS):>14s}  "
                    f"{tfd:>3d}f {tmark}")

                # Phase 3 sync summary
                if tx in phase3_summary:
                    p3 = phase3_summary[tx]
                    p3f = p3 * FPS
                    if p3f < 1.0:
                        p3m = f"{GREEN}✓{RST}"
                    else:
                        p3m = f"{YELLOW}⚠{RST}"
                    tee_print(log_f,
                        f"  {'Phase 3 sync':20s}  "
                        f"{'':>14s}  "
                        f"max_err={p3:.3f}s (<{int(p3f)+1}f)  {p3m}")

                tee_print(log_f, sep)
                tee_print(log_f, "")

                if all_ok:
                    tee_print(log_f,
                        f"  {GREEN}{BOLD}✓ All clips synced OK{RST}")
                else:
                    tee_print(log_f,
                        f"  {YELLOW}⚠ Issues detected — check deltas above{RST}")

        # ── Project Structure (show created files) ──
        tee_print(log_f, "")
        tee_print(log_f,
            f"{BOLD}{BLUE}  Project Structure{RST}")
        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")

        T = "├── "
        L = "└── "
        I = "│   "
        S = "    "

        tee_print(log_f, f"  {BOLD}{project_name}/{RST}")
        tee_print(log_f, f"  │")

        # 01_Media/Source/
        tee_print(log_f, f"  {T}{BOLD}01_Media/Source/{RST}")
        sp = "  │   "

        # Video/
        tee_print(log_f,
            f"{sp}{T}{BOLD}Video/{RST}  "
            f"{len(clips_ok)} clips  "
            f"{DIM}({format_size(total_video_size)}){RST}")
        for i, clip in enumerate(clips_ok):
            vpath = _find_video_path(
                clip['clip_id'], video_path_map, clips_dir)
            conn = L if i == len(clips_ok) - 1 else T
            sz = format_size(vpath.stat().st_size) if vpath else "?"
            vname = vpath.name if vpath else f"{clip['clip_id']}.MP4"
            tee_print(log_f,
                f"{sp}{I}{conn}{vname}  "
                f"{DIM}{sz}  "
                f"{format_timecode(clip['duration'], FPS)}{RST}")

        # Audio/ (DJI synced — NEW files)
        audio_list = sorted(out_dir.rglob("*.wav"))
        if audio_list:
            ta = sum(f.stat().st_size for f in audio_list)
            tee_print(log_f,
                f"{sp}{T}{GREEN}{BOLD}Audio/{RST}  "
                f"{GREEN}{len(audio_list)} synced{RST}  "
                f"{DIM}({format_size(ta)}){RST}  "
                f"{GREEN}← NEW{RST}")
            for j, af in enumerate(audio_list):
                conn = L if j == len(audio_list) - 1 else T
                tee_print(log_f,
                    f"{sp}{I}{conn}{GREEN}{af.name}{RST}  "
                    f"{DIM}{format_size(af.stat().st_size)}{RST}")
        else:
            tee_print(log_f,
                f"{sp}{T}Audio/  {DIM}—{RST}")

        # 99_Pipeline/DJI_Audio/
        sync_files = []
        if prproj_path and prproj_path.exists():
            sync_files.append(prproj_path)
        if xml_path and xml_path.exists():
            sync_files.append(xml_path)
        if sync_files:
            tee_print(log_f,
                f"{sp}{L}{BOLD}99_Pipeline/DJI_Audio/{RST}")
            for k, sf in enumerate(sync_files):
                conn = L if k == len(sync_files) - 1 else T
                tee_print(log_f,
                    f"{sp}{S}{conn}{GREEN}{sf.name}{RST}"
                    f"  {GREEN}← NEW{RST}")
        else:
            tee_print(log_f,
                f"{sp}{L}99_Pipeline/DJI_Audio/")

        # 99_Pipeline/DJI_Audio/
        dji_files_list = sorted(dji_dir.glob("*.wav")) if dji_dir.exists() else []
        if dji_files_list:
            td = sum(f.stat().st_size for f in dji_files_list)
            tee_print(log_f, f"  │")
            tee_print(log_f,
                f"  {L}{BOLD}99_Pipeline/DJI_Audio/{RST}  "
                f"{len(dji_files_list)} files  "
                f"{DIM}({format_size(td)}){RST}")
            for m, df in enumerate(dji_files_list):
                conn = L if m == len(dji_files_list) - 1 else T
                tee_print(log_f,
                    f"  {S}{conn}{df.name}  "
                    f"{DIM}{format_size(df.stat().st_size)}{RST}")

        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")

        # ============================================================
        # DONE + Media recap + NEXT STEP
        # ============================================================
        tee_print(log_f, "")
        tee_print(log_f, f"{BOLD}{GREEN}{'═' * 60}{RST}")
        tee_print(log_f, f"{BOLD}{GREEN}  DONE{RST}")
        tee_print(log_f, f"{BOLD}{GREEN}{'═' * 60}{RST}")

        # ── Media recap (duplicate at end so user doesn't scroll) ──
        tee_print(log_f, "")
        tee_print(log_f,
            f"{BOLD}{BLUE}  Media Statistics{RST}")
        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")
        for clip in clips_ok:
            vpath = _find_video_path(
                clip['clip_id'], video_path_map, clips_dir)
            vsize = vpath.stat().st_size if vpath else 0
            vsuffix = vpath.suffix if vpath else ".MP4"
            tee_print(log_f,
                f"  {CYAN}V{RST}  {clip['clip_id']}{vsuffix}  "
                f"{DIM}{format_size(vsize)}{RST}  "
                f"{format_timecode(clip['duration'], FPS)}")
        for clip in clips_ok:
            for tx in tx_ids:
                clip_out = _scene_out_dir(
                    clip['clip_id'], clip_scene_map, out_dir)
                apath = clip_out / f"{clip['clip_id']}_{tx}.wav"
                if apath.exists():
                    asize = apath.stat().st_size
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)
                    tee_print(log_f,
                        f"  {GREEN}A{RST}  {apath.name}  "
                        f"{DIM}{format_size(asize)}{RST}  "
                        f"{format_timecode(adur, FPS)}")
        tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")
        tee_print(log_f,
            f"  {BOLD}Video{RST}: {len(clips_ok)} clips  "
            f"{format_size(total_video_size)}  "
            f"{format_timecode(total_video_dur, FPS)}")
        tee_print(log_f,
            f"  {BOLD}Audio{RST}: {success_count} synced  "
            f"{format_size(total_audio_size)}  "
            f"{format_timecode(total_audio_dur, FPS)}")

        # ── Sync Visualization + Track Comparison recap ──
        if success_count > 0 and clips_ok:
            for tx in tx_ids:
                tee_print(log_f, "")
                tee_print(log_f,
                    f"{BOLD}{BLUE}  Sync Visualization ({tx}){RST}")
                tee_print(log_f, f"  {DIM}{'─' * 56}{RST}")

                for clip in clips_ok:
                    vdur = clip["duration"]
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)
                    vtc = format_timecode(vdur, FPS)
                    atc = format_timecode(adur, FPS)
                    vframes = int(vdur * FPS)
                    aframes = int(adur * FPS)
                    frame_delta = abs(vframes - aframes)

                    tee_print(log_f,
                        f"  {BOLD}{clip['clip_id']}{RST} × {tx}:")
                    v_bar = f"{CYAN}{'█' * BAR_W}{RST}"
                    tee_print(log_f,
                        f"    V1 |{v_bar}| {vtc}")
                    if adur > 0 and vdur > 0:
                        ratio = min(adur / vdur, 1.0)
                        a_chars = max(1, int(ratio * BAR_W))
                        gap_chars = BAR_W - a_chars
                        if gap_chars > 0:
                            a_bar = (f"{GREEN}{'█' * a_chars}{RST}"
                                     f"{RED}{'░' * gap_chars}{RST}")
                            mark = f"{YELLOW}Δ={frame_delta}f ⚠{RST}"
                        else:
                            a_bar = f"{GREEN}{'█' * BAR_W}{RST}"
                            mark = (f"{GREEN}Δ=0f ✓{RST}"
                                    if frame_delta == 0
                                    else f"{YELLOW}Δ={frame_delta}f ⚠{RST}")
                    else:
                        a_bar = f"{RED}{'░' * BAR_W}{RST}"
                        mark = f"{RED}MISSING ✗{RST}"
                    tee_print(log_f,
                        f"    A2 |{a_bar}| {atc}  {mark}")
                    tee_print(log_f, "")

                # Track Comparison table
                sep = f"  {DIM}{'─' * 68}{RST}"
                tee_print(log_f,
                    f"{BOLD}{BLUE}  Track Comparison ({FPS}fps){RST}")
                tee_print(log_f, sep)
                tee_print(log_f,
                    f"  {BOLD}{'Clip':20s}  {'V1 (video)':>14s}  "
                    f"{'A2 (' + tx + ')':>14s}  {'Delta':>7s}{RST}")
                tee_print(log_f, sep)

                t_vdur = 0.0
                t_adur = 0.0
                t_ok = True
                for clip in clips_ok:
                    vdur = clip["duration"]
                    adur = output_durations.get(
                        (clip["clip_id"], tx), 0.0)
                    t_vdur += vdur
                    t_adur += adur
                    vf = int(vdur * FPS)
                    af = int(adur * FPS)
                    fd = abs(vf - af)
                    if fd > 0:
                        t_ok = False
                    m = f"{GREEN}✓{RST}" if fd == 0 else f"{YELLOW}⚠{RST}"
                    tee_print(log_f,
                        f"  {clip['clip_id']:20s}  "
                        f"{format_timecode(vdur, FPS):>14s}  "
                        f"{format_timecode(adur, FPS):>14s}  "
                        f"{fd:>3d}f {m}")
                tee_print(log_f, sep)
                tvf = int(t_vdur * FPS)
                taf = int(t_adur * FPS)
                tfd = abs(tvf - taf)
                tm = f"{GREEN}✓{RST}" if tfd == 0 else f"{YELLOW}⚠{RST}"
                tee_print(log_f,
                    f"  {BOLD}{'TOTAL':20s}{RST}  "
                    f"{format_timecode(t_vdur, FPS):>14s}  "
                    f"{format_timecode(t_adur, FPS):>14s}  "
                    f"{tfd:>3d}f {tm}")
                if tx in phase3_summary:
                    p3 = phase3_summary[tx]
                    p3f = p3 * FPS
                    p3m = (f"{GREEN}✓{RST}" if p3f < 1.0
                           else f"{YELLOW}⚠{RST}")
                    tee_print(log_f,
                        f"  {'Phase 3 sync':20s}  "
                        f"{'':>14s}  "
                        f"max_err={p3:.3f}s (<{int(p3f)+1}f)  {p3m}")
                tee_print(log_f, sep)
                tee_print(log_f, "")

                if t_ok:
                    tee_print(log_f,
                        f"  {GREEN}{BOLD}✓ All clips synced OK{RST}")
                else:
                    tee_print(log_f,
                        f"  {YELLOW}⚠ Issues detected — check deltas{RST}")

        # ── NEXT STEP ──
        tee_print(log_f, "")
        tee_print(log_f, f"{BOLD}{YELLOW}NEXT STEP{RST}")
        ns_sep = f"{DIM}{'─' * 60}{RST}"
        tee_print(log_f, ns_sep)

        # 1. Run transcription (primary next step)
        tee_print(log_f, "")
        tee_print(log_f,
            f"  {BOLD}1. Run transcription:{RST}")
        tee_print(log_f, "")
        tee_print(log_f,
            f"  {CYAN}source {_venv} && "
            f"python3 {_pipeline} "
            f"\"{project_dir}\" "
            f"--only transcribe -n 2{RST}")
        tee_print(log_f, "")

        # 2. Verify sync in Premiere
        if prproj_path and prproj_path.exists():
            tee_print(log_f,
                f"  {BOLD}2. Verify sync in Premiere Pro:{RST}")
            tee_print(log_f, "")
            tee_print(log_f,
                f"  {CYAN}open \"{prproj_path}\"{RST}")
            if xml_path and xml_path.exists():
                tee_print(log_f,
                    f"  {DIM}Then: File > Import > select:{RST}")
                tee_print(log_f,
                    f"  {CYAN}{xml_path}{RST}")
            tee_print(log_f, "")

        # 3. Re-run DJI sync
        tee_print(log_f,
            f"  {BOLD}3. Re-run DJI sync:{RST}")
        tee_print(log_f, "")
        tee_print(log_f,
            f"  {CYAN}source {_venv} && "
            f"python3 {Path(__file__).resolve()} "
            f"--project \"{project_dir}\" "
            f"--overwrite{RST}")
        tee_print(log_f, "")
        tee_print(log_f, ns_sep)

        tee_print(log_f, "")
        tee_print(log_f,
            f"  {DIM}Log: {log_path}{RST}")

    print(f"\n{DIM}Log saved: {log_path}{RST}")


if __name__ == "__main__":
    main()
