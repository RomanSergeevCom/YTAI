#!/usr/bin/env python3
"""
0104_sync_audio_nested.py — Complete CLI for nested-project audio sync.

Orchestrates per-clip TX audio synchronization for nested projects produced by
0100_organize (scene subdirectories under 01_Media/Source/Video/).

Functions:
  detect_scenes          — Discover scene directories in organized project
  get_scene_clips        — List video clips in a scene directory
  extract_clip_audio     — Extract camera audio from clip to WAV (48kHz)
  build_scene_concat     — Concatenate per-clip WAVs into one scene WAV
  preload_tx_cache       — Load all TX WAVs at 8kHz into a dict cache
  find_best_tx_candidate — Select best TX WAV via cross-correlation
  trim_tx_to_clip        — Trim TX WAV to match clip duration at offset
  residual_to_frames     — Convert sync residual seconds to frame delta
  generate_ingest_json   — Write per-scene ingest.json with A1/A2/A3 tracks
  process_clip           — Orchestrate one clip: extract, correlate, trim, verify
  process_scene          — Orchestrate one scene: all clips + concat + ingest
  main                   — CLI entry point (--project, --scene, --dry-run)

Part of Phase 2 (Audio Sync).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

# ---------------------------------------------------------------------------
# Import shared utilities from 0103_sync_dji_audio
# ---------------------------------------------------------------------------
_SYNC_PATH = (
    Path(__file__).resolve().parent.parent
    / "0103_sync_dji_audio"
    / "0103_sync_dji_audio.py"
)
spec = importlib.util.spec_from_file_location("_sync", _SYNC_PATH)
_sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_sync)

extract_mono_8k = _sync.extract_mono_8k
build_ffmpeg_cmd = _sync.build_ffmpeg_cmd
get_video_clip_info = _sync.get_video_clip_info
tee_print = _sync.tee_print
run_ffmpeg = _sync.run_ffmpeg

# ---------------------------------------------------------------------------
# Import verify_full from fix_dji_sync.py
# ---------------------------------------------------------------------------
_FIX_PATH = (
    Path(__file__).resolve().parent.parent
    / "0103_sync_dji_audio"
    / "fix_dji_sync.py"
)
_fix_spec = importlib.util.spec_from_file_location("_fix", _FIX_PATH)
_fix = importlib.util.module_from_spec(_fix_spec)
_fix_spec.loader.exec_module(_fix)
verify_full = _fix.verify_full

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CONFIDENCE_THRESHOLD = 3.0
SR = 8000
VIDEO_EXTS = {".MP4", ".MOV", ".mp4", ".mov"}


# ---------------------------------------------------------------------------
# AUD-01: Scene discovery
# ---------------------------------------------------------------------------

def detect_scenes(project: Path) -> list[Path]:
    """Discover scene directories in an organized project.

    Scans project/01_Media/Source/Video/ for subdirectories that contain
    at least one video file (recursively). Does NOT require a numeric prefix
    (e.g. `01_`) — any subdirectory with video files qualifies.

    Args:
        project: Root path of the organized project.

    Returns:
        Sorted list of scene directory Path objects.
    """
    video_dir = project / "01_Media" / "Source" / "Video"
    scenes = []
    for p in sorted(video_dir.iterdir()):
        if p.is_dir() and any(
            f.suffix.upper() in {".MP4", ".MOV"} for f in p.rglob("*")
        ):
            scenes.append(p)
    return scenes


# ---------------------------------------------------------------------------
# AUD-01b: Clip discovery within a scene
# ---------------------------------------------------------------------------

def get_scene_clips(scene_dir: Path) -> list[Path]:
    """List all video clips in a scene directory (recursive).

    Args:
        scene_dir: Scene directory containing video files.

    Returns:
        Sorted list of video file Path objects (by stem name).
    """
    clips = []
    for f in scene_dir.rglob("*"):
        if f.suffix.upper() in {".MP4", ".MOV"} and not f.name.startswith("."):
            clips.append(f)
    return sorted(clips, key=lambda p: p.stem)


# ---------------------------------------------------------------------------
# AUD-02: Per-clip audio extraction
# ---------------------------------------------------------------------------

def extract_clip_audio(clip_path: Path, project: Path, scene_name: str) -> Path:
    """Extract camera audio from a video clip to a WAV file.

    Output location:
      {project}/01_Media/Source/Transcription/per_clip/{scene_name}/{clip_stem}/{clip_stem}_AUDIO.wav

    Args:
        clip_path: Path to the source video clip.
        project: Root path of the organized project.
        scene_name: Scene subdirectory name (e.g. "volleyball").

    Returns:
        Path to the output WAV file.
    """
    clip_stem = clip_path.stem
    out_dir = (
        project / "01_Media" / "Source" / "Transcription"
        / "per_clip" / scene_name / clip_stem
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{clip_stem}_AUDIO.wav"

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-y",
        "-i", str(clip_path),
        "-map", "0:a:0",
        "-vn", "-sn", "-dn",
        "-ar", "48000",
        "-ac", "2",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=False)
    return out_path


# ---------------------------------------------------------------------------
# AUD-03: Scene-level concatenation
# ---------------------------------------------------------------------------

def build_scene_concat(
    clip_audio_paths: list[Path], scene_name: str, project: Path
) -> Path:
    """Concatenate per-clip WAVs into one scene-level FULL_AUDIO.wav.

    Uses ffmpeg concat demuxer with a temporary file list.

    Args:
        clip_audio_paths: Ordered list of per-clip WAV paths.
        scene_name: Scene name (used for output filename and directory).
        project: Root path of the organized project.

    Returns:
        Path to the concatenated output WAV.
    """
    out_dir = (
        project / "01_Media" / "Source" / "Transcription"
        / "per_clip" / scene_name
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{scene_name}_FULL_AUDIO.wav"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=out_dir
    ) as list_file:
        list_path = Path(list_file.name)
        for wav in clip_audio_paths:
            list_file.write(f"file '{wav}'\n")

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        str(out_path),
    ]
    subprocess.run(cmd, check=False)
    list_path.unlink(missing_ok=True)
    return out_path


# ---------------------------------------------------------------------------
# TX cache loading
# ---------------------------------------------------------------------------

def preload_tx_cache(dji_audio_dir: Path, tx_prefix: str) -> dict[str, np.ndarray]:
    """Load TX WAV files at 8kHz mono into a dict keyed by path string.

    Only loads WAV files whose name starts with `tx_prefix` (e.g. "TX01").

    Args:
        dji_audio_dir: Directory containing TX WAV files.
        tx_prefix: Filename prefix filter (e.g. "TX01", "TX02").

    Returns:
        Dict mapping str(wav_path) -> np.float32 array at 8000 Hz.
    """
    cache: dict[str, np.ndarray] = {}
    for wav_path in sorted(dji_audio_dir.iterdir()):
        if (
            wav_path.is_file()
            and wav_path.suffix.lower() == ".wav"
            and wav_path.name.startswith(tx_prefix)
        ):
            # Get duration for extraction
            try:
                import soundfile as sf
                duration = sf.info(str(wav_path)).duration
            except Exception:
                duration = 1800.0  # fallback: 30 minutes

            audio = extract_mono_8k(wav_path, 0.0, duration)
            cache[str(wav_path)] = audio.astype(np.float32)

    return cache


# ---------------------------------------------------------------------------
# AUD-04: Cross-correlation candidate selection
# ---------------------------------------------------------------------------

def find_best_tx_candidate(
    cam_audio_8k: np.ndarray,
    tx_wav_cache: dict[str, np.ndarray],
    sr: int = 8000,
) -> tuple[str, float, float]:
    """Select the TX WAV with the best cross-correlation match to camera audio.

    Uses full normalized cross-correlation via fftconvolve. The TX candidate
    with the highest confidence ratio (peak / mean_abs) is selected.

    Args:
        cam_audio_8k: Camera audio as mono float32 array at `sr` Hz.
        tx_wav_cache: Dict mapping path string -> TX audio array at `sr` Hz.
        sr: Sample rate (default 8000 Hz).

    Returns:
        Tuple of (best_tx_path_str, best_offset_sec, best_confidence).
        offset_sec is the position within the TX file where the camera signal
        begins.
    """
    cam_n = (cam_audio_8k - cam_audio_8k.mean()) / (cam_audio_8k.std() + 1e-10)
    cam_flipped = cam_n[::-1]

    best_path: str | None = None
    best_conf = -1.0
    best_offset = 0.0

    for tx_path_str, tx_audio in tx_wav_cache.items():
        if len(tx_audio) < len(cam_n):
            continue

        tx_n = (tx_audio - tx_audio.mean()) / (tx_audio.std() + 1e-10)
        corr = fftconvolve(tx_n, cam_flipped, mode="full")

        # Valid region: positions where the camera window is fully inside TX
        valid_start = len(cam_n) - 1
        valid_end = valid_start + len(tx_audio) - len(cam_n) + 1
        region = corr[valid_start:valid_end]

        peak_local = int(np.argmax(region))
        peak_val = float(region[peak_local])
        mean_val = float(np.mean(np.abs(region)))
        conf = peak_val / (mean_val + 1e-10)
        offset_sec = peak_local / sr

        if conf > best_conf:
            best_conf = conf
            best_path = tx_path_str
            best_offset = offset_sec

    return best_path, best_offset, best_conf


# ---------------------------------------------------------------------------
# AUD-05: TX trimming
# ---------------------------------------------------------------------------

def trim_tx_to_clip(
    tx_path: Path,
    offset_sec: float,
    clip_duration: float,
    output_path: Path,
) -> Path:
    """Trim a TX WAV file to exactly match a clip's duration at the given offset.

    Args:
        tx_path: Source TX WAV file path.
        offset_sec: Start position within the TX file (seconds).
        clip_duration: Duration of the target video clip (seconds).
        output_path: Destination WAV path.

    Returns:
        Path to the output WAV (same as output_path).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-y",
        "-ss", f"{offset_sec:.6f}",
        "-t", f"{clip_duration:.6f}",
        "-i", str(tx_path),
        "-c:a", "pcm_s16le",
        "-ar", "48000",
        str(output_path),
    ]
    subprocess.run(cmd, check=False)
    return output_path


# ---------------------------------------------------------------------------
# AUD-06: Residual to frames
# ---------------------------------------------------------------------------

def residual_to_frames(residual_sec: float, fps: float) -> float:
    """Convert a sync residual in seconds to a frame count at given FPS.

    Args:
        residual_sec: Sync residual (can be positive or negative).
        fps: Frames per second of the video clip.

    Returns:
        Absolute frame delta as a float.
    """
    return abs(residual_sec) * fps


# ---------------------------------------------------------------------------
# AUD-07: Per-scene ingest.json generation
# ---------------------------------------------------------------------------

def generate_ingest_json(
    scene_name: str, clip_results: list[dict], project: Path
) -> Path:
    """Write per-scene ingest.json with A1/A2/A3 track metadata.

    Output location:
      {project}/01_Media/Source/Setup/{scene_name}_ingest.json

    Each clip entry contains:
      A1: camera_embed (original camera audio)
      A2: TX01_SYNC (trimmed TX01 WAV) or LOW_CONF if below threshold
      A3: TX02_SYNC (trimmed TX02 WAV) or LOW_CONF if below threshold

    Args:
        scene_name: Scene directory name (e.g. "volleyball").
        clip_results: List of dicts from process_clip(), each containing
            clip_id, clip_path, duration_sec, fps,
            tx01_path, tx01_delta_frames, tx02_path, tx02_delta_frames.
        project: Root path of the organized project.

    Returns:
        Path to the written ingest.json file.
    """
    setup_dir = project / "01_Media" / "Source" / "Setup"
    setup_dir.mkdir(parents=True, exist_ok=True)
    out_path = setup_dir / f"{scene_name}_ingest.json"

    clips_data = []
    for cr in clip_results:
        tracks = {
            "A1": {"type": "camera_embed", "path": cr["clip_path"]},
        }
        if cr.get("tx01_path"):
            tracks["A2"] = {
                "type": "TX01_SYNC",
                "path": cr["tx01_path"],
                "sync_delta_frames": cr["tx01_delta_frames"],
            }
        else:
            tracks["A2"] = {"type": "LOW_CONF", "path": None, "sync_delta_frames": None}

        if cr.get("tx02_path"):
            tracks["A3"] = {
                "type": "TX02_SYNC",
                "path": cr["tx02_path"],
                "sync_delta_frames": cr["tx02_delta_frames"],
            }
        else:
            tracks["A3"] = {"type": "LOW_CONF", "path": None, "sync_delta_frames": None}

        clips_data.append({
            "clip_id": cr["clip_id"],
            "clip_path": cr["clip_path"],
            "duration_sec": cr["duration_sec"],
            "fps": cr["fps"],
            "tracks": tracks,
        })

    data = {"scene": scene_name, "clips": clips_data}
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)

    return out_path


# ---------------------------------------------------------------------------
# Orchestration: process_clip
# ---------------------------------------------------------------------------

def process_clip(
    clip_path: Path,
    project: Path,
    scene_name: str,
    tx01_cache: dict,
    tx02_cache: dict,
    log_f=None,
    dry_run: bool = False,
) -> dict:
    """Orchestrate one clip: extract audio, correlate, trim TX WAVs, verify.

    Args:
        clip_path: Path to the source video clip.
        project: Root path of the organized project.
        scene_name: Scene directory name (e.g. "volleyball").
        tx01_cache: Preloaded TX01 WAVs dict (path -> float32 array).
        tx02_cache: Preloaded TX02 WAVs dict (path -> float32 array).
        log_f: Optional log file handle.
        dry_run: If True, skip writing files.

    Returns:
        Dict with clip_id, clip_path, duration_sec, fps,
        tx01_path, tx01_delta_frames, tx02_path, tx02_delta_frames,
        tx01_conf, tx02_conf.
    """
    info = get_video_clip_info(clip_path)
    clip_duration = info["duration"]
    clip_fps = float(info.get("fps", 25.0))

    # Extract clip audio (48kHz stereo WAV)
    if not dry_run:
        extract_clip_audio(clip_path, project, scene_name)

    # Camera audio at 8kHz for cross-correlation
    cam_8k = extract_mono_8k(clip_path, 0, clip_duration)

    # TX01 correlation
    tx01_path_str, tx01_offset, tx01_conf = find_best_tx_candidate(cam_8k, tx01_cache)
    # TX02 correlation
    tx02_path_str, tx02_offset, tx02_conf = find_best_tx_candidate(cam_8k, tx02_cache)

    tx01_path_rel = None
    tx01_delta_frames = None
    tx02_path_rel = None
    tx02_delta_frames = None

    # TX01 output
    if tx01_conf >= CONFIDENCE_THRESHOLD and tx01_path_str and not dry_run:
        out_tx01 = project / "01_Media" / "Source" / "Audio" / f"{clip_path.stem}_TX01.wav"
        trim_tx_to_clip(Path(tx01_path_str), tx01_offset, clip_duration, out_tx01)
        residual_sec = verify_full(clip_path, out_tx01, clip_duration)
        if residual_sec is not None:
            tx01_delta_frames = residual_to_frames(residual_sec, clip_fps)
        else:
            tx01_delta_frames = 0.0
        tx01_path_rel = str(out_tx01.relative_to(project))

    # TX02 output
    if tx02_conf >= CONFIDENCE_THRESHOLD and tx02_path_str and not dry_run:
        out_tx02 = project / "01_Media" / "Source" / "Audio" / f"{clip_path.stem}_TX02.wav"
        trim_tx_to_clip(Path(tx02_path_str), tx02_offset, clip_duration, out_tx02)
        residual_sec = verify_full(clip_path, out_tx02, clip_duration)
        if residual_sec is not None:
            tx02_delta_frames = residual_to_frames(residual_sec, clip_fps)
        else:
            tx02_delta_frames = 0.0
        tx02_path_rel = str(out_tx02.relative_to(project))

    # Sync report line
    if tx01_delta_frames is not None:
        tx01_str = f"{tx01_delta_frames:.1f}F"
    elif dry_run and tx01_conf >= CONFIDENCE_THRESHOLD:
        tx01_str = "DRY_RUN"
    else:
        tx01_str = "LOW_CONF"

    if tx02_delta_frames is not None:
        tx02_str = f"{tx02_delta_frames:.1f}F"
    elif dry_run and tx02_conf >= CONFIDENCE_THRESHOLD:
        tx02_str = "DRY_RUN"
    else:
        tx02_str = "LOW_CONF"
    report = (
        f"  {clip_path.stem}: "
        f"TX01={tx01_conf:.1f} ({tx01_str}) "
        f"TX02={tx02_conf:.1f} ({tx02_str})"
    )
    print(report)

    return {
        "clip_id": clip_path.stem,
        "clip_path": str(clip_path.relative_to(project)),
        "duration_sec": clip_duration,
        "fps": clip_fps,
        "tx01_path": tx01_path_rel,
        "tx01_delta_frames": tx01_delta_frames,
        "tx02_path": tx02_path_rel,
        "tx02_delta_frames": tx02_delta_frames,
        "tx01_conf": tx01_conf,
        "tx02_conf": tx02_conf,
    }


# ---------------------------------------------------------------------------
# Orchestration: process_scene
# ---------------------------------------------------------------------------

def process_scene(
    scene_dir: Path,
    project: Path,
    tx01_cache: dict,
    tx02_cache: dict,
    log_f=None,
    dry_run: bool = False,
) -> list[dict]:
    """Orchestrate one scene: process all clips, concat audio, write ingest.json.

    Args:
        scene_dir: Scene directory (e.g. project/01_Media/Source/Video/volleyball).
        project: Root path of the organized project.
        tx01_cache: Preloaded TX01 WAVs dict.
        tx02_cache: Preloaded TX02 WAVs dict.
        log_f: Optional log file handle.
        dry_run: If True, skip writing output WAV files.

    Returns:
        List of clip result dicts from process_clip().
    """
    scene_name = scene_dir.name
    clips = get_scene_clips(scene_dir)
    print(f"\n=== Scene: {scene_name} ({len(clips)} clips) ===")

    clip_results = []
    for clip in clips:
        result = process_clip(
            clip, project, scene_name, tx01_cache, tx02_cache, log_f, dry_run
        )
        clip_results.append(result)

    if not dry_run:
        audio_paths = [
            project / "01_Media" / "Source" / "Transcription" / "per_clip"
            / scene_name / c.stem / f"{c.stem}_AUDIO.wav"
            for c in clips
        ]
        build_scene_concat(audio_paths, scene_name, project)

    # Write ingest.json even in dry_run (metadata, no large files)
    generate_ingest_json(scene_name, clip_results, project)

    return clip_results


# ---------------------------------------------------------------------------
# CLI: main
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for nested-project audio sync.

    Usage:
        python3 0104_sync_audio_nested.py --project /path/to/project
        python3 0104_sync_audio_nested.py --project /path/to/project --scene volleyball
        python3 0104_sync_audio_nested.py --project /path/to/project --dry-run
    """
    parser = argparse.ArgumentParser(
        description="Sync DJI TX audio for nested multi-scene projects"
    )
    parser.add_argument("--project", type=Path, required=True, help="Path to project root")
    parser.add_argument("--scene", type=str, default=None, help="Process only this scene (by name)")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing files")
    args = parser.parse_args()

    project = args.project.resolve()
    dji_audio_dir = project / "99_Pipeline" / "DJI_Audio"

    # Detect TX prefixes from filenames in DJI_Audio/
    tx_prefixes = set()
    for f in dji_audio_dir.glob("*.wav"):
        # TX01_MIC001... -> TX01, TX02_MIC024... -> TX02
        parts = f.stem.split("_")
        if parts and parts[0].startswith("TX"):
            tx_prefixes.add(parts[0])
    tx_prefixes = sorted(tx_prefixes)  # e.g., ["TX01", "TX02"]

    print(f"Project: {project}")
    print(f"TX prefixes found: {tx_prefixes}")
    print(f"DJI Audio dir: {dji_audio_dir}")

    # Pre-load TX caches
    tx_caches = {}
    for prefix in tx_prefixes:
        print(f"Loading {prefix} WAVs into memory at 8kHz...")
        tx_caches[prefix] = preload_tx_cache(dji_audio_dir, prefix)
        print(f"  Loaded {len(tx_caches[prefix])} WAVs for {prefix}")

    # Default: TX01 and TX02; gracefully handle missing
    tx01_cache = tx_caches.get("TX01", {})
    tx02_cache = tx_caches.get("TX02", {})

    # Detect scenes
    scenes = detect_scenes(project)
    if args.scene:
        scenes = [s for s in scenes if s.name == args.scene]
        if not scenes:
            print(f"ERROR: Scene '{args.scene}' not found")
            sys.exit(1)

    print(f"Scenes to process: {[s.name for s in scenes]}")
    if args.dry_run:
        print("\n*** DRY RUN — no files will be written ***\n")

    # Ensure output dirs exist
    (project / "01_Media" / "Source" / "Audio").mkdir(parents=True, exist_ok=True)

    all_results = []
    for scene_dir in scenes:
        results = process_scene(scene_dir, project, tx01_cache, tx02_cache, dry_run=args.dry_run)
        all_results.extend(results)

    # Summary
    total = len(all_results)
    low_conf = sum(
        1 for r in all_results
        if (r.get("tx01_conf", 0) < CONFIDENCE_THRESHOLD
            or r.get("tx02_conf", 0) < CONFIDENCE_THRESHOLD)
    )
    print(f"\n=== SUMMARY ===")
    print(f"Total clips processed: {total}")
    print(f"Low confidence clips: {low_conf}")
    if low_conf:
        for r in all_results:
            if r.get("tx01_conf", 0) < CONFIDENCE_THRESHOLD:
                print(f"  LOW_CONF TX01: {r['clip_id']} (conf={r.get('tx01_conf', 0):.1f})")
            if r.get("tx02_conf", 0) < CONFIDENCE_THRESHOLD:
                print(f"  LOW_CONF TX02: {r['clip_id']} (conf={r.get('tx02_conf', 0):.1f})")


if __name__ == "__main__":
    main()
