#!/usr/bin/env python3
"""
0105_multiwindow_sync_dji.py — Multi-window cross-correlation DJI sync.

Uses consistency scoring across multiple time windows to find the correct
DJI WAV segment for each video clip. Handles spanning (clip audio split
across two or three consecutive DJI auto-split files).

Usage:
    python 0105_multiwindow_sync_dji.py --project "/Volumes/DISK/Project"
    python 0105_multiwindow_sync_dji.py --project "/Volumes/DISK/Project" --dry-run
    python 0105_multiwindow_sync_dji.py --project "/Volumes/DISK/Project" --overwrite
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

# ---------------------------------------------------------------------------
# Import helpers from existing scripts
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).resolve().parent.parent  # 01_prepare/

_SYNC_PATH = _SCRIPTS / "0103_sync_dji_audio" / "0103_sync_dji_audio.py"
_spec = importlib.util.spec_from_file_location("_sync", _SYNC_PATH)
_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sync)

extract_mono_8k = _sync.extract_mono_8k
get_video_clip_info = _sync.get_video_clip_info

_FIX_PATH = _SCRIPTS / "0103_sync_dji_audio" / "fix_dji_sync.py"
_fix_spec = importlib.util.spec_from_file_location("_fix", _FIX_PATH)
_fix = importlib.util.module_from_spec(_fix_spec)
_fix_spec.loader.exec_module(_fix)
verify_full = _fix.verify_full

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SR = 8000
WINDOW_SEC = 60.0
STEP_SEC = 30.0
CONSISTENCY_TOL = 2.0
VIDEO_EXTS = {".MP4", ".MOV", ".mp4", ".mov"}
SHORT_CLIP_THRESHOLD = 90.0
BAR_W = 30

# ---------------------------------------------------------------------------
# ANSI Colors
# ---------------------------------------------------------------------------
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
MAGENTA = "\033[95m"
CYAN = "\033[96m"
WHITE = "\033[97m"
BG_CYAN = "\033[46m"
BG_GREEN = "\033[42m"
BG_BLUE = "\033[44m"
BG_MAGENTA = "\033[45m"
BG_YELLOW = "\033[43m"
BG_RED = "\033[41m"
RST = "\033[0m"
CLR = "\033[2K\r"

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_tc(seconds: float, fps: float = 25.0) -> str:
    """Format seconds as HH:MM:SS:FF timecode."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    f = int((seconds % 1) * fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def fmt_dur(seconds: float) -> str:
    """Format as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 99 * 60:
        return "??:??"
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024 ** 3:.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def progress_bar(ratio: float, width: int = BAR_W) -> str:
    filled = max(0, min(width, int(ratio * width)))
    empty = width - filled
    return f"{GREEN}{'█' * filled}{RST}{DIM}{'░' * empty}{RST}"


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------

def load_mono_8k(filepath: Path) -> np.ndarray:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(filepath), "-ac", "1", "-ar", str(SR),
        "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1",
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(r.stdout, dtype=np.float32)


def extract_cam_8k(video_path: Path) -> np.ndarray:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path), "-vn", "-ac", "1", "-ar", str(SR),
        "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1",
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return np.array([], dtype=np.float32)
    return np.frombuffer(r.stdout, dtype=np.float32)


def get_duration(filepath: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_format", str(filepath)],
        capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def envelope(sig: np.ndarray, win: float = 0.1) -> np.ndarray:
    w = max(1, int(SR * win))
    return np.convolve(np.abs(sig), np.ones(w) / w, mode="same")


# ---------------------------------------------------------------------------
# Multi-window consistency scoring
# ---------------------------------------------------------------------------

def multiwindow_score(cam_8k, candidate_8k, label="", clip_progress=None):
    cam_dur = len(cam_8k) / SR
    cand_env = envelope(candidate_8k)
    cand_env = (cand_env - cand_env.mean()) / (cand_env.std() + 1e-10)

    if cam_dur < SHORT_CLIP_THRESHOLD:
        cam_env = envelope(cam_8k)
        cam_env = (cam_env - cam_env.mean()) / (cam_env.std() + 1e-10)
        corr = fftconvolve(cand_env, cam_env[::-1], mode="full")
        vs = len(cam_env) - 1
        ve = vs + max(1, len(cand_env) - len(cam_env) + 1)
        region = corr[vs:ve]
        if len(region) == 0:
            if clip_progress:
                clip_progress["done"] += 1
            return {"median_offset": 0, "consistency_pct": 0, "mean_conf": 0, "score": 0}
        peak = int(np.argmax(region))
        conf = float(region[peak]) / (float(np.mean(np.abs(region))) + 1e-10)
        if clip_progress:
            clip_progress["done"] += 1
            _show_progress(clip_progress, label)
        return {"median_offset": peak / SR, "consistency_pct": 100.0,
                "mean_conf": conf, "score": conf}

    adjusted_offsets, confs = [], []
    windows = list(range(0, int(cam_dur) - int(WINDOW_SEC), int(STEP_SEC)))

    for wstart in windows:
        s, e = int(wstart * SR), int((wstart + WINDOW_SEC) * SR)
        chunk = cam_8k[s:e]
        if len(chunk) < SR * 10:
            continue
        c_env = envelope(chunk)
        c_env = (c_env - c_env.mean()) / (c_env.std() + 1e-10)
        corr = fftconvolve(cand_env, c_env[::-1], mode="full")
        vs = len(c_env) - 1
        ve = vs + max(1, len(cand_env) - len(c_env) + 1)
        region = corr[vs:ve]
        if len(region) == 0:
            continue
        peak = int(np.argmax(region))
        conf = float(region[peak]) / (float(np.mean(np.abs(region))) + 1e-10)
        adjusted_offsets.append(peak / SR - wstart)
        confs.append(conf)

    if clip_progress:
        clip_progress["done"] += 1
        _show_progress(clip_progress, label)

    if not adjusted_offsets:
        return {"median_offset": 0, "consistency_pct": 0, "mean_conf": 0, "score": 0}

    offsets = np.array(adjusted_offsets)
    confs_arr = np.array(confs)
    median = float(np.median(offsets))
    consistent = np.abs(offsets - median) < CONSISTENCY_TOL
    n_con = int(consistent.sum())
    pct = n_con / len(offsets) * 100
    mc = float(confs_arr[consistent].mean()) if n_con > 0 else 0
    return {"median_offset": median, "consistency_pct": pct,
            "mean_conf": mc, "score": pct * mc / 100}


def _show_progress(cp, label):
    done, total = cp["done"], cp["total"]
    elapsed = time.time() - cp["start_time"]
    rate = done / elapsed if elapsed > 0 else 0
    eta = (total - done) / rate if rate > 0 else 0
    pct = done / total * 100
    bar = progress_bar(done / total, 20)
    print(f"{CLR}      {bar} {pct:5.1f}%  "
          f"{DIM}{done}/{total}{RST}  "
          f"{CYAN}{label:25s}{RST}  "
          f"{DIM}ETA {fmt_eta(eta)}{RST}", end="", flush=True)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------

def parse_date(filename):
    m = re.search(r"(\d{8})", filename)
    return m.group(1) if m else None

def parse_mic_id(filename):
    m = re.search(r"(MIC\d+)", filename)
    return m.group(1) if m else "MIC000"

def discover_project(project):
    dji_dir = None
    for c in [project / "DJI_Audio", project / "99_Pipeline" / "DJI_Audio"]:
        if c.is_dir():
            dji_dir = c
            break
    if not dji_dir:
        print(f"{RED}ERROR: No DJI_Audio directory found{RST}", file=sys.stderr)
        sys.exit(1)

    scenes = []
    org = project / "01_Media" / "Source" / "Video"
    if org.is_dir():
        for d in sorted(org.iterdir()):
            if d.is_dir():
                clips = sorted(f for f in d.iterdir() if f.suffix in VIDEO_EXTS)
                if clips:
                    scenes.append({"name": d.name, "clips": clips})
    if not scenes:
        for d in sorted(project.iterdir()):
            if d.is_dir() and d.name != "DJI_Audio" and not d.name.startswith("."):
                clips = sorted(f for f in d.iterdir() if f.suffix in VIDEO_EXTS)
                if clips:
                    scenes.append({"name": d.name, "clips": clips})

    tx_groups = {}
    for f in sorted(dji_dir.iterdir()):
        if f.suffix.lower() != ".wav" or f.name.startswith("."):
            continue
        m = re.match(r"(TX\d+)", f.name)
        if m:
            tx_groups.setdefault(m.group(1), []).append(f)

    return {"dji_dir": dji_dir, "scenes": scenes, "tx_groups": tx_groups}


# ---------------------------------------------------------------------------
# Candidate builder
# ---------------------------------------------------------------------------

def build_candidates(tx_paths, tx_cache):
    candidates = []
    for p in tx_paths:
        a = tx_cache.get(str(p))
        if a is None or len(a) < SR * 30:
            continue
        candidates.append({"type": "single", "paths": [p], "audio": a,
                           "label": parse_mic_id(p.name), "split_samples": []})

    for i in range(len(tx_paths) - 1):
        p1, p2 = tx_paths[i], tx_paths[i + 1]
        if parse_date(p1.name) != parse_date(p2.name):
            continue
        a1, a2 = tx_cache.get(str(p1)), tx_cache.get(str(p2))
        if a1 is None or a2 is None or len(a1) < SR*30 or len(a2) < SR*30:
            continue
        candidates.append({"type": "spanning", "paths": [p1, p2],
                           "audio": np.concatenate([a1, a2]),
                           "label": f"{parse_mic_id(p1.name)}+{parse_mic_id(p2.name)}",
                           "split_samples": [len(a1)]})

    for i in range(len(tx_paths) - 2):
        p1, p2, p3 = tx_paths[i], tx_paths[i+1], tx_paths[i+2]
        d1, d2, d3 = parse_date(p1.name), parse_date(p2.name), parse_date(p3.name)
        if not (d1 and d2 and d3 and d1 == d2 == d3):
            continue
        a1, a2, a3 = tx_cache.get(str(p1)), tx_cache.get(str(p2)), tx_cache.get(str(p3))
        if any(x is None for x in [a1, a2, a3]) or len(a1) < SR*30 or len(a2) < SR*30:
            continue
        candidates.append({"type": "spanning", "paths": [p1, p2, p3],
                           "audio": np.concatenate([a1, a2, a3]),
                           "label": f"{parse_mic_id(p1.name)}+{parse_mic_id(p2.name)}+{parse_mic_id(p3.name)}",
                           "split_samples": [len(a1), len(a1)+len(a2)]})
    return candidates


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------

def trim_single(tx_path, offset, duration, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-ss", f"{offset:.6f}", "-t", f"{duration:.6f}",
        "-i", str(tx_path), "-c:a", "pcm_s24le", "-ar", "48000",
        str(output_path)], check=False)
    return output_path


def trim_multi(paths, split_samples, offset_sec, clip_duration, output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    boundaries = [0] + [s / SR for s in split_samples] + [sum(get_duration(p) for p in paths)]
    clip_end = offset_sec + clip_duration

    segments = []
    for fi, p in enumerate(paths):
        fs, fe = boundaries[fi], boundaries[fi + 1]
        ss, se = max(offset_sec, fs), min(clip_end, fe)
        if ss < se:
            segments.append((p, ss - fs, se - ss))

    if len(segments) == 0:
        return output_path
    if len(segments) == 1:
        return trim_single(segments[0][0], segments[0][1], segments[0][2], output_path)

    info_r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(segments[0][0])],
        capture_output=True, text=True)
    audio_s = next((s for s in json.loads(info_r.stdout).get("streams", [])
                    if s["codec_type"] == "audio"), {})
    sr_out = int(audio_s.get("sample_rate", 48000))
    bits = int(audio_s.get("bits_per_sample", 24))

    inputs, fparts, clabels = [], [], []
    for i, (p, start, dur) in enumerate(segments):
        inputs.extend(["-i", str(p)])
        fparts.append(f"[{i}:a]atrim=start={start:.6f}:end={start+dur:.6f},asetpts=N/SR/TB[a{i}]")
        clabels.append(f"[a{i}]")

    fstr = (";".join(fparts)
            + f";{''.join(clabels)}concat=n={len(segments)}:v=0:a=1[raw]"
            + f";[raw]atrim=end={clip_duration:.6f},asetpts=N/SR/TB[out]")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        *inputs, "-filter_complex", fstr, "-map", "[out]",
        "-c:a", f"pcm_s{bits}le", "-ar", str(sr_out), str(output_path)], check=False)
    return output_path


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_sync(video_path, output_path, clip_duration):
    analysis = min(clip_duration, 60.0)
    cam = _extract_8k(video_path, 0, analysis, vn=True)
    dji = _extract_8k(output_path, 0, analysis)
    if len(cam) < SR * 2 or len(dji) < SR * 2:
        return None
    cam_n = (cam - cam.mean()) / (cam.std() + 1e-10)
    dji_n = (dji - dji.mean()) / (dji.std() + 1e-10)
    corr = fftconvolve(dji_n, cam_n[::-1], mode="full")
    expected = len(cam) - 1
    w = int(SR * 2)
    region = corr[max(0, expected-w):min(len(corr), expected+w)]
    if len(region) == 0:
        return None
    peak = max(0, expected - w) + int(np.argmax(region))
    return (peak - expected) / SR


def _extract_8k(fp, start, dur, vn=False):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error",
           "-ss", str(start), "-t", str(dur), "-i", str(fp)]
    if vn:
        cmd.append("-vn")
    cmd.extend(["-ac", "1", "-ar", str(SR), "-f", "f32le", "-c:a", "pcm_f32le", "pipe:1"])
    r = subprocess.run(cmd, capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32) if r.returncode == 0 else np.array([], dtype=np.float32)


# ---------------------------------------------------------------------------
# Process one clip
# ---------------------------------------------------------------------------

def process_clip(clip_path, scene_name, tx_groups, tx_caches, output_base,
                 dry_run=False, overwrite=False, clip_idx=0, total_clips=1,
                 project_start=0):
    clip_id = clip_path.stem
    clip_dur = get_duration(clip_path)
    clip_start = time.time()

    print(f"\n  {BG_CYAN}{WHITE}{BOLD} {clip_idx+1}/{total_clips} {RST}"
          f" {BOLD}{clip_id}{RST}"
          f"  {DIM}{fmt_dur(clip_dur)} ({fmt_tc(clip_dur)}){RST}")

    # Skip existing
    if not overwrite:
        out_dir = output_base / scene_name
        existing = list(out_dir.glob(f"{clip_id}_TX*.wav")) if out_dir.is_dir() else []
        if existing:
            for f in existing:
                print(f"    {YELLOW}⏭{RST} {DIM}exists:{RST} {f.name}")
            return {"clip_id": clip_id, "status": "skipped", "output": str(existing[0])}

    # Extract camera audio
    print(f"    {CYAN}▶{RST} Extracting camera audio...", end="", flush=True)
    cam_8k = extract_cam_8k(clip_path)
    if len(cam_8k) < SR * 5:
        print(f" {RED}✗ ERROR{RST}")
        return {"clip_id": clip_id, "error": "no camera audio"}
    print(f" {GREEN}✓{RST} {DIM}{len(cam_8k)/SR:.1f}s{RST}")

    # Count candidates
    total_candidates = sum(len(build_candidates(tp, tx_caches[tx]))
                           for tx, tp in tx_groups.items())
    cp = {"done": 0, "total": total_candidates, "start_time": time.time()}

    # Score
    print(f"    {CYAN}▶{RST} Correlating {total_candidates} candidates...")
    best_overall = None
    best_per_tx = {}

    for tx, tp in sorted(tx_groups.items()):
        cands = build_candidates(tp, tx_caches[tx])
        best = None
        for c in cands:
            r = multiwindow_score(cam_8k, c["audio"], f"{tx} {c['label']}", cp)
            r["candidate"] = c
            if best is None or r["score"] > best["score"]:
                best = r
        if best and best["score"] > 0:
            best_per_tx[tx] = best
            if best_overall is None or best["score"] > best_overall["score"]:
                best_overall = best
                best_overall["tx_prefix"] = tx

    # Clear progress
    print(CLR, end="", flush=True)
    corr_elapsed = time.time() - cp["start_time"]

    # Report per TX
    print(f"    {GREEN}✓{RST} Correlation done {DIM}({fmt_dur(corr_elapsed)}){RST}")
    for tx, b in sorted(best_per_tx.items()):
        sc = b["score"]
        co = b["consistency_pct"]
        off = b["median_offset"]
        lbl = b["candidate"]["label"]
        color = GREEN if sc > 20 else YELLOW if sc > 10 else RED
        print(f"      {DIM}│{RST} {BOLD}{tx}{RST}"
              f"  {color}score={sc:5.1f}{RST}"
              f"  consist={co:.0f}%"
              f"  {DIM}→{RST} {CYAN}{lbl}{RST}"
              f"  {DIM}offset={fmt_dur(off)}{RST}")

    clip_elapsed = time.time() - clip_start

    if not best_overall or best_overall["score"] <= 0:
        print(f"    {RED}✗ NO MATCH{RST} {DIM}({fmt_dur(clip_elapsed)}){RST}")
        return {"clip_id": clip_id, "error": "no match"}

    cand = best_overall["candidate"]
    tx = best_overall["tx_prefix"]
    offset = best_overall["median_offset"]

    # Contributing MICs
    out_dir = output_base / scene_name
    mic_parts = [parse_mic_id(p.name) for p in cand["paths"]]
    if cand["type"] == "spanning":
        boundaries = [0] + [s / SR for s in cand["split_samples"]]
        contributing_mics = []
        clip_end = offset + clip_dur
        running = 0
        for fi, p in enumerate(cand["paths"]):
            fs = boundaries[fi] if fi < len(boundaries) else running
            fd = len(tx_caches[tx].get(str(p), np.array([]))) / SR
            fe = fs + fd
            if offset < fe and clip_end > fs:
                contributing_mics.append(parse_mic_id(p.name))
            running = fe
        if not contributing_mics:
            contributing_mics = mic_parts
    else:
        contributing_mics = mic_parts

    # EXTEND if candidate can't cover full clip
    if cand["type"] == "single":
        total_avail = get_duration(cand["paths"][0]) - offset
    else:
        total_avail = sum(get_duration(p) for p in cand["paths"]) - offset

    if total_avail < clip_dur - 0.1:
        shortage = clip_dur - total_avail
        last_path = cand["paths"][-1]
        all_tx = tx_groups[tx]
        last_idx = next((i for i, p in enumerate(all_tx) if p.name == last_path.name), -1)
        extra = []
        needed = shortage
        for ni in range(last_idx + 1, len(all_tx)):
            np_ = all_tx[ni]
            if parse_date(np_.name) != parse_date(last_path.name):
                break
            extra.append(np_)
            needed -= get_duration(np_)
            if needed <= 0:
                break
        if extra:
            all_paths = list(cand["paths"]) + extra
            splits = []
            run = 0
            for p in all_paths[:-1]:
                a = tx_caches[tx].get(str(p))
                run += len(a) if a is not None else int(get_duration(p) * SR)
                splits.append(run)
            extra_mics = [parse_mic_id(p.name) for p in extra]
            contributing_mics.extend(m for m in extra_mics if m not in contributing_mics)
            cand = {**cand, "type": "spanning", "paths": all_paths, "split_samples": splits}
            print(f"      {YELLOW}↗{RST} EXTEND +{'+'.join(extra_mics)}"
                  f" {DIM}(need {shortage:.1f}s more){RST}")

    out_name = f"{clip_id}_{tx}_{'_'.join(contributing_mics)}.wav"
    out_path = out_dir / out_name

    sc_color = GREEN if best_overall["score"] > 20 else YELLOW
    print(f"    {BG_GREEN}{WHITE}{BOLD} WINNER {RST}"
          f" {BOLD}{tx}{RST} {CYAN}{'+'.join(contributing_mics)}{RST}"
          f"  {sc_color}score={best_overall['score']:.1f}{RST}"
          f"  {DIM}offset={fmt_dur(offset)}{RST}")

    if dry_run:
        print(f"    {YELLOW}[DRY-RUN]{RST} {out_name}")
        return {"clip_id": clip_id, "tx": tx, "candidate": "+".join(contributing_mics),
                "score": best_overall["score"], "offset": offset, "dry_run": True}

    # Trim
    print(f"    {CYAN}▶{RST} Trimming...", end="", flush=True)
    if cand["type"] == "spanning":
        trim_multi(cand["paths"], cand["split_samples"], offset, clip_dur, out_path)
    else:
        trim_single(cand["paths"][0], offset, clip_dur, out_path)

    if not out_path.exists():
        print(f" {RED}✗ FAILED{RST}")
        return {"clip_id": clip_id, "error": "trim failed"}

    out_dur = get_duration(out_path)
    delta = abs(out_dur - clip_dur)
    print(f" {GREEN}✓{RST}")

    # Verify
    print(f"    {CYAN}▶{RST} Verifying...", end="", flush=True)
    residual = verify_sync(clip_path, out_path, clip_dur)
    print(f" {GREEN}✓{RST}")

    size_mb = out_path.stat().st_size / 1024 / 1024
    ok = "OK"
    if delta > 0.5:
        ok = "DURATION_MISMATCH"
    elif residual is not None and abs(residual) > 0.1:
        ok = "DRIFT"

    # Result box
    status_bg = BG_GREEN if ok == "OK" else BG_YELLOW if ok == "DRIFT" else BG_RED
    res_str = f"{residual:+.4f}s" if residual is not None else "N/A"
    print(f"    {status_bg}{WHITE}{BOLD} {ok} {RST}"
          f" {BOLD}{out_name}{RST} {DIM}({size_mb:.1f} MB){RST}")
    print(f"      {DIM}├{RST} Duration: {BOLD}{fmt_tc(out_dur)}{RST}"
          f"  {DIM}(video: {fmt_tc(clip_dur)}, Δ={delta:.3f}s){RST}")
    print(f"      {DIM}├{RST} Residual: {GREEN if residual and abs(residual)<0.01 else YELLOW}{res_str}{RST}")
    print(f"      {DIM}└{RST} Elapsed:  {DIM}{fmt_dur(time.time()-clip_start)}{RST}")

    return {"clip_id": clip_id, "tx": tx, "candidate": "+".join(contributing_mics),
            "score": best_overall["score"], "offset": offset,
            "output": str(out_path), "duration": out_dur,
            "residual": residual, "status": ok}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="YTAI: Multi-window DJI Audio Sync")
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    project = args.project.resolve()
    t0 = time.time()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Header
    print(f"{BOLD}{CYAN}{'═' * 60}{RST}")
    print(f"{BOLD}{CYAN}  YTAI: MULTIWINDOW DJI SYNC{RST}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RST}")
    print(f"  {DIM}Timestamp{RST}  : {ts}")
    print(f"  {DIM}Project{RST}    : {BOLD}{project.name}{RST}")
    print(f"  {DIM}Path{RST}       : {project}")

    info = discover_project(project)
    total_clips = sum(len(s["clips"]) for s in info["scenes"])
    total_video_dur = 0
    for s in info["scenes"]:
        for c in s["clips"]:
            total_video_dur += get_duration(c)

    print(f"  {DIM}Scenes{RST}     : {', '.join(s['name'] for s in info['scenes'])}")
    print(f"  {DIM}Clips{RST}      : {total_clips} ({fmt_dur(total_video_dur)})")
    dji_count = sum(len(v) for v in info["tx_groups"].values())
    print(f"  {DIM}DJI files{RST}  : {dji_count}"
          f" ({', '.join(f'{k}={len(v)}' for k,v in info['tx_groups'].items())})")

    output_base = project / "01_Media" / "Source" / "Audio"
    output_base.mkdir(parents=True, exist_ok=True)

    # Load DJI audio
    print(f"\n{BOLD}{MAGENTA}PHASE 1: Loading DJI audio{RST}")
    print(f"{DIM}{'─' * 60}{RST}")
    load_start = time.time()
    tx_caches = {}
    total_mem = 0
    for tx, paths in info["tx_groups"].items():
        cache = {}
        for p in paths:
            arr = load_mono_8k(p)
            dur = len(arr) / SR
            if dur < 5:
                continue
            cache[str(p)] = arr
            total_mem += arr.nbytes
            print(f"  {GREEN}✓{RST} {tx} {parse_mic_id(p.name)}"
                  f"  {DIM}{fmt_dur(dur)}  {fmt_size(arr.nbytes)}{RST}")
        tx_caches[tx] = cache
    load_el = time.time() - load_start
    print(f"  {BOLD}Total:{RST} {fmt_size(total_mem)}"
          f" in {DIM}{fmt_dur(load_el)}{RST}")

    # Process scenes
    print(f"\n{BOLD}{MAGENTA}PHASE 2: Cross-correlation sync{RST}")
    print(f"{DIM}{'─' * 60}{RST}")

    results = []
    ci = 0
    for scene in info["scenes"]:
        print(f"\n  {BG_BLUE}{WHITE}{BOLD} {scene['name']} {RST}"
              f" {DIM}{len(scene['clips'])} clips{RST}")

        for clip in scene["clips"]:
            r = process_clip(clip, scene["name"], info["tx_groups"], tx_caches,
                             output_base, args.dry_run, args.overwrite,
                             ci, total_clips, t0)
            results.append(r)
            ci += 1

    total_el = time.time() - t0

    # Summary
    print(f"\n{BOLD}{CYAN}{'═' * 60}{RST}")
    print(f"{BOLD}{CYAN}  SUMMARY{RST}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RST}")

    ok_count = sum(1 for r in results if r.get("status") == "OK")
    skip_count = sum(1 for r in results if r.get("status") == "skipped")
    err_count = sum(1 for r in results if "error" in r)
    warn_count = len(results) - ok_count - skip_count - err_count

    print(f"  {GREEN}✓ Synced{RST}   : {BOLD}{ok_count}{RST}")
    if skip_count:
        print(f"  {YELLOW}⏭ Skipped{RST}  : {skip_count}")
    if warn_count:
        print(f"  {YELLOW}⚠ Warning{RST}  : {warn_count}")
    if err_count:
        print(f"  {RED}✗ Errors{RST}   : {err_count}")
    print(f"  {DIM}Time{RST}       : {fmt_dur(total_el)}")

    # Detail table
    print(f"\n  {BOLD}{BLUE}Results{RST}")
    print(f"  {DIM}{'─' * 56}{RST}")
    print(f"  {DIM}{'Clip':12s}  {'Source':25s}  {'Score':>6s}  {'Residual':>10s}  Status{RST}")
    print(f"  {DIM}{'─' * 56}{RST}")
    for r in results:
        cid = r["clip_id"]
        if "error" in r:
            print(f"  {RED}{cid:12s}  {'—':25s}  {'—':>6s}  {'—':>10s}  ✗ {r['error']}{RST}")
        elif r.get("status") == "skipped":
            print(f"  {DIM}{cid:12s}  {'—':25s}  {'—':>6s}  {'—':>10s}  ⏭ skipped{RST}")
        else:
            src = r.get("candidate", "?")
            sc = f"{r['score']:.1f}"
            res = r.get("residual")
            res_s = f"{res:+.4f}s" if res is not None else "N/A"
            st = r.get("status", "?")
            sc_c = GREEN if r["score"] > 20 else YELLOW
            st_c = GREEN if st == "OK" else YELLOW if st == "DRIFT" else RED
            print(f"  {cid:12s}  {CYAN}{src:25s}{RST}  {sc_c}{sc:>6s}{RST}"
                  f"  {res_s:>10s}  {st_c}{st}{RST}")
    print(f"  {DIM}{'─' * 56}{RST}")

    # Output files
    if not args.dry_run:
        print(f"\n  {BOLD}{BLUE}Output files{RST}")
        print(f"  {DIM}{'─' * 56}{RST}")
        for f in sorted(output_base.rglob("*.wav")):
            sz = fmt_size(f.stat().st_size)
            dur = get_duration(f)
            rel = f.relative_to(project)
            print(f"  {GREEN}✓{RST} {rel}"
                  f"  {DIM}{sz}  {fmt_tc(dur)}{RST}")
        print(f"  {DIM}{'─' * 56}{RST}")

    print(f"\n{BOLD}{GREEN}{'═' * 60}{RST}")
    print(f"{BOLD}{GREEN}  DONE{RST}  {DIM}({fmt_dur(total_el)}){RST}")
    print(f"{BOLD}{GREEN}{'═' * 60}{RST}")


if __name__ == "__main__":
    main()
