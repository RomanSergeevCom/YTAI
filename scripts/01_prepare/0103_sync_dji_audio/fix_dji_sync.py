#!/usr/bin/env python3
"""
fix_dji_sync.py — Per-clip DJI audio re-synchronization using full waveform
cross-correlation against raw DJI source files.

Two-phase approach:
  Phase 1: Global correction per TX per scene (finds rough alignment)
  Phase 2: Per-clip full waveform fine sync (precision <1ms)

Usage:
    source ~/YTAI/environment/.venv_transcribe/bin/activate

    python3 fix_dji_sync.py \\
        --project "/Volumes/RYA Blue/YTCG Saudi/YTCG39_Hadi_Dawani"

    python3 fix_dji_sync.py \\
        --project "..." --scene 03_Coffee --dry-run

    python3 fix_dji_sync.py \\
        --project "..." --verify-only
"""
from __future__ import annotations

import argparse
import copy
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Import shared utilities from the main sync module
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from importlib import import_module as _imp  # noqa: E402

_sync = _imp("0103_sync_dji_audio")

extract_mono_8k = _sync.extract_mono_8k
compute_envelope = _sync.compute_envelope
find_fine_offset = _sync.find_fine_offset
find_overlapping_wavs = _sync.find_overlapping_wavs
build_ffmpeg_cmd = _sync.build_ffmpeg_cmd
get_video_clip_info = _sync.get_video_clip_info
get_dji_wav_info_raw = _sync.get_dji_wav_info_raw
auto_detect_tz_offset = _sync.auto_detect_tz_offset
tee_print = _sync.tee_print
format_duration = _sync.format_duration
natural_key = _sync.natural_key
_scene_out_dir = _sync._scene_out_dir

VIDEO_EXTS = _sync.VIDEO_EXTS
WAV_EXTS = _sync.WAV_EXTS
SCENE_DIR_RE = _sync.SCENE_DIR_RE
MIN_OK_BYTES = _sync.MIN_OK_BYTES

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SR = 8000
FINE_SEARCH_WINDOW = 30.0  # ±30s for per-clip fine sync (wider for global correction residual)
CONFIDENCE_THRESHOLD = 3.0
MIN_ERROR_SEC = 0.002
AUTO_SPLIT_DUR = 1790.0
AUTO_SPLIT_GAP_MAX = 5.0

# ANSI
BOLD, DIM, RST = "\033[1m", "\033[2m", "\033[0m"
GREEN, RED, YELLOW, CYAN, MAGENTA = (
    "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[35m")


# ---------------------------------------------------------------------------
# Full waveform cross-correlation for per-clip fine sync
# ---------------------------------------------------------------------------

def full_waveform_fine_offset(
    camera_path: Path,
    dji_path: Path,
    rough_trim_start: float,
    clip_duration: float,
    search_window: float = FINE_SEARCH_WINDOW,
    log_f=None,
) -> tuple[float, float]:
    """Per-clip fine offset via full waveform cross-correlation.

    Assumes rough_trim_start is already CLOSE (within ±search_window) thanks
    to global correction. Refines to sub-millisecond precision.

    Args:
        camera_path: Camera audio (per_clip WAV or MP4)
        dji_path: Raw DJI WAV file
        rough_trim_start: Approximate start within DJI (after global correction)
        clip_duration: Video clip duration (seconds)
        search_window: ±window around rough offset
        log_f: Log file handle

    Returns:
        (refined_trim_start, confidence)
    """
    from scipy.signal import fftconvolve

    # Cap analysis duration to avoid clock-drift averaging over long clips
    MAX_ANALYSIS_DUR = 120.0
    analysis_dur = min(clip_duration, MAX_ANALYSIS_DUR)

    # Extract camera audio (capped)
    _log(log_f, f"    [EXTRACT] Camera: {camera_path.name} ({analysis_dur:.1f}s of {clip_duration:.1f}s)")
    cam = extract_mono_8k(camera_path, 0, analysis_dur)
    if len(cam) < SR * 2:
        _log(log_f, f"    [SKIP] Camera too short ({len(cam) / SR:.1f}s)")
        return (rough_trim_start, 0.0)
    _log(log_f, f"             {len(cam)} samples ({len(cam) / SR:.1f}s)")

    # Extract DJI: analysis duration + 2*search_window centered on rough
    dji_start = max(0, rough_trim_start - search_window)
    dji_dur = analysis_dur + 2 * search_window
    _log(log_f, f"    [EXTRACT] DJI: {dji_path.name}")
    _log(log_f, f"             range: {dji_start:.1f}s → {dji_start + dji_dur:.1f}s")
    dji = extract_mono_8k(dji_path, dji_start, dji_dur)
    if len(dji) < SR * 2:
        _log(log_f, f"    [SKIP] DJI too short ({len(dji) / SR:.1f}s)")
        return (rough_trim_start, 0.0)
    _log(log_f, f"             {len(dji)} samples ({len(dji) / SR:.1f}s)")

    # Raw waveform cross-correlation (preserves frequency info, sub-ms precision)
    cam_std = cam.std()
    dji_std = dji.std()
    _log(log_f, f"    [WAVEFORM] Camera: std={cam_std:.4f}")
    _log(log_f, f"    [WAVEFORM] DJI:    std={dji_std:.4f}")

    if cam_std < 1e-6 or dji_std < 1e-6:
        _log(log_f, "    [SKIP] Silence")
        return (rough_trim_start, 0.0)

    # Normalize: zero-mean, unit variance
    cam_n = (cam - cam.mean()) / cam_std
    dji_n = (dji - dji.mean()) / dji_std

    # Full cross-correlation via FFT
    cam_flipped = cam_n[::-1]
    corr = fftconvolve(dji_n, cam_flipped, mode="full")

    # Restrict search to ±search_window around expected position
    # Expected peak when aligned: offset = len(cam) - 1 + (rough - dji_start) * SR
    expected_peak = len(cam_n) - 1 + int((rough_trim_start - dji_start) * SR)
    window_samples = int(search_window * SR)
    search_lo = max(0, expected_peak - window_samples)
    search_hi = min(len(corr), expected_peak + window_samples)

    if search_lo >= search_hi:
        _log(log_f, "    [SKIP] Search window out of bounds")
        return (rough_trim_start, 0.0)

    corr_window = corr[search_lo:search_hi]
    local_peak_idx = np.argmax(corr_window)
    peak_idx = search_lo + local_peak_idx
    peak_val = corr[peak_idx]
    mean_val = np.mean(np.abs(corr_window))
    confidence = peak_val / (mean_val + 1e-10)

    offset_samples = peak_idx - len(cam_n) + 1
    offset_sec = offset_samples / SR
    refined_trim_start = dji_start + offset_sec

    correction = refined_trim_start - rough_trim_start

    _log(log_f, f"    [CORRELATE] Window: [{search_lo}:{search_hi}] "
                f"peak={local_peak_idx}/{search_hi - search_lo}  "
                f"conf={confidence:.1f}  correction={correction:+.3f}s")

    if confidence < CONFIDENCE_THRESHOLD:
        _log(log_f, f"    [RESULT] ✗ Low confidence ({confidence:.1f}) — keeping rough offset")
        return (rough_trim_start, confidence)

    _log(log_f, f"    [RESULT] ✓ {rough_trim_start:.3f}s → "
                f"{refined_trim_start:.3f}s  ({correction:+.3f}s)")

    return (refined_trim_start, confidence)


def _log(log_f, msg: str):
    if log_f:
        tee_print(log_f, msg)
    else:
        print(msg)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_full(camera_path: Path, dji_output_path: Path,
                clip_duration: float, log_f=None) -> float | None:
    """Verify sync by correlating the result WAV against camera audio.

    Uses raw waveform cross-correlation (same as sync phase) for accuracy.
    The output WAV should be aligned to the camera, so peak should be at
    expected_peak (zero offset).  Restricts search to ±2s around expected.
    """
    from scipy.signal import fftconvolve

    dur = min(clip_duration, 120.0)
    cam = extract_mono_8k(camera_path, 0, dur)
    dji = extract_mono_8k(dji_output_path, 0, dur)

    if len(cam) < SR * 2 or len(dji) < SR * 2:
        return None

    cam_std = cam.std()
    dji_std = dji.std()

    if cam_std < 1e-6 or dji_std < 1e-6:
        return None

    cam_n = (cam - cam.mean()) / cam_std
    dji_n = (dji - dji.mean()) / dji_std

    cam_flipped = cam_n[::-1]
    corr = fftconvolve(dji_n, cam_flipped, mode="full")

    expected_peak = len(cam_n) - 1
    # Restrict search to ±2s around expected
    verify_window = int(2.0 * SR)
    search_lo = max(0, expected_peak - verify_window)
    search_hi = min(len(corr), expected_peak + verify_window)

    corr_window = corr[search_lo:search_hi]
    local_peak_idx = np.argmax(corr_window)
    peak_idx = search_lo + local_peak_idx
    peak_val = corr[peak_idx]
    mean_val = np.mean(np.abs(corr_window))
    confidence = peak_val / (mean_val + 1e-10)

    residual_sec = (peak_idx - expected_peak) / SR

    status = "✓ OK" if abs(residual_sec) < 0.04 else "⚠ DRIFT"
    _log(log_f, f"      [VERIFY] Residual: {residual_sec:+.4f}s  "
                f"Conf: {confidence:.1f}  {status}")

    return residual_sec


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Per-clip DJI re-sync: global baseline + full waveform fine-tune")
    ap.add_argument("--project", required=True)
    ap.add_argument("--dji-dir", default="99_Pipeline/DJI_Audio")
    ap.add_argument("--tz-offset", type=float, default=None)
    ap.add_argument("--scene", default=None,
                    help="Only process one scene (e.g. 03_Coffee)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    clips_dir = project_dir / "01_Media" / "Source" / "Video"
    dji_dir = (project_dir / args.dji_dir).resolve()
    out_dir = project_dir / "01_Media" / "Source" / "Audio"
    per_clip_dir = project_dir / "01_Media" / "Source" / "Transcription" / "per_clip"
    logs_dir = project_dir / "01_Media" / "Source" / "Setup" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    for d, label in [(project_dir, "Project"), (clips_dir, "Video"),
                      (dji_dir, "DJI Audio")]:
        if not d.exists():
            print(f"ERROR: {label} not found: {d}", file=sys.stderr)
            sys.exit(1)

    # ── Gather video clips ──
    video_files = sorted(
        [p for p in clips_dir.rglob("*")
         if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name))

    clip_scene_map: dict[str, str] = {}
    for vf in video_files:
        try:
            rel = vf.parent.relative_to(clips_dir)
            top = rel.parts[0] if rel.parts else None
            if top and SCENE_DIR_RE.match(top):
                clip_scene_map[vf.stem] = top
        except ValueError:
            pass

    if args.scene:
        video_files = [v for v in video_files
                       if clip_scene_map.get(v.stem) == args.scene]

    # ── Gather DJI files ──
    dji_files = sorted(
        [p for p in dji_dir.iterdir()
         if p.is_file() and p.suffix in WAV_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name))

    # ── Metadata ──
    clips = [get_video_clip_info(vf) for vf in video_files]
    raw_wavs = [get_dji_wav_info_raw(df) for df in dji_files]

    # ── Timezone ──
    # For TZ detection we need ALL clips (not just filtered scene)
    if args.tz_offset is None:
        all_video_files = sorted(
            [p for p in (project_dir / "01_Media" / "Source" / "Video").rglob("*")
             if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")],
            key=lambda p: natural_key(p.name))
        all_clips = [get_video_clip_info(vf) for vf in all_video_files]
        detected, count, total = auto_detect_tz_offset(all_clips, raw_wavs)
        if detected is None:
            print("ERROR: Cannot auto-detect timezone. Use --tz-offset.")
            sys.exit(1)
        tz_offset = detected
    else:
        tz_offset = args.tz_offset

    # Convert DJI to UTC
    dji_wavs = []
    for raw in raw_wavs:
        if raw["local_naive"] is not None:
            local_tz = timezone(timedelta(hours=tz_offset))
            local_dt = raw["local_naive"].replace(tzinfo=local_tz)
            creation_utc = local_dt.astimezone(timezone.utc)
        else:
            creation_utc = None
        info = dict(raw)
        del info["local_naive"]
        info["creation_utc"] = creation_utc
        dji_wavs.append(info)

    # Group by TX
    dji_by_tx: dict[str, list[dict]] = {}
    for w in dji_wavs:
        if w["creation_utc"]:
            dji_by_tx.setdefault(w["tx_id"], []).append(w)
    for tx in dji_by_tx:
        dji_by_tx[tx].sort(key=lambda w: w["creation_utc"])

    # Auto-split snapping
    for tx in dji_by_tx:
        files = dji_by_tx[tx]
        for i in range(1, len(files)):
            prev, cur = files[i - 1], files[i]
            prev_end = prev["creation_utc"] + timedelta(seconds=prev["duration"])
            gap = (cur["creation_utc"] - prev_end).total_seconds()
            if prev["duration"] >= AUTO_SPLIT_DUR and 0 < gap < AUTO_SPLIT_GAP_MAX:
                cur["creation_utc"] = prev_end

    clips_ok = [c for c in clips if c["creation_utc"] is not None]
    tx_ids = sorted(dji_by_tx.keys())

    # ── Logging ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_name = project_dir.name
    mode = "verify" if args.verify_only else ("dry_run" if args.dry_run else "fix")
    log_path = logs_dir / f"{project_name}_fix_dji_sync_{mode}_{ts}.log"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}  FIX DJI SYNC — Per-Clip Full Waveform{RST}")
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")
        tee_print(log_f, f"  Project : {project_name}")
        tee_print(log_f, f"  TZ      : UTC{'+' if tz_offset >= 0 else ''}{tz_offset:g}")
        tee_print(log_f, f"  Clips   : {len(clips_ok)}")
        tee_print(log_f, f"  DJI     : {', '.join(f'{tx}={len(dji_by_tx[tx])}' for tx in tx_ids)}")
        tee_print(log_f, f"  Scene   : {args.scene or 'ALL'}")
        tee_print(log_f, f"  Mode    : {mode.upper()}")
        tee_print(log_f, "")

        # ── VERIFY-ONLY ──
        if args.verify_only:
            tee_print(log_f, f"{BOLD}{MAGENTA}VERIFY EXISTING SYNC{RST}")
            tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
            ok_count = drift_count = skip_count = 0

            for clip in clips_ok:
                scene = clip_scene_map.get(clip["clip_id"], "")
                for tx in tx_ids:
                    clip_out = _scene_out_dir(clip["clip_id"], clip_scene_map, out_dir)
                    wav_path = clip_out / f"{clip['clip_id']}_{tx}.wav"
                    if not wav_path.exists():
                        continue
                    cam_wav = per_clip_dir / clip["clip_id"] / f"{clip['clip_id']}_AUDIO.wav"
                    if not cam_wav.exists():
                        cam_wav = clip["path"]
                    tee_print(log_f, f"  {clip['clip_id']} × {tx}:")
                    residual = verify_full(cam_wav, wav_path, clip["duration"], log_f)
                    if residual is None:
                        skip_count += 1
                    elif abs(residual) < 0.04:
                        ok_count += 1
                    else:
                        drift_count += 1

            tee_print(log_f, "")
            tee_print(log_f, f"  {GREEN}✓ OK{RST}: {ok_count}  "
                             f"{RED}⚠ DRIFT{RST}: {drift_count}  "
                             f"skip: {skip_count}")
            return

        # ==============================================================
        # PHASE 1: Global correction per TX per scene
        # ==============================================================
        tee_print(log_f, f"{BOLD}{MAGENTA}PHASE 1: Global correction per TX{RST}")
        tee_print(log_f, f"{DIM}{'-' * 60}{RST}")

        # For each scene × TX, find correction from the longest clip in that scene
        scene_clips: dict[str, list[dict]] = {}
        for c in clips_ok:
            s = clip_scene_map.get(c["clip_id"], "_all")
            scene_clips.setdefault(s, []).append(c)

        # Global correction: {tx: correction_sec}
        global_correction: dict[str, float] = {}

        # Try to find correction per TX using the longest clip across all scenes
        for tx in tx_ids:
            # Find longest clip that has overlap with this TX
            best_clip = None
            best_dur = 0
            for c in clips_ok:
                segs = find_overlapping_wavs(c, dji_by_tx.get(tx, []))
                if segs and c["duration"] > best_dur:
                    best_dur = c["duration"]
                    best_clip = c

            if best_clip is None:
                tee_print(log_f, f"  {tx}: No clips with DJI overlap → skip")
                continue

            # Camera audio for this clip
            cam_wav = (per_clip_dir / best_clip["clip_id"]
                       / f"{best_clip['clip_id']}_AUDIO.wav")
            if not cam_wav.exists():
                cam_wav = best_clip["path"]

            segs = find_overlapping_wavs(best_clip, dji_by_tx[tx])
            rough = segs[0]["trim_start"]
            raw_path = segs[0]["wav"]["path"]

            tee_print(log_f, f"  {tx}: ref={best_clip['clip_id']} "
                             f"({best_dur:.0f}s, {clip_scene_map.get(best_clip['clip_id'], '?')})")

            # Use existing find_fine_offset with large search window
            refined, conf = find_fine_offset(
                cam_wav, raw_path, rough,
                analysis_dur=60.0, search_window=60.0, log_f=log_f)

            correction = refined - rough
            if conf >= CONFIDENCE_THRESHOLD:
                global_correction[tx] = correction
                tee_print(log_f, f"  {tx}: correction={correction:+.3f}s "
                                 f"(conf={conf:.1f})")
            else:
                tee_print(log_f, f"  {tx}: {YELLOW}low conf ({conf:.1f}){RST} "
                                 f"— no global correction")
            tee_print(log_f, "")

        # Apply global corrections to DJI timestamps
        dji_by_tx_corrected: dict[str, list[dict]] = {}
        for tx in tx_ids:
            corr = global_correction.get(tx, 0.0)
            if corr != 0.0:
                corrected = []
                for w in dji_by_tx[tx]:
                    wc = copy.copy(w)
                    wc["creation_utc"] = w["creation_utc"] - timedelta(seconds=corr)
                    corrected.append(wc)
                dji_by_tx_corrected[tx] = corrected
                tee_print(log_f, f"  Applied {tx} correction: {corr:+.3f}s to "
                                 f"{len(corrected)} files")
            else:
                dji_by_tx_corrected[tx] = dji_by_tx[tx]

        # Re-apply auto-split snapping on corrected timestamps
        for tx in dji_by_tx_corrected:
            files = dji_by_tx_corrected[tx]
            files.sort(key=lambda w: w["creation_utc"])
            for i in range(1, len(files)):
                prev, cur = files[i - 1], files[i]
                prev_end = prev["creation_utc"] + timedelta(seconds=prev["duration"])
                gap = (cur["creation_utc"] - prev_end).total_seconds()
                if prev["duration"] >= AUTO_SPLIT_DUR and 0 < gap < AUTO_SPLIT_GAP_MAX:
                    cur["creation_utc"] = prev_end

        tee_print(log_f, "")

        # ==============================================================
        # PHASE 2: Per-clip full waveform fine sync
        # ==============================================================
        tee_print(log_f, f"{BOLD}{MAGENTA}PHASE 2: Per-clip full waveform fine sync{RST}")
        tee_print(log_f, f"{DIM}{'-' * 60}{RST}")
        tee_print(log_f, "")

        fixed = skipped = no_overlap = failed = 0
        verified_ok = verified_drift = 0

        for clip in clips_ok:
            scene = clip_scene_map.get(clip["clip_id"], "")

            for tx in tx_ids:
                # Find overlap using CORRECTED timestamps
                segments = find_overlapping_wavs(
                    clip, dji_by_tx_corrected.get(tx, []))
                if not segments:
                    no_overlap += 1
                    continue

                # Camera audio
                cam_wav = (per_clip_dir / clip["clip_id"]
                           / f"{clip['clip_id']}_AUDIO.wav")
                if not cam_wav.exists():
                    cam_wav = clip["path"]

                tee_print(log_f, f"  {BOLD}{clip['clip_id']} × {tx}{RST}  "
                                 f"[{scene}]  dur={clip['duration']:.1f}s")

                rough_trim_start = segments[0]["trim_start"]
                raw_dji_path = segments[0]["wav"]["path"]

                # Per-clip full waveform fine sync
                refined_trim_start, confidence = full_waveform_fine_offset(
                    camera_path=cam_wav,
                    dji_path=raw_dji_path,
                    rough_trim_start=rough_trim_start,
                    clip_duration=clip["duration"],
                    search_window=FINE_SEARCH_WINDOW,
                    log_f=log_f,
                )

                fine_correction = refined_trim_start - rough_trim_start

                if confidence < CONFIDENCE_THRESHOLD:
                    tee_print(log_f, f"    → SKIP (low conf {confidence:.1f})")
                    skipped += 1
                    tee_print(log_f, "")
                    continue

                # Validate: refined must be within DJI file bounds
                dji_file_dur = segments[0]["wav"]["duration"]
                if refined_trim_start < 0 or refined_trim_start > dji_file_dur:
                    tee_print(log_f, f"    → {RED}REJECT{RST}: refined={refined_trim_start:.1f}s "
                                     f"outside file [0, {dji_file_dur:.1f}s]")
                    skipped += 1
                    tee_print(log_f, "")
                    continue

                # Build refined segments for ffmpeg
                refined_segments = []
                for si, seg in enumerate(segments):
                    s = dict(seg)
                    if si == 0:
                        s["trim_start"] = max(0, refined_trim_start)
                    refined_segments.append(s)

                # Output
                output_path = _scene_out_dir(
                    clip["clip_id"], clip_scene_map, out_dir)
                output_path.mkdir(parents=True, exist_ok=True)
                output_file = output_path / f"{clip['clip_id']}_{tx}.wav"

                if args.dry_run:
                    tee_print(log_f, f"    → DRY-RUN: {output_file.name} "
                                     f"(fine correction {fine_correction:+.3f}s)")
                    fixed += 1
                    tee_print(log_f, "")
                    continue

                # Compute gaps between segments
                gaps = []
                for i in range(1, len(refined_segments)):
                    ps = refined_segments[i - 1]
                    cs = refined_segments[i]
                    pe = (ps["wav"]["creation_utc"]
                          + timedelta(seconds=ps["trim_start"] + ps["trim_duration"]))
                    cs_ = (cs["wav"]["creation_utc"]
                           + timedelta(seconds=cs["trim_start"]))
                    gaps.append(max(0, (cs_ - pe).total_seconds()))

                cmd = build_ffmpeg_cmd(
                    refined_segments, output_file,
                    gaps=gaps if gaps else None,
                    target_duration=clip["duration"])

                if args.verbose:
                    tee_print(log_f, f"    [CMD] {' '.join(str(c) for c in cmd)}")

                rc = subprocess.run(cmd, capture_output=True).returncode
                if (rc != 0 or not output_file.exists()
                        or output_file.stat().st_size < MIN_OK_BYTES):
                    tee_print(log_f, f"    → {RED}FAILED{RST} (ffmpeg rc={rc})")
                    failed += 1
                    tee_print(log_f, "")
                    continue

                size_mb = output_file.stat().st_size / (1024 * 1024)
                tee_print(log_f, f"    → {GREEN}OK{RST} {output_file.name} "
                                 f"({size_mb:.1f} MB, fine {fine_correction:+.3f}s)")

                # Verify
                residual = verify_full(
                    cam_wav, output_file, clip["duration"], log_f)
                if residual is not None and abs(residual) < 0.04:
                    verified_ok += 1
                else:
                    verified_drift += 1

                fixed += 1
                tee_print(log_f, "")

        # ── Summary ──
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")
        tee_print(log_f, f"{BOLD}SUMMARY{RST}")
        tee_print(log_f, f"  {GREEN}Fixed{RST}       : {fixed}")
        tee_print(log_f, f"  Skipped     : {skipped}")
        tee_print(log_f, f"  No overlap  : {no_overlap}")
        tee_print(log_f, f"  {RED}Failed{RST}      : {failed}")
        tee_print(log_f, f"  Verify ✓    : {verified_ok}")
        tee_print(log_f, f"  Verify ⚠    : {verified_drift}")
        tee_print(log_f, f"{BOLD}{CYAN}{'=' * 60}{RST}")


if __name__ == "__main__":
    main()
