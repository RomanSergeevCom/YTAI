#!/usr/bin/env python3
"""
0104_sync_audio_nested.py — Core functions for nested-project audio sync.

Provides building blocks for per-clip TX audio synchronization using
full-waveform cross-correlation. Designed for nested projects produced by
0100_organize where video files live in named scene subdirectories.

Functions:
  detect_scenes          — Discover scene directories in organized project
  get_scene_clips        — List video clips in a scene directory
  extract_clip_audio     — Extract camera audio from clip to WAV (48kHz)
  build_scene_concat     — Concatenate per-clip WAVs into one scene WAV
  preload_tx_cache       — Load all TX WAVs at 8kHz into a dict cache
  find_best_tx_candidate — Select best TX WAV via cross-correlation
  trim_tx_to_clip        — Trim TX WAV to match clip duration at offset
  residual_to_frames     — Convert sync residual seconds to frame delta

Part of Phase 2 (Audio Sync). Plan 02 will orchestrate these functions
into a complete CLI script.
"""
from __future__ import annotations

import importlib.util
import subprocess
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
