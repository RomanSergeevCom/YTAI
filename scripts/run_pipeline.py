#!/usr/bin/env python3
"""
YTAI Pipeline Runner — single entry point for the full pipeline.

Usage:
    python run_pipeline.py "/Volumes/RYA Blue/Project"
    python run_pipeline.py "$PROJECT" --all --speakers 2
    python run_pipeline.py "$PROJECT" --only transcribe --speakers 2
    python run_pipeline.py "$PROJECT" --list
    python run_pipeline.py "$PROJECT" --dry-run

Phases:
    [1] Prepare files  (default)
        - Init v3.0 folder structure
        - Auto-organize media files (video → Source/Video/, audio → DJI_Audio/)
        - Extract audio from video clips + concat FULL_AUDIO
        - Sync DJI wireless audio (timezone auto-detected)

    [2] Transcribe  (requires --all or --only transcribe)
        - Whisper transcription + Pyannote speaker diarization

Speaker ID is done separately via Claude Desktop project.

Logs:
    01_Media/Source/Setup/logs/{project}_run_pipeline_{timestamp}.log
"""

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ============================================================================
# ANSI Colors
# ============================================================================

class C:
    """ANSI color codes for terminal output."""
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    BG_CYAN = "\033[46m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"
    BG_YELLOW = "\033[43m"
    RESET = "\033[0m"

_ANSI_RE = re.compile(r'\033\[[0-9;]*m')


def vlen(s: str) -> int:
    """Visual length of string (excluding ANSI escape codes)."""
    return len(_ANSI_RE.sub('', s))


def _trow(content: str, W: int = 60, border: str = "║") -> str:
    """Table row: pad content to W visual chars, add borders."""
    pad = W - vlen(content)
    return (f"  {C.DIM}{border}{C.RESET}{content}"
            f"{' ' * max(pad, 0)}{C.DIM}{border}{C.RESET}")


# ============================================================================
# Constants
# ============================================================================

SCRIPTS_DIR = Path(__file__).parent
TEMPLATES_DIR = SCRIPTS_DIR.parent / "YTAI_Folder_Templates"

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mts', '.avi', '.mkv'}
AUDIO_EXTS = {'.wav'}
LUT_EXTS = {'.cube'}
SIDECAR_EXTS = {'.xml'}

# DJI raw audio filename pattern: TX02_MIC037_20260306_102304_orig.wav
DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}', re.IGNORECASE)

# Short project code extraction: YTCG37_Setup_UAE_Company_Remotely → YTCG37
CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')


def project_code(project: Path) -> str:
    """Extract short code (e.g. 'YTCG37') from project folder name."""
    m = CODE_RE.match(project.name)
    return m.group(1) if m else project.name

# Camera audio (pre-extracted from video): RYA-ZVE1-1146_AUDIO.wav
CAMERA_AUDIO_RE = re.compile(r'^.+_AUDIO\.wav$', re.IGNORECASE)

# Scene folder pattern: 01_Interview, 02_Car, 03_Coffee, etc.
SCENE_DIR_RE = re.compile(r'^\d{2}_')

# v3.0 managed directories — skip during file discovery
V3_MANAGED_DIRS = {
    '01_Media', '02_Exports', '03_Shorts', '04_Thumbnail',
    'YouTube', '99_Pipeline',
}

# System/hidden dirs to always skip
SYSTEM_DIRS = {
    '.Spotlight-V100', '.fseventsd', '.Trashes',
    '.TemporaryItems', '__MACOSX', '.DocumentRevisions-V100',
    '_discovery',
}

# Archive/old dirs to skip (case-insensitive prefix match)
ARCHIVE_PREFIXES = ('archive', 'old_', 'backup', '_old', '_backup')

# Pipeline structure: 2 phases
#   Phase 1 (Prepare):    init folders + organize files + extract audio + DJI sync
#   Phase 2 (Transcribe): Whisper transcription + Pyannote diarization
PHASES = [
    {
        "id": "prepare",
        "name": "Prepare files",
        "stages": [
            {
                "id": "init",
                "name": "Init folders",
                "script": None,  # built-in
            },
            {
                "id": "extract_audio",
                "name": "Extract audio",
                "script": "01_prepare/0102_extract_audio/0102_extract_audio.py",
            },
            {
                "id": "sync_dji",
                "name": "DJI sync",
                "script": "01_prepare/0105_multiwindow_sync_dji/0105_multiwindow_sync_dji.py",
                "optional": True,
            },
        ],
    },
    {
        "id": "transcribe",
        "name": "Transcribe",
        "stages": [
            {
                "id": "transcribe",
                "name": "Transcribe",
                "script": "02_transcribe/020101_transcribe/transcribe_project.py",
            },
        ],
    },
]

PHASE_IDS = [p["id"] for p in PHASES]
ALL_STAGE_IDS = [s["id"] for p in PHASES for s in p["stages"]]
# For --only: accept both phase IDs and sub-stage IDs
ONLY_CHOICES = list(dict.fromkeys(PHASE_IDS + ALL_STAGE_IDS))


# ============================================================================
# Logger — dual output: file + console
# ============================================================================

class PipelineLogger:
    """
    Dual logger: writes to log file AND console simultaneously.

    - info()  → file + console (with ANSI colors in console, stripped in file)
    - debug() → file only (detailed debugging)
    - warn()  → file + console
    - error() → file + console
    """

    def __init__(self, log_path: Path = None, project: Path = None):
        self.log_file = None
        self.log_path = log_path
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = open(log_path, 'w', encoding='utf-8')
            self._write_header(project)

    def _write_header(self, project: Path = None):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.log_file.write(f"YTAI Pipeline Log\n")
        self.log_file.write(f"{'=' * 70}\n")
        self.log_file.write(f"Started:    {ts}\n")
        self.log_file.write(f"Python:     {sys.version.split()[0]} "
                            f"({sys.executable})\n")
        self.log_file.write(f"Platform:   {platform.system()} "
                            f"{platform.release()} ({platform.machine()})\n")
        self.log_file.write(f"Scripts:    {SCRIPTS_DIR}\n")

        # FFmpeg version
        try:
            r = subprocess.run(["ffmpeg", "-version"],
                               capture_output=True, text=True, timeout=5)
            ffv = r.stdout.split('\n')[0] if r.returncode == 0 else "not found"
        except Exception:
            ffv = "not found"
        self.log_file.write(f"FFmpeg:     {ffv}\n")

        # Disk space
        if project:
            try:
                st = os.statvfs(str(project))
                free = st.f_bavail * st.f_frsize
                total = st.f_blocks * st.f_frsize
                self.log_file.write(f"Disk free:  {fmt_size(free)} / "
                                    f"{fmt_size(total)}\n")
            except Exception:
                pass

        self.log_file.write(f"{'=' * 70}\n\n")
        self.log_file.flush()

    def info(self, msg: str = "", console: bool = True):
        self._write(msg, 'INFO', console)

    def debug(self, msg: str = ""):
        self._write(msg, 'DEBUG', console=False)

    def warn(self, msg: str = "", console: bool = True):
        self._write(msg, 'WARN', console)

    def error(self, msg: str = "", console: bool = True):
        self._write(msg, 'ERROR', console)

    def _write(self, msg: str, level: str, console: bool):
        if self.log_file:
            ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
            clean_msg = _ANSI_RE.sub('', msg)
            self.log_file.write(f"[{ts}] [{level:5}] {clean_msg}\n")
            self.log_file.flush()
        if console:
            print(msg)

    def close(self):
        if self.log_file:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            self.log_file.write(f"\n{'=' * 70}\n")
            self.log_file.write(f"Finished: {ts}\n")
            self.log_file.write(f"{'=' * 70}\n")
            self.log_file.close()


# ============================================================================
# Helpers
# ============================================================================

def fmt_duration(seconds: float) -> str:
    """Format seconds as 'Xm Ys'."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def fmt_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024**2:.1f} MB"
    else:
        return f"{size_bytes / 1024**3:.2f} GB"


def format_timecode(seconds: float, fps: int = 25) -> str:
    """Format seconds as SMPTE timecode HH:MM:SS:FF."""
    total_frames = int(round(seconds * fps))
    ff = total_frames % fps
    ss = (total_frames // fps) % 60
    mm = (total_frames // fps // 60) % 60
    hh = total_frames // fps // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _get_duration(path: Path) -> float:
    """Get media duration in seconds via ffprobe (0.0 on error)."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(path)],
            capture_output=True, text=True, timeout=10)
        import json as _json
        info = _json.loads(r.stdout)
        return float(info.get("format", {}).get("duration", 0))
    except Exception:
        return 0.0


def natural_sort_key(p: Path):
    """Natural sort key for file paths."""
    return [int(c) if c.isdigit() else c.lower()
            for c in re.split(r'(\d+)', p.name)]


def print_header(project_name: str) -> None:
    line = f"{C.CYAN}{'━' * 58}{C.RESET}"
    print(f"\n{line}")
    print(f"  {C.BOLD}YTAI Pipeline{C.RESET}  "
          f"{C.DIM}│{C.RESET}  {project_name}")
    print(f"{line}\n")


def print_footer(completed: int, total: int, elapsed: float,
                 project: Path, log_path: Path = None) -> None:
    line = f"{C.CYAN}{'━' * 58}{C.RESET}"
    print(f"\n{line}")
    print(f"  {C.GREEN}Done:{C.RESET} {completed}/{total} phases "
          f"in {C.DIM}{fmt_duration(elapsed)}{C.RESET}")

    # Project size
    try:
        total_size = sum(
            f.stat().st_size
            for f in (project / "01_Media").rglob("*") if f.is_file()
        )
        print(f"  Project size: {C.DIM}{fmt_size(total_size)}{C.RESET}")
    except Exception:
        pass

    print()
    print("  Output:")
    print(f"    per_clip/*/                              — per-clip audio + transcripts")
    print(f"    Setup/{{CODE}}_transcript.json             — main transcript")
    print(f"    Transcription/transcripts/{{CODE}}_*.srt  — subtitles")
    print(f"    Transcription/captions/{{CODE}}_*.srt     — captions")
    print(f"    Setup/{{CODE}}_transcript.xlsx             — Excel transcript")
    print(f"    Setup/{{CODE}}_ingest.json                 — Premiere UXP")
    if log_path:
        print()
        print(f"  Log: {C.DIM}{log_path}{C.RESET}")
    print()
    print("  Next:")
    print(f"    Speaker ID via Claude Desktop project")
    print(f'    Or: python 03_speaker_id/00_process_all.py --project "{project}"')
    print(f"{line}\n")


# ============================================================================
# File discovery — find media files outside v3.0 structure
# ============================================================================

def discover_media_files(project: Path, log: PipelineLogger) -> dict:
    """
    Scan project for media files that need to be organized.

    Looks for video, audio (WAV), LUT (.cube), and XML sidecar files
    that are NOT already in their correct v3.0 locations.

    WAV files are classified:
    - DJI raw (matches TX##_MIC###_YYYYMMDD_HHMMSS) → dji_audio
    - Other WAV → skipped_audio (left in place, likely pipeline output)

    Returns dict with 'videos', 'dji_audio', 'skipped_audio', 'lut',
    'sidecars' lists of Path objects.
    """
    video_dir = project / "01_Media" / "Source" / "Video"
    dji_dir = project / "99_Pipeline" / "DJI_Audio"
    lut_dir = project / "01_Media" / "Source" / "LUT"

    # Resolve skip roots for consistent path comparison
    skip_roots = set()
    for d in [
        video_dir, dji_dir, lut_dir,
        project / "01_Media" / "Source" / "Transcription",
        project / "01_Media" / "Source" / "Audio",
        project / "01_Media" / "Source" / "Setup",
        project / "01_Media" / "Assets",
        project / "02_Exports",
        project / "03_Shorts",
        project / "04_Thumbnail",
        project / "YouTube",
    ]:
        skip_roots.add(d.resolve())

    videos = []
    dji_audio = []
    camera_audio = []
    skipped_audio = []
    lut = []
    sidecars = []

    log.debug(f"Scanning for media files: {project}")
    log.debug(f"Skip roots ({len(skip_roots)}):")
    for sr in sorted(skip_roots):
        log.debug(f"  - {sr}")

    for root, dirs, files in os.walk(project):
        root_path = Path(root).resolve()

        # Skip system/hidden/archive directories
        dirs[:] = [d for d in dirs
                   if d not in SYSTEM_DIRS
                   and not d.startswith('.')
                   and not d.lower().startswith(ARCHIVE_PREFIXES)]

        # Skip v3.0 managed directories
        if any(root_path == sr or
               str(root_path).startswith(str(sr) + os.sep)
               for sr in skip_roots):
            log.debug(f"  Skip managed: {root_path}")
            dirs.clear()
            continue

        for fname in files:
            if fname.startswith('.'):
                continue
            fp = Path(root) / fname
            ext = fp.suffix.lower()

            try:
                rel = fp.relative_to(project)
                size = fp.stat().st_size
            except (ValueError, OSError):
                continue

            if ext in VIDEO_EXTS:
                videos.append(fp)
                log.debug(f"  Found video: {rel} ({fmt_size(size)})")
            elif ext in AUDIO_EXTS:
                if DJI_RAW_RE.match(fname):
                    dji_audio.append(fp)
                    log.debug(f"  Found DJI audio: {rel} ({fmt_size(size)})")
                elif CAMERA_AUDIO_RE.match(fname):
                    camera_audio.append(fp)
                    log.debug(f"  Found camera audio: {rel} ({fmt_size(size)})")
                else:
                    skipped_audio.append(fp)
                    log.debug(f"  Skip audio (not DJI/camera): {rel}")
            elif ext in LUT_EXTS:
                lut.append(fp)
                log.debug(f"  Found LUT: {rel} ({fmt_size(size)})")
            elif ext in SIDECAR_EXTS:
                sidecars.append(fp)
                log.debug(f"  Found sidecar: {rel} ({fmt_size(size)})")

    # Sort naturally
    for lst in (videos, dji_audio, camera_audio, skipped_audio, lut, sidecars):
        lst.sort(key=natural_sort_key)

    log.debug(f"Discovery: {len(videos)} video, {len(dji_audio)} DJI audio, "
              f"{len(camera_audio)} camera audio, "
              f"{len(skipped_audio)} skipped audio, {len(lut)} LUT, "
              f"{len(sidecars)} sidecars")

    return {
        "videos": videos,
        "dji_audio": dji_audio,
        "camera_audio": camera_audio,
        "skipped_audio": skipped_audio,
        "lut": lut,
        "sidecars": sidecars,
    }


def print_file_table(files: list, label: str, log: PipelineLogger):
    """Print a detailed table of files with sizes."""
    if not files:
        return

    total_size = sum(f.stat().st_size for f in files)
    log.info(f"      {label}: {len(files)} files ({fmt_size(total_size)})")

    for f in files:
        size = f.stat().st_size
        log.info(f"        {C.DIM}│{C.RESET} {f.name:<43} "
                 f"{C.DIM}{fmt_size(size):>10}{C.RESET}")


def _xml_to_clip_id(xml_path: Path, video_stems: set) -> str | None:
    """
    Extract clip_id from XML sidecar filename.

    Sony naming: RYA-FX3-0099M01.XML → clip_id = RYA-FX3-0099
    Strip trailing M## suffix and check against known video stems.
    """
    stem = xml_path.stem
    # Try stripping M## suffix (Sony convention)
    match = re.match(r'^(.+?)M\d+$', stem, re.IGNORECASE)
    if match:
        candidate = match.group(1)
        if candidate in video_stems:
            return candidate
    # Direct match (XML stem == video stem)
    if stem in video_stems:
        return stem
    return None


def organize_media_files(project: Path, discovered: dict,
                         log: PipelineLogger,
                         dry_run: bool = False) -> bool:
    """
    Move discovered media files to their v3.0 locations.

    - Video → 01_Media/Source/Video/ (preserving scene subfolders)
    - DJI audio (raw) → 99_Pipeline/DJI_Audio/
    - Camera audio → Transcription/per_clip/{clip}/
    - LUT (.cube) → 01_Media/Source/LUT/
    - XML sidecars → Transcription/per_clip/{clip}/ (matched to video)
    """
    video_dir = project / "01_Media" / "Source" / "Video"
    dji_dir = project / "99_Pipeline" / "DJI_Audio"
    lut_dir = project / "01_Media" / "Source" / "LUT"
    tr_dir = project / "01_Media" / "Source" / "Transcription"

    # Standard moves (label, files, destination) — flat destination
    moves = [
        ("DJI audio", discovered["dji_audio"], dji_dir),
        ("LUT", discovered["lut"], lut_dir),
    ]

    total_files = (sum(len(m[1]) for m in moves) +
                   len(discovered["videos"]) +
                   len(discovered.get("camera_audio", [])) +
                   len(discovered["sidecars"]))
    if total_files == 0:
        return True

    all_ok = True

    # Move video files — preserve scene subfolders (01_Interview, 02_Car, etc.)
    if discovered["videos"]:
        video_dir.mkdir(parents=True, exist_ok=True)
        total_size = sum(f.stat().st_size for f in discovered["videos"])
        log.info(f"      Moving {len(discovered['videos'])} video "
                 f"{C.DIM}({fmt_size(total_size)}){C.RESET} → "
                 f"{video_dir.relative_to(project)}/")

        for f in discovered["videos"]:
            scene = _get_scene_name(f, project)
            if scene:
                dest = video_dir / scene
            else:
                dest = video_dir
            dest.mkdir(parents=True, exist_ok=True)
            dst = dest / f.name

            if dst.exists():
                log.warn(f"        {C.YELLOW}⚠{C.RESET} Already exists, "
                         f"skip: {f.name}")
                continue

            if dry_run:
                scene_tag = f" ({scene})" if scene else ""
                log.info(f"        → Would move: {f.name}{scene_tag}")
                continue

            try:
                size = f.stat().st_size
                shutil.move(str(f), str(dst))
                scene_tag = f" → {scene}/" if scene else ""
                log.info(f"        {C.GREEN}✓{C.RESET} {f.name}{scene_tag} "
                         f"{C.DIM}({fmt_size(size)}){C.RESET}")
            except Exception as e:
                log.error(f"        {C.RED}✗{C.RESET} Failed: {f.name}: {e}")
                all_ok = False

    # Move camera audio (pre-extracted) → Transcription/per_clip/{clip}/
    cam_audio = discovered.get("camera_audio", [])
    if cam_audio:
        total_size = sum(f.stat().st_size for f in cam_audio)
        log.info(f"      Moving {len(cam_audio)} camera audio "
                 f"{C.DIM}({fmt_size(total_size)}){C.RESET} → per_clip/")

        for f in cam_audio:
            stem = f.stem
            if stem.upper().endswith("_AUDIO"):
                stem = stem[:-6]  # Strip _AUDIO suffix
            per_clip = tr_dir / "per_clip" / stem
            per_clip.mkdir(parents=True, exist_ok=True)
            dst = per_clip / f.name

            if dst.exists():
                log.warn(f"        {C.YELLOW}⚠{C.RESET} Already exists, "
                         f"skip: {f.name}")
                continue

            if dry_run:
                log.info(f"        → Would move: {f.name} → per_clip/{stem}/")
                continue

            try:
                size = f.stat().st_size
                shutil.move(str(f), str(dst))
                log.info(f"        {C.GREEN}✓{C.RESET} {f.name} → per_clip/{stem}/ "
                         f"{C.DIM}({fmt_size(size)}){C.RESET}")
            except Exception as e:
                log.error(f"        {C.RED}✗{C.RESET} Failed: {f.name}: {e}")
                all_ok = False

    # Move standard files (DJI audio, LUT)
    for label, files, dest in moves:
        if not files:
            continue

        dest.mkdir(parents=True, exist_ok=True)
        rel_dest = dest.relative_to(project)
        total_size = sum(f.stat().st_size for f in files)
        log.info(f"      Moving {len(files)} {label.lower()} "
                 f"{C.DIM}({fmt_size(total_size)}){C.RESET} → {rel_dest}/")

        for f in files:
            dst = dest / f.name

            if dst.exists():
                log.warn(f"        {C.YELLOW}⚠{C.RESET} Already exists, "
                         f"skip: {f.name}")
                continue

            if dry_run:
                log.info(f"        → Would move: {f.name}")
                continue

            try:
                size = f.stat().st_size
                log.debug(f"        Move: {f} → {dst}")
                shutil.move(str(f), str(dst))
                log.info(f"        {C.GREEN}✓{C.RESET} {f.name} "
                         f"{C.DIM}({fmt_size(size)}){C.RESET}")
            except Exception as e:
                log.error(f"        {C.RED}✗{C.RESET} Failed: {f.name}: {e}")
                all_ok = False

    # Move XML sidecars → per_clip/{clip}/
    if discovered["sidecars"]:
        # Collect video stems for matching (from already-moved + existing)
        video_stems = set()
        for v in discovered["videos"]:
            video_stems.add(v.stem)
        for v in _list_videos_recursive(video_dir):
            video_stems.add(v.stem)

        log.info(f"      Moving {len(discovered['sidecars'])} sidecar(s) "
                 f"→ per_clip/")

        for xml_f in discovered["sidecars"]:
            clip_id = _xml_to_clip_id(xml_f, video_stems)
            if clip_id:
                per_clip = tr_dir / "per_clip" / clip_id
                per_clip.mkdir(parents=True, exist_ok=True)
                dst = per_clip / xml_f.name
            else:
                # Fallback: put in Video/ if no clip match
                video_dir.mkdir(parents=True, exist_ok=True)
                dst = video_dir / xml_f.name
                log.warn(f"        {C.YELLOW}⚠{C.RESET} No clip match "
                         f"for {xml_f.name}, → Video/")

            if dst.exists():
                log.warn(f"        {C.YELLOW}⚠{C.RESET} Already exists, "
                         f"skip: {xml_f.name}")
                continue

            if dry_run:
                target = dst.parent.relative_to(project)
                log.info(f"        → Would move: {xml_f.name} → {target}/")
                continue

            try:
                size = xml_f.stat().st_size
                shutil.move(str(xml_f), str(dst))
                rel_dst = dst.parent.relative_to(project)
                log.info(f"        {C.GREEN}✓{C.RESET} {xml_f.name} "
                         f"→ {rel_dst}/ {C.DIM}({fmt_size(size)}){C.RESET}")
            except Exception as e:
                log.error(f"        {C.RED}✗{C.RESET} Failed: "
                          f"{xml_f.name}: {e}")
                all_ok = False

    # Log skipped audio
    if discovered["skipped_audio"]:
        log.info(f"      Skipped {len(discovered['skipped_audio'])} "
                 f"audio file(s) (not DJI raw):")
        for f in discovered["skipped_audio"]:
            try:
                rel = f.relative_to(project)
            except ValueError:
                rel = f.name
            log.info(f"        {C.DIM}⏭ {rel}{C.RESET}")

    # Clean up empty directories left after moving
    if not dry_run:
        _cleanup_empty_dirs(project, log)

    return all_ok


def _cleanup_empty_dirs(project: Path, log: PipelineLogger):
    """Remove empty directories left after file organization."""
    for root, dirs, files in os.walk(project, topdown=False):
        root_path = Path(root)

        if root_path == project:
            continue

        try:
            rel = root_path.relative_to(project)
            top_dir = str(rel).split(os.sep)[0]
            if top_dir in V3_MANAGED_DIRS:
                continue
        except ValueError:
            continue

        remaining = [f for f in os.listdir(root_path)
                     if not f.startswith('.')]
        if not remaining:
            try:
                for hidden in os.listdir(root_path):
                    (root_path / hidden).unlink()
                root_path.rmdir()
                log.debug(f"  Removed empty dir: {rel}")
            except Exception:
                pass


# ============================================================================
# Pre-stage validation — detailed checks before each sub-stage
# ============================================================================

def validate_prerequisites(stage_id: str, project: Path,
                           log: PipelineLogger) -> bool:
    """
    Pre-flight validation for a pipeline sub-stage.
    Prints file statistics and returns True if ready.
    """
    if stage_id == "init":
        return True
    elif stage_id == "extract_audio":
        return _validate_extract_audio(project, log)
    elif stage_id == "sync_dji":
        return _validate_sync_dji(project, log)
    elif stage_id == "transcribe":
        return _validate_transcribe(project, log)
    return True


def _validate_extract_audio(project: Path, log: PipelineLogger) -> bool:
    video_dir = project / "01_Media" / "Source" / "Video"

    if not video_dir.is_dir():
        log.error(f"      {C.RED}✗{C.RESET} Video directory missing: "
                  f"Source/Video/")
        return False

    videos = _list_videos_recursive(video_dir)

    if not videos:
        log.error(f"      {C.RED}✗{C.RESET} No video files in Source/Video/")
        return False

    total_size = sum(f.stat().st_size for f in videos)
    log.info(f"      Input: {len(videos)} video files "
             f"{C.DIM}({fmt_size(total_size)}){C.RESET}")
    for v in videos:
        log.info(f"        {v.name:<43} "
                 f"{C.DIM}{fmt_size(v.stat().st_size):>10}{C.RESET}")
    log.info(f"      Output → per_clip/{{clip}}/ (WAV) + "
             f"Transcription/ (FULL_AUDIO)")
    return True


def _validate_sync_dji(project: Path, log: PipelineLogger) -> bool:
    video_dir = project / "01_Media" / "Source" / "Video"
    dji_dir = project / "99_Pipeline" / "DJI_Audio"

    videos = _list_videos_recursive(video_dir)

    if not videos:
        log.error(f"      {C.RED}✗{C.RESET} No video files in Source/Video/")
        return False

    log.info(f"      Video: {len(videos)} files")

    dji_files = sorted(
        [f for f in dji_dir.iterdir()
         if f.is_file() and f.suffix.lower() == '.wav'],
        key=natural_sort_key
    ) if dji_dir.is_dir() else []

    if not dji_files:
        log.error(f"      {C.RED}✗{C.RESET} No DJI audio in "
                  f"99_Pipeline/DJI_Audio/")
        return False

    total_dji = sum(f.stat().st_size for f in dji_files)
    log.info(f"      DJI audio: {len(dji_files)} files "
             f"{C.DIM}({fmt_size(total_dji)}){C.RESET}")
    for d in dji_files:
        log.info(f"        {d.name:<43} "
                 f"{C.DIM}{fmt_size(d.stat().st_size):>10}{C.RESET}")
    log.info(f"      Output → Source/Audio/ (synced WAV per clip)")
    return True


def _validate_transcribe(project: Path, log: PipelineLogger) -> bool:
    video_dir = project / "01_Media" / "Source" / "Video"

    videos = _list_videos_recursive(video_dir)

    if not videos:
        log.error(f"      {C.RED}✗{C.RESET} No video files in Source/Video/")
        return False

    total_size = sum(f.stat().st_size for f in videos)
    log.info(f"      Input: {len(videos)} video files "
             f"{C.DIM}({fmt_size(total_size)}){C.RESET}")
    for v in videos:
        log.info(f"        {v.name:<43} "
                 f"{C.DIM}{fmt_size(v.stat().st_size):>10}{C.RESET}")

    # Informational: existing artifacts
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    full_audio = list(tr_dir.glob("*_FULL_AUDIO.wav")) \
        if tr_dir.is_dir() else []
    if full_audio:
        fa = full_audio[0]
        log.info(f"      FULL_AUDIO: {fa.name} "
                 f"{C.DIM}({fmt_size(fa.stat().st_size)}){C.RESET}")
        log.info(f"        (transcribe extracts own 16kHz audio from video)")

    audio_dir = project / "01_Media" / "Source" / "Audio"
    synced = sorted(
        [f for f in audio_dir.rglob("*")
         if f.is_file() and f.suffix.lower() == '.wav'],
        key=natural_sort_key
    ) if audio_dir.is_dir() else []
    if synced:
        log.info(f"      DJI synced: {len(synced)} files "
                 f"{C.DIM}(included in ingest.json){C.RESET}")

    log.info(f"      Output → per_clip/ + Transcription/ + "
             f"Setup/ingest.json")
    return True


# ============================================================================
# Post-stage verification — check outputs after each sub-stage
# ============================================================================

def verify_stage_output(stage_id: str, project: Path,
                        log: PipelineLogger):
    """Verify expected outputs after a sub-stage completes."""
    if stage_id == "extract_audio":
        _verify_extract_audio(project, log)
    elif stage_id == "sync_dji":
        _verify_sync_dji(project, log)
    elif stage_id == "transcribe":
        _verify_transcribe(project, log)


def _verify_extract_audio(project: Path, log: PipelineLogger):
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    per_clip_dir = tr_dir / "per_clip"

    # Find per-clip audio WAVs in per_clip/{clip}/
    audio_files = []
    if per_clip_dir.is_dir():
        for clip_dir in sorted(per_clip_dir.iterdir(), key=natural_sort_key):
            if clip_dir.is_dir():
                for f in clip_dir.glob("*_AUDIO.wav"):
                    audio_files.append(f)

    full_audio = list(tr_dir.glob("*_FULL_AUDIO.wav")) \
        if tr_dir.is_dir() else []

    log.info(f"      Verify extract_audio:")
    if audio_files:
        total = sum(f.stat().st_size for f in audio_files)
        log.info(f"        Per-clip: {len(audio_files)} files "
                 f"{C.DIM}({fmt_size(total)}){C.RESET}")
        for a in audio_files:
            rel = a.relative_to(tr_dir)
            log.info(f"          {C.GREEN}✓{C.RESET} {str(rel):<41} "
                     f"{C.DIM}{fmt_size(a.stat().st_size):>10}{C.RESET}")
    else:
        log.warn(f"        {C.YELLOW}⚠{C.RESET} No per-clip audio files")

    if full_audio:
        fa = full_audio[0]
        log.info(f"        FULL_AUDIO: {fa.name} "
                 f"{C.DIM}({fmt_size(fa.stat().st_size)}){C.RESET}")
    else:
        log.warn(f"        {C.YELLOW}⚠{C.RESET} FULL_AUDIO.wav not found!")

    logs_dir = project / "01_Media" / "Source" / "Setup" / "logs"
    stage_logs = sorted(logs_dir.glob("*_extract_audio_*.log")) \
        if logs_dir.is_dir() else []
    if stage_logs:
        log.debug(f"        Stage log: {stage_logs[-1].name}")


def _verify_sync_dji(project: Path, log: PipelineLogger):
    audio_dir = project / "01_Media" / "Source" / "Audio"

    synced = sorted(
        [f for f in audio_dir.rglob("*")
         if f.is_file() and f.suffix.lower() == '.wav'],
        key=natural_sort_key
    ) if audio_dir.is_dir() else []

    log.info(f"      Verify sync_dji:")
    if synced:
        total = sum(f.stat().st_size for f in synced)
        log.info(f"        Synced: {len(synced)} files "
                 f"{C.DIM}({fmt_size(total)}){C.RESET}")
        for s in synced:
            log.info(f"          {C.GREEN}✓{C.RESET} {s.name:<41} "
                     f"{C.DIM}{fmt_size(s.stat().st_size):>10}{C.RESET}")
    else:
        log.warn(f"        {C.YELLOW}⚠{C.RESET} No synced audio files")


def _verify_transcribe(project: Path, log: PipelineLogger):
    src_dir = project / "01_Media" / "Source"
    tr_dir = src_dir / "Transcription"
    setup_dir = src_dir / "Setup"

    log.info(f"      Verify transcribe:")

    # Check Source/ first (v3 new), then Transcription/ (legacy)
    transcripts = list(src_dir.glob("*_transcript.json"))
    if not transcripts:
        transcripts = list(tr_dir.glob("*_transcript.json")) \
            if tr_dir.is_dir() else []
    if transcripts:
        t = transcripts[0]
        log.info(f"        {C.GREEN}✓{C.RESET} Transcript: {t.name} "
                 f"{C.DIM}({fmt_size(t.stat().st_size)}){C.RESET}")
    else:
        log.warn(f"        {C.YELLOW}⚠{C.RESET} Transcript JSON not found!")

    srts = list(src_dir.glob("*_transcript.srt"))
    if not srts:
        srts = list(tr_dir.glob("*_transcript.srt")) \
            if tr_dir.is_dir() else []
    if srts:
        log.info(f"        {C.GREEN}✓{C.RESET} SRT: {srts[0].name}")

    xlsxs = list(src_dir.glob("*_transcript.xlsx"))
    if not xlsxs:
        xlsxs = list(tr_dir.glob("*_transcript.xlsx")) \
            if tr_dir.is_dir() else []
    if xlsxs:
        log.info(f"        {C.GREEN}✓{C.RESET} XLSX: {xlsxs[0].name}")

    per_clip = tr_dir / "per_clip" if tr_dir else None
    if per_clip and per_clip.is_dir():
        clips = [d for d in per_clip.iterdir() if d.is_dir()]
        log.info(f"        {C.GREEN}✓{C.RESET} Per-clip: {len(clips)} clips")
        for c in sorted(clips, key=natural_sort_key):
            n = len(list(c.iterdir()))
            log.info(f"            {c.name}/ "
                     f"{C.DIM}({n} files){C.RESET}")

    ingest = list(setup_dir.glob("*_ingest.json")) \
        if setup_dir.is_dir() else []
    if ingest:
        log.info(f"        {C.GREEN}✓{C.RESET} Ingest: {ingest[0].name} "
                 f"{C.DIM}({fmt_size(ingest[0].stat().st_size)}){C.RESET}")
    else:
        log.warn(f"        {C.YELLOW}⚠{C.RESET} Ingest JSON not found!")


# ============================================================================
# Stage checks — determine if a sub-stage was already completed
# ============================================================================

def check_init(project: Path) -> bool:
    """True if v3.0 folder structure exists."""
    return (project / "01_Media" / "Source" / "Video").is_dir()


def check_extract_audio(project: Path) -> bool:
    """True if FULL_AUDIO.wav exists."""
    tr = project / "01_Media" / "Source" / "Transcription"
    return tr.is_dir() and any(tr.glob("*_FULL_AUDIO.wav"))


def check_sync_dji(project: Path) -> bool:
    """True if synced DJI audio exists (supports scene subfolders)."""
    audio = project / "01_Media" / "Source" / "Audio"
    return audio.is_dir() and any(audio.rglob("*.wav"))


def check_transcribe(project: Path) -> bool:
    """True if transcript JSON exists (check Source/ then Transcription/)."""
    src = project / "01_Media" / "Source"
    if any(src.glob("*_transcript.json")):
        return True
    tr = src / "Transcription"
    return tr.is_dir() and any(tr.glob("*_transcript.json"))


def has_dji_files(project: Path) -> bool:
    """True if DJI source audio files exist."""
    dji = project / "99_Pipeline" / "DJI_Audio"
    if not dji.is_dir():
        return False
    return any(dji.glob("*.wav"))


def _list_videos_recursive(video_dir: Path) -> list:
    """Find video files in Source/Video/ recursively (supports scene subfolders)."""
    if not video_dir.is_dir():
        return []
    return sorted(
        [f for f in video_dir.rglob("*")
         if f.is_file() and f.suffix.lower() in VIDEO_EXTS
         and not f.name.startswith(".")],
        key=natural_sort_key)


def _get_scene_name(file_path: Path, project: Path) -> str | None:
    """If file is inside a scene folder (01_Interview/ etc.), return folder name."""
    try:
        rel = file_path.parent.relative_to(project)
        top = rel.parts[0] if rel.parts else None
        if top and SCENE_DIR_RE.match(top):
            return top
    except ValueError:
        pass
    return None


def has_video_files(project: Path) -> bool:
    """True if video source files exist in Source/Video/ (recursive)."""
    video = project / "01_Media" / "Source" / "Video"
    return len(_list_videos_recursive(video)) > 0


CHECK_FNS = {
    # "init" is NOT here — always runs (handles organize + idempotency)
    "extract_audio": check_extract_audio,
    "sync_dji": check_sync_dji,
    "transcribe": check_transcribe,
}


# ============================================================================
# Init sub-stage — create folder structure + organize media files
# ============================================================================

def _deep_merge_template(template_path: Path, project: Path,
                         log: PipelineLogger) -> int:
    """
    Recursively merge template into project, creating missing dirs/files.

    Unlike shallow copy, this creates ALL nested directories from template,
    even if parent dirs already exist. Skips .gitkeep files.

    Returns count of created directories.
    """
    created = 0
    for root, dirs, files in os.walk(template_path):
        rel = Path(root).relative_to(template_path)
        dst_dir = project / rel
        if not dst_dir.exists():
            dst_dir.mkdir(parents=True, exist_ok=True)
            log.debug(f"  Created dir: {rel}/")
            created += 1
        for fname in files:
            if fname == ".gitkeep":
                continue
            dst_file = dst_dir / fname
            if not dst_file.exists():
                shutil.copy2(str(Path(root) / fname), str(dst_file))
                log.debug(f"  Copied file: {rel / fname}")
    return created




def run_init(project: Path, folder_type: str,
             log: PipelineLogger, dry_run: bool = False) -> bool:
    """
    Create v3.0 folder structure and auto-organize media files.

    1. Deep merge template (creates ALL missing dirs/files)
    2. Create/rename Premiere project files
    3. Discover media files outside v3.0 directories
    4. Move: video → Source/Video/, DJI → DJI_Audio/, LUT → LUT/,
       XML → per_clip/{clip}/
    5. Print project summary
    """
    # Step 1: Deep merge template
    template_name = ("Type1_Footage" if folder_type == "footage"
                     else "Type2_Production")
    template_path = TEMPLATES_DIR / template_name

    if not template_path.is_dir():
        log.error(f"      {C.RED}✗{C.RESET} Template not found: "
                  f"{template_path}")
        return False

    if dry_run:
        log.info(f"      → Would merge {folder_type} from {template_name}/")
    else:
        created = _deep_merge_template(template_path, project, log)
        if created > 0:
            log.info(f"      {C.GREEN}✓{C.RESET} Created {created} "
                     f"directories from {template_name}")
        else:
            log.info(f"      Folder structure: {C.GREEN}✓{C.RESET} complete")

    # Step 2: Discover media files
    log.info("")
    log.info("      Scanning for media files...")
    discovered = discover_media_files(project, log)

    total = (len(discovered["videos"]) + len(discovered["dji_audio"]) +
             len(discovered["lut"]) + len(discovered["sidecars"]))

    if total > 0:
        log.info(f"      Found {total} files to organize:")
        print_file_table(discovered["videos"], "Video", log)
        print_file_table(discovered["dji_audio"], "DJI audio (raw)", log)
        print_file_table(discovered["lut"], "LUT", log)
        print_file_table(discovered["sidecars"], "Sidecar (XML)", log)
        log.info("")

        # Step 4: Move files
        if not organize_media_files(project, discovered, log,
                                    dry_run=dry_run):
            log.error(f"      {C.RED}✗{C.RESET} Some files failed to move")
            return False

        if not dry_run:
            log.info(f"      {C.GREEN}✓{C.RESET} All files organized")
    else:
        log.info(f"      All files already in place "
                 f"{C.GREEN}✓{C.RESET}")

    # Step 5: Create Premiere Pro project (copy template)
    #   Clean up leftover PROJECT_NAME*.prproj from old templates
    for stale in [project / "01_Media" / "PROJECT_NAME.prproj",
                  project / "01_Media" / "Source" / "PROJECT_NAME_Source.prproj"]:
        if stale.exists() and not dry_run:
            stale.unlink()

    prproj_path = project / "01_Media" / f"{project.name}.prproj"
    if not prproj_path.exists():
        _prproj_template = (
            SCRIPTS_DIR / "01_prepare" / "0101_init_folders"
            / "RYA_example.prproj")
        if _prproj_template.exists():
            if dry_run:
                log.info(f"      → Would create {prproj_path.name}")
            else:
                prproj_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_prproj_template, prproj_path)
                log.info(f"      {C.GREEN}✓{C.RESET} "
                         f"{prproj_path.name}  "
                         f"{C.DIM}(Premiere Pro project){C.RESET}")
        else:
            log.info(f"      {C.YELLOW}⚠{C.RESET} "
                     f"Premiere template not found: "
                     f"{_prproj_template}")
    else:
        log.info(f"      {prproj_path.name}  "
                 f"{C.DIM}already exists{C.RESET}")

    # Step 6: Rename PROJECT_NAME.gdoc → {project_name}.gdoc
    gdoc_path = project / f"{project.name}.gdoc"
    template_gdoc = project / "PROJECT_NAME.gdoc"
    if not gdoc_path.exists():
        if template_gdoc.exists():
            if dry_run:
                log.info(f"      → Would rename PROJECT_NAME.gdoc → "
                         f"{gdoc_path.name}")
            else:
                template_gdoc.rename(gdoc_path)
                log.info(f"      {C.GREEN}✓{C.RESET} "
                         f"{gdoc_path.name}  "
                         f"{C.DIM}(Google Doc){C.RESET}")
    else:
        if template_gdoc.exists() and not dry_run:
            template_gdoc.unlink()  # remove leftover template
        log.info(f"      {gdoc_path.name}  "
                 f"{C.DIM}already exists{C.RESET}")

    return True


def _list_media(dirpath: Path, exts: set) -> list:
    """List media files in dir recursively, sorted naturally."""
    if not dirpath.is_dir():
        return []
    files = [f for f in dirpath.rglob("*")
             if f.is_file() and f.suffix.lower() in exts
             and not f.name.startswith('.')]
    files.sort(key=natural_sort_key)
    return files


def _dir_summary(dirpath: Path, exts: set = None) -> str:
    """One-line summary: N files (X MB) or —."""
    if not dirpath.is_dir():
        return f"{C.DIM}—{C.RESET}"
    if exts:
        files = [f for f in dirpath.iterdir()
                 if f.is_file() and f.suffix.lower() in exts
                 and not f.name.startswith('.')]
    else:
        files = [f for f in dirpath.iterdir()
                 if f.is_file() and not f.name.startswith('.')]
    if not files:
        return f"{C.DIM}—{C.RESET}"
    total = sum(f.stat().st_size for f in files)
    return f"{len(files)} files {C.DIM}({fmt_size(total)}){C.RESET}"


def print_project_tree(project: Path, log: PipelineLogger):
    """Print project structure as ASCII tree after prepare phase."""
    W = 58
    log.info(f"  {C.DIM}╭{'─' * W}╮{C.RESET}")
    log.info(f"  {C.DIM}│{C.RESET}  "
             f"{C.BOLD}Project Structure{C.RESET}"
             f"{' ' * (W - 20)}{C.DIM}│{C.RESET}")
    log.info(f"  {C.DIM}├{'─' * W}┤{C.RESET}")

    name = project.name
    media = project / "01_Media"
    source = media / "Source"
    video_dir = source / "Video"
    audio_dir = source / "Audio"
    lut_dir = source / "LUT"
    tr_dir = source / "Transcription"
    per_clip = tr_dir / "per_clip"
    setup_dir = source / "Setup"
    dji_dir = project / "99_Pipeline" / "DJI_Audio"

    # Tree characters
    T = "├── "
    L = "└── "
    I = "│   "
    S = "    "

    # Gather data
    videos = _list_media(video_dir, VIDEO_EXTS)
    dji_files = _list_media(dji_dir, AUDIO_EXTS)
    lut_files = _list_media(lut_dir, LUT_EXTS)
    audio_files = _list_media(audio_dir, AUDIO_EXTS)
    full_audio = list(tr_dir.glob("*_FULL_AUDIO.wav")) if tr_dir.is_dir() else []
    clip_dirs = sorted([d for d in per_clip.iterdir() if d.is_dir()],
                       key=natural_sort_key) if per_clip.is_dir() else []
    assets_dir = media / "Assets"
    asset_subs = sorted([d.name for d in assets_dir.iterdir() if d.is_dir()]
                        ) if assets_dir.is_dir() else []

    # --- Print tree ---
    log.info(f"  {C.BOLD}{name}/{C.RESET}")
    log.info(f"  │")

    # 01_Media/
    log.info(f"  {T}{C.BOLD}01_Media/{C.RESET}")

    # .prproj (inside 01_Media/)
    prproj = media / f"{name}.prproj"
    if prproj.exists():
        log.info(f"  {I}{T}{prproj.name}")

    # Assets/
    if asset_subs:
        subs_str = " ".join(f"{C.DIM}{s}/{C.RESET}" for s in asset_subs)
        log.info(f"  {I}{T}Assets/  {subs_str}")

    # Source/
    log.info(f"  {I}{L}{C.BOLD}Source/{C.RESET}")
    src_p = f"  {I}{S}"  # prefix inside Source

    # Video/
    if videos:
        total_v = sum(f.stat().st_size for f in videos)
        log.info(f"{src_p}{T}{C.BOLD}Video/{C.RESET}"
                 f"  {len(videos)} clips "
                 f"{C.DIM}({fmt_size(total_v)}){C.RESET}")
        for i, v in enumerate(videos):
            connector = L if i == len(videos) - 1 else T
            sz = fmt_size(v.stat().st_size)
            log.info(f"{src_p}{I}{connector}{v.name}"
                     f"  {C.DIM}{sz}{C.RESET}")
    else:
        log.info(f"{src_p}{T}Video/  {C.DIM}—{C.RESET}")

    # Audio/
    if audio_files:
        total_a = sum(f.stat().st_size for f in audio_files)
        log.info(f"{src_p}{T}{C.BOLD}Audio/{C.RESET}"
                 f"  {len(audio_files)} synced "
                 f"{C.DIM}({fmt_size(total_a)}){C.RESET}")
    elif dji_files:
        log.info(f"{src_p}{T}Audio/"
                 f"  {C.YELLOW}⚠ sync failed{C.RESET}")
    else:
        log.info(f"{src_p}{T}Audio/  {C.DIM}—{C.RESET}")

    # LUT/
    log.info(f"{src_p}{T}LUT/  {_dir_summary(lut_dir, LUT_EXTS)}")

    # Transcript output files in Source/ (v3 new layout)
    for suffix in ["_transcript.json", "_transcript.srt",
                   "_1_Ingest_captions.srt", "_transcript.xlsx"]:
        fp = source / f"{name}{suffix}"
        if fp.exists():
            sz = fmt_size(fp.stat().st_size)
            log.info(f"{src_p}{T}{C.GREEN}{fp.name}{C.RESET}"
                     f"  {C.DIM}{sz}{C.RESET}")

    # Transcription/
    log.info(f"{src_p}{T}{C.BOLD}Transcription/{C.RESET}")
    tr_p = f"{src_p}{I}"

    if full_audio:
        fa = full_audio[0]
        sz = fmt_size(fa.stat().st_size)
        log.info(f"{tr_p}{T}{fa.name}"
                 f"  {C.DIM}{sz}{C.RESET}")

    if clip_dirs:
        log.info(f"{tr_p}{L}{C.BOLD}per_clip/{C.RESET}"
                 f"  {len(clip_dirs)} clips")
        pc_p = f"{tr_p}{S}"
        for j, cd in enumerate(clip_dirs):
            connector = L if j == len(clip_dirs) - 1 else T
            # Summarize clip dir contents
            clip_files = sorted([f.name for f in cd.iterdir()
                                 if f.is_file()
                                 and not f.name.startswith('.')])
            # Shorten names: show just suffixes
            short = []
            for cf in clip_files:
                if cf.endswith("_AUDIO.wav"):
                    short.append("AUDIO.wav")
                elif cf.endswith(".XML") or cf.endswith(".xml"):
                    short.append("XML")
                else:
                    short.append(cf)
            items_str = " + ".join(short) if short else "empty"
            log.info(f"{pc_p}{connector}{cd.name}/"
                     f"  {C.DIM}{items_str}{C.RESET}")
    elif not full_audio:
        log.info(f"{tr_p}{L}per_clip/  {C.DIM}—{C.RESET}")

    # Setup/
    logs_dir = setup_dir / "logs"
    log_count = len(list(logs_dir.glob("*.log"))) if logs_dir.is_dir() else 0
    log_info = f"{log_count} logs" if log_count else f"{C.DIM}—{C.RESET}"
    log.info(f"{src_p}├──Setup/logs/  {C.DIM}{log_info}{C.RESET}")

    assembly_dir = setup_dir / "Assembly"
    asm_count = len(list(assembly_dir.glob("*.json"))) if assembly_dir.is_dir() else 0
    asm_info = f"{asm_count} briefs" if asm_count else f"{C.DIM}—{C.RESET}"
    log.info(f"{src_p}├──Setup/Assembly/  {C.DIM}{asm_info}{C.RESET}")

    pre_edit_dir = setup_dir / "Pre-Edit"
    pe_count = len(list(pre_edit_dir.iterdir())) if pre_edit_dir.is_dir() else 0
    pe_info = f"{pe_count} items" if pe_count else f"{C.DIM}—{C.RESET}"
    log.info(f"{src_p}{L}Setup/Pre-Edit/  {C.DIM}{pe_info}{C.RESET}")

    # 99_Pipeline/
    log.info(f"  │")
    if dji_files:
        total_d = sum(f.stat().st_size for f in dji_files)
        log.info(f"  {T}{C.BOLD}99_Pipeline/DJI_Audio/{C.RESET}"
                 f"  {len(dji_files)} files "
                 f"{C.DIM}({fmt_size(total_d)}){C.RESET}")
        dji_p = f"  {I}"
        for k, d in enumerate(dji_files):
            connector = L if k == len(dji_files) - 1 else T
            sz = fmt_size(d.stat().st_size)
            log.info(f"{dji_p}{connector}{d.name}"
                     f"  {C.DIM}{sz}{C.RESET}")
    else:
        log.info(f"  {T}99_Pipeline/DJI_Audio/  {C.DIM}—{C.RESET}")

    # Other dirs
    log.info(f"  │")
    other_dirs = ["02_Exports", "03_Shorts", "04_Thumbnail", "YouTube"]
    existing_others = [d for d in other_dirs
                       if (project / d).is_dir()]
    for i, d in enumerate(existing_others):
        is_last = (i == len(existing_others) - 1)
        connector = L if is_last else T
        log.info(f"  {connector}{d}/")

    log.info(f"  {C.DIM}╰{'─' * W}╯{C.RESET}")


def print_dji_warning(project: Path, log: PipelineLogger):
    """Print prominent DJI sync warning if sync failed despite DJI files."""
    dji_dir = project / "99_Pipeline" / "DJI_Audio"
    audio_dir = project / "01_Media" / "Source" / "Audio"

    dji_files = [f for f in dji_dir.iterdir()
                 if f.is_file() and f.suffix.lower() == '.wav'
                 ] if dji_dir.is_dir() else []
    synced = [f for f in audio_dir.rglob("*")
              if f.is_file() and f.suffix.lower() == '.wav'
              ] if audio_dir.is_dir() else []

    if not dji_files or synced:
        return

    W = 58
    log.info("")
    log.info(f"  {C.YELLOW}{'━' * W}{C.RESET}")
    log.info(f"  {C.YELLOW}{C.BOLD}  ⚠  DJI audio sync failed"
             f"{C.RESET}")
    log.info(f"  {C.YELLOW}{'─' * W}{C.RESET}")
    log.info(f"  {C.YELLOW}  {len(dji_files)} DJI file(s) in "
             f"99_Pipeline/DJI_Audio/{C.RESET}")
    log.info(f"  {C.YELLOW}  Source/Audio/ is empty{C.RESET}")
    log.info(f"  {C.YELLOW}{C.RESET}")
    log.info(f"  {C.YELLOW}  Try with explicit timezone:{C.RESET}")
    log.info(f"  {C.YELLOW}    source ~/YTAI/environment/.venv_transcribe/bin/activate && "
             f"python3 ~/YTAI/scripts/run_pipeline.py "
             f"\"{project}\" --tz-offset 4 --force{C.RESET}")
    log.info(f"  {C.YELLOW}{'━' * W}{C.RESET}")


def print_prepare_summary(project: Path, elapsed: float,
                          log: PipelineLogger, tz_offset=None,
                          log_path: Path = None):
    """Print summary box after prepare phase completes."""
    W = 60
    B = "║"

    video_dir = project / "01_Media" / "Source" / "Video"
    audio_dir = project / "01_Media" / "Source" / "Audio"
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    dji_dir = project / "99_Pipeline" / "DJI_Audio"
    per_clip = tr_dir / "per_clip"

    videos = _list_videos_recursive(video_dir)
    dji_files = [f for f in dji_dir.iterdir()
                 if f.is_file() and f.suffix.lower() == '.wav'
                 ] if dji_dir.is_dir() else []
    synced = sorted(
        [f for f in audio_dir.rglob("*")
         if f.is_file() and f.suffix.lower() == '.wav'],
        key=natural_sort_key
    ) if audio_dir.is_dir() else []
    full_audio = list(tr_dir.glob("*_FULL_AUDIO.wav")) \
        if tr_dir.is_dir() else []
    clip_dirs = [d for d in per_clip.iterdir() if d.is_dir()] \
        if per_clip and per_clip.is_dir() else []

    FPS = 25
    BAR_W = 40

    # ── Gather durations for videos and synced audio ──
    vid_durs = {}   # {stem: (path, dur, size)}
    for vf in sorted(videos, key=natural_sort_key):
        dur = _get_duration(vf)
        vid_durs[vf.stem] = (vf, dur, vf.stat().st_size)

    aud_durs = {}   # {stem: {tx: (path, dur, size)}}
    tx_ids = set()
    for af in sorted(synced, key=natural_sort_key):
        # Parse: RYA-FX3-0099_TX02.wav → clip=RYA-FX3-0099, tx=TX02
        stem = af.stem
        parts = stem.rsplit("_", 1)
        if len(parts) == 2 and parts[1].startswith("TX"):
            clip_id, tx = parts
            tx_ids.add(tx)
            dur = _get_duration(af)
            aud_durs.setdefault(clip_id, {})[tx] = (af, dur, af.stat().st_size)

    total_video_size = sum(v[2] for v in vid_durs.values())
    total_video_dur = sum(v[1] for v in vid_durs.values())
    total_audio_size = sum(af.stat().st_size for af in synced)
    total_audio_dur = sum(
        info[1] for clip_txs in aud_durs.values()
        for info in clip_txs.values())

    log.info(f"\n  {C.BG_GREEN}{C.WHITE}{C.BOLD} Summary {C.RESET}")

    # ── Sync Visualization (before the box) ──
    if synced and tx_ids:
        for tx in sorted(tx_ids):
            log.info("")
            log.info(f"  {C.BOLD}{C.BLUE}Sync Visualization "
                     f"({tx}){C.RESET}")
            log.info(f"  {C.DIM}{'─' * 56}{C.RESET}")

            for clip_stem in sorted(vid_durs.keys()):
                vf, vdur, _ = vid_durs[clip_stem]
                adur = 0.0
                if clip_stem in aud_durs and tx in aud_durs[clip_stem]:
                    adur = aud_durs[clip_stem][tx][1]

                vtc = format_timecode(vdur, FPS)
                atc = format_timecode(adur, FPS)
                vframes = int(vdur * FPS)
                aframes = int(adur * FPS)
                fdelta = abs(vframes - aframes)

                log.info(f"  {C.BOLD}{clip_stem}{C.RESET} × {tx}:")

                v_bar = f"{C.CYAN}{'█' * BAR_W}{C.RESET}"
                log.info(f"    V1 |{v_bar}| {vtc}")

                if adur > 0 and vdur > 0:
                    ratio = min(adur / vdur, 1.0)
                    a_ch = max(1, int(ratio * BAR_W))
                    gap_ch = BAR_W - a_ch
                    if gap_ch > 0:
                        a_bar = (f"{C.GREEN}{'█' * a_ch}{C.RESET}"
                                 f"{C.RED}{'░' * gap_ch}{C.RESET}")
                        mark = f"{C.YELLOW}Δ={fdelta}f ⚠{C.RESET}"
                    else:
                        a_bar = f"{C.GREEN}{'█' * BAR_W}{C.RESET}"
                        mark = (f"{C.GREEN}Δ=0f ✓{C.RESET}"
                                if fdelta == 0
                                else f"{C.YELLOW}Δ={fdelta}f ⚠{C.RESET}")
                else:
                    a_bar = f"{C.RED}{'░' * BAR_W}{C.RESET}"
                    mark = f"{C.RED}MISSING ✗{C.RESET}"

                log.info(f"    A2 |{a_bar}| {atc}  {mark}")

    # ── Box: Completed + Media Statistics ──
    log.info(f"\n  {C.DIM}╔{'═' * W}╗{C.RESET}")

    # Completed
    log.info(_trow(f"  {C.BOLD}Completed{C.RESET}", W, B))
    log.info(_trow(f"  {C.DIM}{'─' * 56}{C.RESET}", W, B))

    log.info(_trow(f"  {C.GREEN}✓{C.RESET}  Folder structure initialized",
                   W, B))

    if videos:
        log.info(_trow(f"  {C.GREEN}✓{C.RESET}  {len(videos)} video clips "
                       f"{C.DIM}({fmt_size(total_video_size)}){C.RESET}",
                       W, B))

    if full_audio:
        fa = full_audio[0]
        log.info(_trow(f"  {C.GREEN}✓{C.RESET}  FULL_AUDIO extracted "
                       f"{C.DIM}({fmt_size(fa.stat().st_size)}){C.RESET}",
                       W, B))

    if clip_dirs:
        log.info(_trow(f"  {C.GREEN}✓{C.RESET}  {len(clip_dirs)} per-clip "
                       f"audio extracted", W, B))

    if synced:
        log.info(_trow(f"  {C.GREEN}✓{C.RESET}  {len(synced)} DJI audio "
                       f"synced", W, B))

    log.info(_trow(f"  Time: {C.BOLD}{fmt_duration(elapsed)}{C.RESET}",
                   W, B))

    # ── Media Statistics ──
    if videos or synced:
        log.info(f"  {C.DIM}╠{'═' * W}╣{C.RESET}")
        log.info(_trow(f"  {C.BOLD}Media Statistics{C.RESET}", W, B))
        log.info(_trow(f"  {C.DIM}{'─' * 56}{C.RESET}", W, B))

        for clip_stem in sorted(vid_durs.keys()):
            vf, dur, sz = vid_durs[clip_stem]
            log.info(_trow(
                f"  {C.CYAN}V{C.RESET}  {vf.name}  "
                f"{C.DIM}{fmt_size(sz)}{C.RESET}  "
                f"{format_timecode(dur, FPS)}", W, B))

        for af in sorted(synced, key=natural_sort_key):
            sz = af.stat().st_size
            dur = _get_duration(af)
            log.info(_trow(
                f"  {C.GREEN}A{C.RESET}  {af.name}  "
                f"{C.DIM}{fmt_size(sz)}{C.RESET}  "
                f"{format_timecode(dur, FPS)}", W, B))

        log.info(_trow(f"  {C.DIM}{'─' * 56}{C.RESET}", W, B))
        log.info(_trow(
            f"  {C.BOLD}Video{C.RESET}: {len(videos)} clips  "
            f"{fmt_size(total_video_size)}  "
            f"{format_timecode(total_video_dur, FPS)}", W, B))
        if synced:
            log.info(_trow(
                f"  {C.BOLD}Audio{C.RESET}: {len(synced)} synced  "
                f"{fmt_size(total_audio_size)}  "
                f"{format_timecode(total_audio_dur, FPS)}", W, B))

    # Needs attention
    needs_attention = []
    if dji_files and not synced:
        needs_attention.append(
            ("DJI sync failed",
             "try: --tz-offset N --force (e.g. --tz-offset 4)"))

    if needs_attention:
        log.info(f"  {C.DIM}╠{'═' * W}╣{C.RESET}")
        log.info(_trow(f"  {C.BOLD}{C.YELLOW}Needs Attention{C.RESET}",
                       W, B))
        log.info(_trow(f"  {C.DIM}{'─' * 56}{C.RESET}", W, B))
        for title, hint in needs_attention:
            log.info(_trow(f"  {C.YELLOW}⚠{C.RESET}  {title}", W, B))
            log.info(_trow(f"     {C.DIM}{hint}{C.RESET}", W, B))

    # Log path inside box
    if log_path:
        log.info(f"  {C.DIM}╠{'═' * W}╣{C.RESET}")
        log.info(_trow(f"  Log: {C.DIM}{log_path.name}{C.RESET}", W, B))

    # Close box
    log.info(f"  {C.DIM}╚{'═' * W}╝{C.RESET}")

    # ── Next Steps (outside box — commands are long) ──
    _venv = "source ~/YTAI/environment/.venv_transcribe/bin/activate"
    _pipe = "python3 ~/YTAI/scripts/run_pipeline.py"
    _proj = str(project)

    log.info("")
    log.info(f"  {C.BOLD}Next Steps{C.RESET}")
    log.info(f"  {C.DIM}{'─' * 56}{C.RESET}")
    log.info(f"  {C.BOLD}1.{C.RESET} Run transcription:")
    log.info(f"  {C.CYAN}{_venv} && "
             f"{_pipe} \"{_proj}\" "
             f"--only transcribe -n 2{C.RESET}")
    log.info("")
    log.info(f"  {C.BOLD}2.{C.RESET} Or run everything:")
    log.info(f"  {C.CYAN}{_venv} && "
             f"{_pipe} \"{_proj}\" "
             f"--all -n 2{C.RESET}")


# ============================================================================
# Run a pipeline script as subprocess
# ============================================================================

def run_script(script_rel: str, project: Path,
               extra_args: list = None, dry_run: bool = False,
               log: PipelineLogger = None) -> bool:
    """Run a pipeline script via subprocess with live output."""
    script_path = SCRIPTS_DIR / script_rel

    if not script_path.exists():
        msg = f"      ✗ Script not found: {script_path}"
        if log:
            log.error(msg)
        else:
            print(msg)
        return False

    cmd = [sys.executable, str(script_path), "--project", str(project)]
    if extra_args:
        cmd.extend(extra_args)

    if log:
        log.debug(f"Command: {' '.join(cmd)}")

    if dry_run:
        msg = f"      → Would run: {' '.join(cmd)}"
        if log:
            log.info(msg)
        else:
            print(msg)
        return True

    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        if log:
            log.debug(f"Exit code: {result.returncode}")
        return result.returncode == 0
    except KeyboardInterrupt:
        if log:
            log.warn("\n      ⚠ Interrupted by user")
        return False
    except Exception as e:
        if log:
            log.error(f"      ✗ Error: {e}")
        return False


# ============================================================================
# Ask continue
# ============================================================================

def ask_continue(phase_name: str) -> bool:
    """Prompt user to continue to next phase."""
    try:
        response = input(
            f"\n  {C.GREEN}{phase_name} complete.{C.RESET} "
            f"Continue? [{C.BOLD}Y{C.RESET}/n]: "
        ).strip().lower()
        return response != "n"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ============================================================================
# List mode
# ============================================================================

def list_stages(project: Path) -> None:
    """Print status of each phase/stage for this project."""
    project_name = project.name
    print_header(project_name)

    # All check functions (including init) for list display
    all_checks = dict(CHECK_FNS)
    all_checks["init"] = check_init

    for pidx, phase in enumerate(PHASES):
        # Check if all sub-stages in this phase are done
        all_done = True
        for stage in phase["stages"]:
            sid = stage["id"]
            check_fn = all_checks.get(sid)
            if stage.get("optional") and sid == "sync_dji":
                if not has_dji_files(project):
                    continue
            if check_fn and not check_fn(project):
                all_done = False

        if all_done:
            phase_status = f"{C.GREEN}✓ done{C.RESET}"
        else:
            phase_status = f"○ pending"
        print(f"  [{pidx + 1}/{len(PHASES)}] "
              f"{C.BOLD}{phase['name']}{C.RESET:<30} {phase_status}")

        for stage in phase["stages"]:
            sid = stage["id"]
            name = stage["name"]
            check_fn = all_checks.get(sid)

            if check_fn and check_fn(project):
                status = f"{C.GREEN}✓{C.RESET}"
            elif sid == "sync_dji" and not has_dji_files(project):
                status = f"{C.DIM}⏭ no DJI{C.RESET}"
            else:
                status = "○"

            print(f"        {name:<26} {status}")

    # File stats
    print()
    video_dir = project / "01_Media" / "Source" / "Video"
    if video_dir.is_dir():
        vids = _list_videos_recursive(video_dir)
        if vids:
            total = sum(f.stat().st_size for f in vids)
            print(f"  Video:       {len(vids)} files ({fmt_size(total)})")

    dji_dir = project / "99_Pipeline" / "DJI_Audio"
    if dji_dir.is_dir():
        djis = [f for f in dji_dir.iterdir()
                if f.suffix.lower() == '.wav']
        if djis:
            total = sum(f.stat().st_size for f in djis)
            print(f"  DJI audio:   {len(djis)} files ({fmt_size(total)})")

    tr_dir = project / "01_Media" / "Source" / "Transcription"
    if tr_dir.is_dir():
        trs = list(tr_dir.glob("*_transcript.json"))
        if trs:
            print(f"  Transcript:  {trs[0].name}")

    logs_dir = project / "01_Media" / "Source" / "Setup" / "logs"
    if logs_dir.is_dir():
        run_logs = sorted(logs_dir.glob("*_run_pipeline_*.log"))
        if run_logs:
            print(f"  Last log:    {run_logs[-1].name}")

    print()


# ============================================================================
# Main pipeline
# ============================================================================

def run_pipeline(args) -> int:
    """Execute the pipeline phases."""
    project = Path(args.project).resolve()
    project_name = project.name

    # --list mode
    if args.list:
        list_stages(project)
        return 0

    print_header(project_name)

    # Set up logging
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    logs_dir = project / "01_Media" / "Source" / "Setup" / "logs"

    if not args.dry_run:
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{project_name}_run_pipeline_{ts}.log"
        log = PipelineLogger(log_path, project=project)
    else:
        log_path = None
        log = PipelineLogger()

    log.info(f"Project:  {project_name}")
    log.info(f"Path:     {project}")
    log.debug(f"Args:     {vars(args)}")
    log.debug(f"Python:   {sys.executable}")
    log.debug(f"Scripts:  {SCRIPTS_DIR}")
    log.debug(f"Template: {TEMPLATES_DIR}")

    # Determine which phases to run
    phases_to_run = _resolve_phases(args)
    if phases_to_run is None:
        log.error(f"Unknown stage/phase: {args.only}")
        log.close()
        return 1

    total_phases = len(phases_to_run)
    phase_names = ', '.join(p['name'] for p in phases_to_run)
    log.info(f"Phases:   {phase_names}")
    if log_path:
        log.info(f"Log:      {log_path}")
    log.info("")

    start_time = time.time()
    completed_phases = 0

    for pidx, phase in enumerate(phases_to_run):
        phase_name = phase["name"]
        total_stages = len(phase["stages"])

        # Phase header — colored background bar
        log.info(f"\n  {C.BG_CYAN}{C.WHITE}{C.BOLD} Phase "
                 f"{pidx + 1}/{total_phases} {C.RESET} "
                 f"{C.BOLD}{phase_name}{C.RESET}")
        log.debug(f"Phase {phase['id']}: starting")
        phase_start = time.time()

        # Run each sub-stage within this phase
        phase_ok = True
        for sidx, stage in enumerate(phase["stages"]):
            sid = stage["id"]
            sname = stage["name"]
            check_fn = CHECK_FNS.get(sid)
            stage_tag = f"[{sidx + 1}/{total_stages}]"

            # Smart skip: already done?
            if not args.force and check_fn and check_fn(project):
                log.info(f"    {C.GREEN}✓{C.RESET} {stage_tag} "
                         f"{sname:<30} "
                         f"{C.DIM}already done{C.RESET}")
                log.debug(f"  Sub-stage {sid}: check passed, skip")
                continue

            # Optional: skip sync_dji if no DJI source files
            if stage.get("optional") and sid == "sync_dji":
                if not has_dji_files(project):
                    log.info(f"    {C.DIM}⏭{C.RESET} {stage_tag} "
                             f"{sname:<30} "
                             f"{C.DIM}no DJI files{C.RESET}")
                    continue

            # Pre-flight: video files
            if sid in ("extract_audio", "sync_dji"):
                if not has_video_files(project):
                    if args.dry_run:
                        log.info(f"    {C.YELLOW}⚠{C.RESET} {stage_tag} "
                                 f"{sname:<30} "
                                 f"{C.YELLOW}no video files yet{C.RESET}")
                        continue
                    log.error(f"    {C.RED}✗{C.RESET} {stage_tag} "
                              f"{sname:<30} "
                              f"{C.RED}no video files{C.RESET}")
                    log.error("")
                    log.error("      Video files were not found. "
                              "Check project folder.")
                    log.error(f"      Expected: {project}/"
                              f"01_Media/Source/Video/*.mp4")
                    phase_ok = False
                    break

            # Pre-stage validation
            if sid != "init" and not args.dry_run:
                log.info(f"      {sname}:")
                if not validate_prerequisites(sid, project, log):
                    log.error(f"    {C.RED}✗{C.RESET} Pre-flight failed")
                    phase_ok = False
                    break

            # Run sub-stage
            log.info(f"    {C.CYAN}▶{C.RESET} {stage_tag} "
                     f"{sname:<30} "
                     f"{C.CYAN}⏳ running...{C.RESET}")
            log.debug(f"  Sub-stage {sid}: executing")
            stage_start = time.time()

            success = False
            if sid == "init":
                success = run_init(project, args.type, log,
                                   dry_run=args.dry_run)
            else:
                extra = build_extra_args(sid, args)
                success = run_script(
                    stage["script"], project,
                    extra_args=extra,
                    dry_run=args.dry_run,
                    log=log,
                )

            stage_elapsed = time.time() - stage_start

            if success:
                log.info(f"    {C.GREEN}✓{C.RESET} {stage_tag} "
                         f"{sname:<30} "
                         f"{C.DIM}{fmt_duration(stage_elapsed)}{C.RESET}")
                log.debug(f"  Sub-stage {sid}: OK in "
                          f"{stage_elapsed:.1f}s")

                # Post-stage verification
                if not args.dry_run and sid != "init":
                    verify_stage_output(sid, project, log)
            else:
                log.error(f"    {C.RED}✗{C.RESET} {stage_tag} "
                          f"{sname:<30} "
                          f"{C.RED}failed{C.RESET} "
                          f"{C.DIM}({fmt_duration(stage_elapsed)})"
                          f"{C.RESET}")
                phase_ok = False
                break

        phase_elapsed = time.time() - phase_start

        if phase_ok:
            log.info(f"\n  {C.BG_GREEN}{C.WHITE}{C.BOLD} Phase "
                     f"{pidx + 1}/{total_phases} {C.RESET} "
                     f"{C.GREEN}{phase_name}{C.RESET}  "
                     f"{C.DIM}{fmt_duration(phase_elapsed)}{C.RESET}")
            completed_phases += 1

            # Show project tree + warnings after prepare phase
            if phase["id"] == "prepare" and not args.dry_run:
                log.info("")
                print_project_tree(project, log)
                print_dji_warning(project, log)

                # Generate lite ingest.json (video + DJI audio, no transcripts)
                try:
                    _ingest_mod = (SCRIPTS_DIR / "02_transcribe"
                                   / "020101_transcribe" / "ingest_json.py")
                    import importlib.util
                    _spec = importlib.util.spec_from_file_location(
                        "ingest_json", _ingest_mod)
                    _mod = importlib.util.module_from_spec(_spec)
                    _spec.loader.exec_module(_mod)
                    ingest_path = _mod.generate_lite(project)
                    log.info(f"      {C.GREEN}✓{C.RESET} Lite ingest.json → "
                             f"{ingest_path.relative_to(project)}")
                except Exception as e:
                    log.warn(f"      {C.YELLOW}⚠{C.RESET} "
                             f"Lite ingest.json skipped: {e}")
        else:
            log.error(f"\n  {C.BG_YELLOW}{C.WHITE}{C.BOLD} Phase "
                      f"{pidx + 1}/{total_phases} {C.RESET} "
                      f"{C.RED}{phase_name} — failed{C.RESET} "
                      f"{C.DIM}({fmt_duration(phase_elapsed)}){C.RESET}")
            log.close()
            return 1

        # Pause between phases
        if (not args.no_pause and not args.dry_run
                and pidx < total_phases - 1):
            if not ask_continue(phase_name):
                log.info("\n  Stopped by user.")
                log.close()
                return 0

    elapsed = time.time() - start_time

    if not args.dry_run:
        ran_ids = [p["id"] for p in phases_to_run]
        if ran_ids == ["prepare"]:
            print_prepare_summary(project, elapsed, log,
                                  tz_offset=args.tz_offset,
                                  log_path=log_path)
        else:
            print_footer(completed_phases, total_phases, elapsed,
                         project, log_path)

    log.close()
    return 0


def _resolve_phases(args) -> list:
    """
    Determine which phases/stages to run based on --only, --from, --to.

    Returns list of phase dicts (possibly with filtered stages),
    or None if invalid choice.
    """
    if args.only:
        choice = args.only

        # Phase-level: "prepare" or "transcribe"
        for p in PHASES:
            if p["id"] == choice:
                return [p]

        # Sub-stage level: "init", "extract_audio", "sync_dji", "transcribe"
        for p in PHASES:
            for s in p["stages"]:
                if s["id"] == choice:
                    return [{
                        "id": p["id"],
                        "name": s["name"],
                        "stages": [s],
                    }]
        return None

    # --from / --to: resolve at phase level
    start_idx = 0
    # Default: prepare only, unless --all or --to is specified
    end_idx = len(PHASES) - 1 if args.all else 0

    if args.start_from:
        for i, p in enumerate(PHASES):
            if p["id"] == args.start_from:
                start_idx = i
                break
            for s in p["stages"]:
                if s["id"] == args.start_from:
                    start_idx = i
                    break

    if args.stop_after:
        for i, p in enumerate(PHASES):
            if p["id"] == args.stop_after:
                end_idx = i
                break
            for s in p["stages"]:
                if s["id"] == args.stop_after:
                    end_idx = i
                    break

    return PHASES[start_idx: end_idx + 1]


def build_extra_args(stage_id: str, args) -> list:
    """Build extra CLI arguments for a sub-stage script."""
    extra = []

    if stage_id == "extract_audio":
        if args.force:
            extra.append("--overwrite")

    elif stage_id == "sync_dji":
        if args.tz_offset is not None:
            extra.extend(["--tz-offset", str(args.tz_offset)])
        if args.force:
            extra.append("--overwrite")

    elif stage_id == "transcribe":
        if args.speakers:
            extra.extend(["-n", str(args.speakers)])
        if args.language:
            extra.extend(["--language", args.language])
        if args.model:
            extra.extend(["-m", args.model])
        if getattr(args, "skip_done", False):
            extra.append("--skip-done")
        extra.append("-y")  # skip interactive prompts

    return extra


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI Pipeline — single entry point",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Prepare files (default — init + extract audio + DJI sync)
  python run_pipeline.py "/Volumes/RYA Blue/Project"

  # Full pipeline (prepare + transcribe)
  python run_pipeline.py "$PROJECT" --all --speakers 2

  # Only transcription (files already prepared)
  python run_pipeline.py "$PROJECT" --only transcribe --speakers 2

  # Check status / dry run
  python run_pipeline.py "$PROJECT" --list
  python run_pipeline.py "$PROJECT" --dry-run

Phases:
  [1] Prepare files  (default)
        Init folders + auto-organize media files
        Extract audio from clips + FULL_AUDIO
        DJI sync (timezone auto-detected)

  [2] Transcribe  (requires --all or --only transcribe)
        Whisper + Pyannote diarization

Logs:
  01_Media/Source/Setup/logs/{project}_run_pipeline_{timestamp}.log

Speaker ID is done separately via Claude Desktop project.
        """,
    )

    # Positional
    parser.add_argument("project", help="Path to project folder")

    # Phase/stage selection
    parser.add_argument("--all", action="store_true",
                        help="Run all phases (prepare + transcribe)")
    parser.add_argument("--only", choices=ONLY_CHOICES,
                        help="Run only this phase or sub-stage")
    parser.add_argument("--from", dest="start_from",
                        choices=ONLY_CHOICES,
                        help="Start from this phase (default: prepare)")
    parser.add_argument("--to", dest="stop_after",
                        choices=ONLY_CHOICES,
                        help="Stop after this phase")

    # Pipeline parameters
    parser.add_argument("-n", "--speakers", type=int,
                        help="Number of speakers for Pyannote diarization")
    parser.add_argument("--language",
                        help="Language code for Whisper (default: auto)")
    parser.add_argument("-m", "--model", default=None,
                        help="Whisper model (default: large-v3)")
    parser.add_argument("--tz-offset", type=float,
                        help="Timezone for DJI sync (auto-detected if omitted)")
    parser.add_argument("--type", choices=["footage", "production"],
                        default="production",
                        help="Folder type for init (default: production)")

    # Behavior
    parser.add_argument("--no-pause", action="store_true",
                        help="Run without pausing between phases")
    parser.add_argument("--force", action="store_true",
                        help="Re-run stages even if output exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing")
    parser.add_argument("--skip-done", action="store_true",
                        help="Skip transcription if transcript already exists")
    parser.add_argument("--list", action="store_true",
                        help="Show status of each phase and exit")

    args = parser.parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
