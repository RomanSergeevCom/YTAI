#!/usr/bin/env python3
"""
YTAI Utils: Paths
Project paths, file search, backup.
"""

import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, List


# ============================================================================
# Project structure constants
# ============================================================================

VIDEO_DIR = "01_Media/Source/Video"
AUDIO_DIR = "01_Media/Source/Audio"
TRANSCRIPTION_DIR = "01_Media/Source/Transcription"
SETUP_DIR = "01_Media/Source/Setup"
DJI_PIPELINE_DIR = "99_Pipeline/DJI_Audio"
LOGS_DIR = "01_Media/Source/Setup/logs"

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}


# ============================================================================
# Project paths
# ============================================================================

def get_project_paths(project_dir: str) -> dict:
    """
    Get all project paths.

    Args:
        project_dir: Path to project folder

    Returns:
        Dict with all paths

    Raises:
        FileNotFoundError: If project folder does not exist
    """
    project_root = Path(project_dir).expanduser().resolve()
    
    if not project_root.exists():
        raise FileNotFoundError(f"Project folder not found: {project_root}")
    
    return {
        "project_root": project_root,
        "project_name": project_root.name,
        "video_dir": project_root / VIDEO_DIR,
        "audio_dir": project_root / AUDIO_DIR,
        "transcription_dir": project_root / TRANSCRIPTION_DIR,
        "setup_dir": project_root / SETUP_DIR,
        "dji_pipeline_dir": project_root / DJI_PIPELINE_DIR,
        "logs_dir": project_root / LOGS_DIR,
    }


def ensure_dirs(paths: dict) -> None:
    """Create all required directories."""
    for key in ["transcription_dir", "setup_dir", "logs_dir"]:
        if key in paths:
            paths[key].mkdir(parents=True, exist_ok=True)


# ============================================================================
# File search
# ============================================================================

def find_latest_file(directory: Path, pattern: str, exclude: Optional[List[str]] = None) -> Optional[Path]:
    """
    Find the latest file by pattern (by modification date).

    Args:
        directory: Directory to search in
        pattern: Glob pattern (e.g. "*_transcript_*.json")
        exclude: List of substrings to exclude

    Returns:
        Path to the latest file or None
    """
    if not directory.exists():
        return None
    
    files = list(directory.glob(pattern))
    
    # Exclude files with certain substrings
    if exclude:
        files = [f for f in files if not any(ex in f.name for ex in exclude)]
    
    # Exclude backup/
    files = [f for f in files if "backup" not in str(f)]
    
    if not files:
        return None
    
    # Sort by modification date (latest first)
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return files[0]


def find_latest_dir(directory: Path, pattern: str) -> Optional[Path]:
    """
    Find the latest directory by pattern.

    Args:
        directory: Directory to search in
        pattern: Glob pattern (e.g. "*_extract_speakers_*")

    Returns:
        Path to the latest directory or None
    """
    if not directory.exists():
        return None
    
    dirs = [d for d in directory.glob(pattern) if d.is_dir() and "backup" not in str(d)]
    
    if not dirs:
        return None
    
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return dirs[0]


# ============================================================================
# Backup
# ============================================================================

def move_to_backup(path: Path, backup_dir: Optional[Path] = None) -> Optional[Path]:
    """
    Move a file/folder to backup/.

    Args:
        path: File or folder to move
        backup_dir: Backup folder (default: next to path)

    Returns:
        New path in backup or None if path does not exist
    """
    if not path.exists():
        return None
    
    if backup_dir is None:
        backup_dir = path.parent / "backup"
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # If a file with the same name already exists in backup - add timestamp
    dest = backup_dir / path.name
    if dest.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if path.is_dir():
            dest = backup_dir / f"{path.name}_{timestamp}"
        else:
            dest = backup_dir / f"{path.stem}_{timestamp}{path.suffix}"
    
    shutil.move(str(path), str(dest))
    return dest


def cleanup_old_files(directory: Path, pattern: str, backup_dir: Optional[Path] = None) -> int:
    """
    Find files by pattern and move them to backup/.

    Args:
        directory: Directory to search in
        pattern: Glob pattern
        backup_dir: Backup folder (default: directory/backup)

    Returns:
        Number of moved files/folders
    """
    if not directory.exists():
        return 0
    
    if backup_dir is None:
        backup_dir = directory / "backup"
    
    items = list(directory.glob(pattern))
    # Exclude the backup folder itself
    items = [i for i in items if i.name != "backup" and "backup" not in str(i)]
    
    count = 0
    for item in items:
        if move_to_backup(item, backup_dir):
            count += 1
    
    return count


# ============================================================================
# Channel Profile
# ============================================================================

def find_channel_profile(project_root: Path) -> Optional[Path]:
    """
    Find a Channel Profile file in the project or parent folder.

    Searches for: *_Channel_Profile.txt, Channel_Profile.txt
    """
    patterns = ["*_Channel_Profile.txt", "Channel_Profile.txt", "channel_profile.txt"]
    
    # First in the project
    for pattern in patterns:
        files = list(project_root.glob(pattern))
        if files:
            return files[0]
    
    # Then in the parent folder
    parent = project_root.parent
    for pattern in patterns:
        files = list(parent.glob(pattern))
        if files:
            return files[0]
    
    return None


def load_channel_profile(project_root: Path) -> Optional[str]:
    """Load the contents of a Channel Profile."""
    profile_path = find_channel_profile(project_root)
    
    if profile_path and profile_path.exists():
        try:
            return profile_path.read_text(encoding="utf-8")
        except Exception:
            pass
    
    return None


# ============================================================================
# Extract guest name from project name
# ============================================================================

def extract_guest_hint(project_name: str) -> Optional[str]:
    """
    Extract guest name from project name.

    Examples:
        "YTCG37_Hadi_Dawani" -> "Hadi Dawani"
        "YTDemo_Ahmed_AlMutawa" -> "Ahmed AlMutawa"
        "YT_Interview_John_Smith" -> "John Smith"
        "YTPODCAST15_Maria_Garcia" -> "Maria Garcia"
    """
    # Remove YT prefix with any letters/digits up to the first _
    # YT, YTCG37, YTDemo, YTPODCAST15, etc.
    cleaned = re.sub(r'^YT[A-Za-z]*\d*_?', '', project_name)
    
    # Remove trailing dates (YYYYMMDD or YYMMDD)
    cleaned = re.sub(r'_?\d{6,8}$', '', cleaned)
    
    # Replace underscores with spaces
    cleaned = cleaned.replace('_', ' ').strip()
    
    # Check that it looks like a name (1-4 words)
    words = cleaned.split()
    if 1 <= len(words) <= 4:
        skip_words = {'interview', 'project', 'video', 'raw', 'edit', 'final', 'draft'}
        name_words = [w for w in words if w.lower() not in skip_words]
        if name_words:
            return ' '.join(name_words)
    
    return None
