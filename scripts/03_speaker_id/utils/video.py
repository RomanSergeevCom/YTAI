#!/usr/bin/env python3
"""
YTAI Utils: Video
FFprobe, video clip operations.
"""

import re
import subprocess
import logging
from pathlib import Path
from typing import List, Tuple, Optional

from .paths import VIDEO_EXTS
from .formatting import format_timestamp


# ============================================================================
# Natural Sort
# ============================================================================

def natural_sort_key(s: str):
    """
    Key for natural sorting of strings with numbers.

    Example: clip1, clip2, clip10 (not clip1, clip10, clip2)
    """
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', s)]


# ============================================================================
# FFprobe
# ============================================================================

def get_video_duration(video_path: Path) -> float:
    """
    Get video duration via ffprobe.

    Args:
        video_path: Path to the video file

    Returns:
        Duration in seconds or 0.0 on error
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    
    return 0.0


# ============================================================================
# Clip operations
# ============================================================================

def get_video_clips(
    video_dir: Path, 
    logger: Optional[logging.Logger] = None
) -> List[dict]:
    """
    Get a list of video clips with durations and offsets.

    Args:
        video_dir: Directory with video files
        logger: Optional logger

    Returns:
        List of dicts:
        [
            {
                "file": "RYA-ZVE1-1146.MP4",
                "path": Path(...),
                "duration": 150.5,
                "start": 0.0,
                "end": 150.5
            },
            ...
        ]
    """
    def log(msg):
        if logger:
            logger.info(msg)
    
    def log_debug(msg):
        if logger:
            logger.debug(msg)
    
    if not video_dir.exists():
        log(f"Video directory not found: {video_dir}")
        return []
    
    # Find all video files (excluding Archive)
    clips = []
    for f in video_dir.iterdir():
        if (f.is_file() and 
            f.suffix in VIDEO_EXTS and 
            not f.name.startswith(".") and
            "Archive" not in str(f)):
            clips.append(f)
    
    # Natural sort
    clips.sort(key=lambda p: natural_sort_key(p.name))
    
    if not clips:
        log(f"No video clips found in {video_dir}")
        return []
    
    log(f"Found {len(clips)} video clips")
    
    # Get durations and compute offsets
    result = []
    current_offset = 0.0
    
    for clip_path in clips:
        duration = get_video_duration(clip_path)
        
        if duration <= 0:
            log(f"  ⚠ Failed to get duration: {clip_path.name}")
            continue
        
        result.append({
            "file": clip_path.name,
            "path": clip_path,
            "duration": duration,
            "start": current_offset,
            "end": current_offset + duration
        })
        
        log_debug(f"  {clip_path.name}: {format_timestamp(duration)} "
                  f"({current_offset:.1f}s - {current_offset + duration:.1f}s)")
        
        current_offset += duration
    
    log(f"Total duration: {format_timestamp(current_offset)}")
    
    return result


def find_clip_for_timestamp(
    clips: List[dict], 
    timestamp: float
) -> Tuple[Optional[dict], float]:
    """
    Find the clip for a given global timestamp.

    Args:
        clips: List of clips from get_video_clips()
        timestamp: Global timestamp in seconds

    Returns:
        Tuple (clip_dict, local_timestamp) or (None, 0.0)
    """
    if not clips:
        return None, 0.0
    
    for clip in clips:
        if clip["start"] <= timestamp < clip["end"]:
            local_ts = timestamp - clip["start"]
            return clip, local_ts
    
    # Edge case: timestamp at the very end of the last clip (within 0.5 sec)
    last_clip = clips[-1]
    if last_clip["end"] - 0.5 <= timestamp <= last_clip["end"] + 0.5:
        local_ts = min(timestamp - last_clip["start"], last_clip["duration"])
        return last_clip, local_ts
    
    return None, 0.0


def get_total_duration(clips: List[dict]) -> float:
    """Get the total duration of all clips."""
    if not clips:
        return 0.0
    return clips[-1]["end"]
