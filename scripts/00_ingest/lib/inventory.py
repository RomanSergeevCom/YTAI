"""
Media inventory via ffprobe + scene grouping by timestamp gaps.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mts', '.avi', '.mkv'}
AUDIO_EXTS = {'.wav'}
DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}', re.IGNORECASE)
CAMERA_RE = re.compile(r'RYA-([A-Z0-9]+)-(\d+)', re.IGNORECASE)

SKIP_DIRS = {
    '.Spotlight-V100', '.fseventsd', '.Trashes', '.TemporaryItems',
    '__MACOSX', '.DocumentRevisions-V100', '_discovery',
    'Adobe Premiere Pro Auto-Save', 'Adobe Premiere Pro Audio Previews',
}


def _ffprobe(filepath: Path) -> dict | None:
    """Run ffprobe and return parsed JSON, or None on error."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json',
             '-show_format', '-show_streams', str(filepath)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        return None


def _parse_creation_time(probe: dict) -> str | None:
    """Extract creation_time from ffprobe output."""
    # Try format tags first, then stream tags
    for section in [probe.get('format', {}), *(probe.get('streams', []))]:
        tags = section.get('tags', {})
        for key in ('creation_time', 'com.apple.quicktime.creationdate'):
            if key in tags:
                return tags[key]
    return None


def _parse_camera(filename: str) -> str | None:
    """Extract camera model from filename like RYA-ZVE1-1376.MP4."""
    m = CAMERA_RE.match(filename)
    return m.group(1) if m else None


def _human_size(nbytes: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def _human_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def _parse_datetime(dt_str: str) -> datetime | None:
    """Parse ISO-ish datetime string from ffprobe."""
    for fmt in (
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
    ):
        try:
            return datetime.strptime(dt_str, fmt)
        except ValueError:
            continue
    return None


def scan_media(raw_folder: Path, *, progress_cb=None) -> dict:
    """
    Walk raw_folder and probe all media files.

    Returns dict with keys:
      - clips: list of clip info dicts (sorted by creation_time)
      - dji_audio: list of DJI WAV file paths
      - other_files: list of non-media files
      - archive: dict describing Archive/ contents if present
    """
    clips = []
    dji_audio = []
    other_files = []
    archive_info = {"has_archive": False, "files": []}

    for root, dirs, files in os.walk(raw_folder):
        # Skip system/hidden dirs
        dirs[:] = [d for d in dirs
                   if d not in SKIP_DIRS and not d.startswith('.')]

        rel_root = Path(root).relative_to(raw_folder)

        # Detect Archive/ folder
        if rel_root.parts and rel_root.parts[0].lower() in ('archive', 'архив'):
            archive_info["has_archive"] = True
            for f in files:
                archive_info["files"].append(str(rel_root / f))
            continue

        for fname in sorted(files):
            fpath = Path(root) / fname
            ext = fpath.suffix.lower()

            if ext in VIDEO_EXTS:
                if progress_cb:
                    progress_cb(fname)

                probe = _ffprobe(fpath)
                if probe is None:
                    other_files.append({"filename": fname, "path": str(fpath),
                                        "note": "ffprobe failed"})
                    continue

                fmt = probe.get('format', {})
                duration = float(fmt.get('duration', 0))
                size = int(fmt.get('size', 0))

                # Find video stream
                width, height, fps = 0, 0, 0.0
                video_codec = None
                audio_codec = None
                audio_channels = 0
                has_audio = False

                for stream in probe.get('streams', []):
                    if stream.get('codec_type') == 'video':
                        width = stream.get('width', 0)
                        height = stream.get('height', 0)
                        video_codec = stream.get('codec_name')
                        # Parse fps from r_frame_rate "25/1"
                        rfr = stream.get('r_frame_rate', '0/1')
                        parts = rfr.split('/')
                        if len(parts) == 2 and int(parts[1]) != 0:
                            fps = round(int(parts[0]) / int(parts[1]), 2)
                    elif stream.get('codec_type') == 'audio':
                        has_audio = True
                        audio_codec = stream.get('codec_name')
                        audio_channels = stream.get('channels', 0)

                creation_time_str = _parse_creation_time(probe)
                creation_time = (
                    _parse_datetime(creation_time_str)
                    if creation_time_str else None
                )
                # Fallback to file mtime
                if creation_time is None:
                    creation_time = datetime.fromtimestamp(fpath.stat().st_mtime)

                clips.append({
                    "filename": fname,
                    "path": str(fpath),
                    "duration_sec": round(duration, 2),
                    "size_bytes": size,
                    "size_human": _human_size(size),
                    "width": width,
                    "height": height,
                    "resolution": f"{width}x{height}",
                    "fps": fps,
                    "video_codec": video_codec,
                    "has_audio": has_audio,
                    "audio_codec": audio_codec,
                    "audio_channels": audio_channels,
                    "creation_time": creation_time.isoformat(),
                    "camera": _parse_camera(fname),
                })

            elif ext in AUDIO_EXTS and DJI_RAW_RE.match(fname):
                dji_audio.append({"filename": fname, "path": str(fpath)})

            elif not fname.startswith('.'):
                other_files.append({"filename": fname, "path": str(fpath)})

    # Sort clips by creation_time
    clips.sort(key=lambda c: c["creation_time"])

    return {
        "clips": clips,
        "dji_audio": dji_audio,
        "other_files": other_files,
        "archive": archive_info,
    }


def group_scenes(clips: list, gap_minutes: float = 5.0) -> list:
    """
    Group clips into scenes based on timestamp gaps.

    A new scene starts when there's a gap > gap_minutes between
    consecutive clips (by creation_time + duration).

    Returns list of scene dicts with:
      - id: "01", "02", ...
      - suggested_name: "01_Scene_1", "02_Scene_2", ...
      - clips: list of clip filenames
      - clip_count: int
      - duration_sec: total duration
      - duration_human: formatted
      - type: "interview" or "broll"
      - reason: explanation
    """
    if not clips:
        return []

    gap_threshold = gap_minutes * 60  # seconds

    scenes = []
    current_scene_clips = [clips[0]]

    for i in range(1, len(clips)):
        prev = clips[i - 1]
        curr = clips[i]

        prev_end_time = _parse_datetime(prev["creation_time"])
        curr_start_time = _parse_datetime(curr["creation_time"])

        if prev_end_time and curr_start_time:
            # Add duration to get approximate end time of previous clip
            from datetime import timedelta
            prev_end = prev_end_time + timedelta(seconds=prev["duration_sec"])
            gap = (curr_start_time - prev_end).total_seconds()

            if gap > gap_threshold:
                # New scene
                scenes.append(current_scene_clips)
                current_scene_clips = [curr]
                continue

        current_scene_clips.append(curr)

    # Don't forget last scene
    scenes.append(current_scene_clips)

    result = []
    for idx, scene_clips in enumerate(scenes, 1):
        total_duration = sum(c["duration_sec"] for c in scene_clips)
        total_size = sum(c["size_bytes"] for c in scene_clips)
        avg_clip_duration = total_duration / len(scene_clips) if scene_clips else 0

        # Classify: short clips (<30s avg) = broll, otherwise interview
        if avg_clip_duration < 30:
            scene_type = "broll"
            type_reason = f"Короткие клипы (avg {avg_clip_duration:.0f}с)"
        else:
            scene_type = "interview"
            type_reason = f"Длинные клипы (avg {avg_clip_duration:.0f}с)"

        # Scene name
        type_label = "Broll" if scene_type == "broll" else "Scene"
        suggested_name = f"{idx:02d}_{type_label}_{idx}"

        # Time range
        first_time = scene_clips[0]["creation_time"][:19]
        last_time = scene_clips[-1]["creation_time"][:19]

        result.append({
            "id": f"{idx:02d}",
            "suggested_name": suggested_name,
            "clips": [c["filename"] for c in scene_clips],
            "first_clip": scene_clips[0]["filename"],
            "last_clip": scene_clips[-1]["filename"],
            "clip_count": len(scene_clips),
            "duration_sec": round(total_duration, 2),
            "duration_human": _human_duration(total_duration),
            "size_bytes": total_size,
            "size_human": _human_size(total_size),
            "time_range": f"{first_time} — {last_time}",
            "avg_clip_sec": round(avg_clip_duration, 1),
            "type": scene_type,
            "reason": type_reason,
        })

    return result


def build_inventory_summary(clips: list, dji_audio: list,
                            other_files: list, archive: dict) -> dict:
    """Build the inventory section of the discovery report."""
    if not clips:
        return {
            "total_files": 0,
            "total_size_human": "0 B",
            "total_duration_human": "0m 00s",
            "date_range": None,
            "cameras": [],
            "resolutions": {},
        }

    total_size = sum(c["size_bytes"] for c in clips)
    total_duration = sum(c["duration_sec"] for c in clips)
    cameras = sorted(set(c["camera"] for c in clips if c["camera"]))
    resolutions = {}
    for c in clips:
        res = c["resolution"]
        resolutions[res] = resolutions.get(res, 0) + 1

    return {
        "total_files": len(clips),
        "total_size_bytes": total_size,
        "total_size_human": _human_size(total_size),
        "total_duration_sec": round(total_duration, 2),
        "total_duration_human": _human_duration(total_duration),
        "date_range": {
            "earliest": clips[0]["creation_time"],
            "latest": clips[-1]["creation_time"],
        },
        "cameras": cameras,
        "resolutions": resolutions,
        "dji_audio_count": len(dji_audio),
        "other_files_count": len(other_files),
        "archive": archive,
    }
