"""
0100_organize.py — Organize media files for a YTAI production project.

Usage:
    python 0100_organize.py --project PATH [--dry-run]

Purpose:
    Detects whether a project is "nested" (multi-scene, with TX recorder
    folders at root) or flat, then:
      1. Creates the v3.0 folder skeleton from YTAI_Folder_Templates/Type2_Production
      2. Detects scene folders (bare-name, e.g. volleyball/, apartment/)
      3. Stubs for file moves implemented in Plan 02

Output:
    v3.0 folder skeleton merged into the project directory.
    Logs written to stdout (--dry-run prints planned operations only).
"""

import argparse
import os
import re
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants (replicate from run_pipeline.py + extend for organize stage)
# ---------------------------------------------------------------------------

VIDEO_EXTS = {'.mp4', '.mov', '.m4v', '.mts', '.avi', '.mkv'}
AUDIO_EXTS = {'.wav'}
SIDECAR_EXTS = {'.xml'}

# TX folder detection: TX01/, TX02/, TX02_2/, TX03/, etc.
TX_FOLDER_RE = re.compile(r'^TX\d+', re.IGNORECASE)

# DJI raw audio filename: TX02_MIC037_20260306_102304_orig.wav
DJI_RAW_RE = re.compile(r'^TX\d{2}_MIC\d{3}_\d{8}_\d{6}', re.IGNORECASE)

# v3.0 managed directories — skip during file discovery / scene detection
V3_MANAGED_DIRS = {
    '01_Media', '02_Exports', '03_Shorts', '04_Thumbnail',
    'YouTube', '99_Pipeline',
}

# System/hidden directories to always skip
SYSTEM_DIRS = {
    '.Spotlight-V100', '.fseventsd', '.Trashes',
    '.TemporaryItems', '__MACOSX', '.DocumentRevisions-V100',
}

# Archive/backup directories to skip (case-insensitive prefix match)
ARCHIVE_PREFIXES = ('archive', 'old_', 'backup', '_old', '_backup')


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------

def is_nested_project(project: Path) -> bool:
    """Return True if the project has TX01/, TX02/, etc. folders at root.

    TX folder presence signals a nested multi-scene project with DJI recorder
    audio captured in separate TX subfolders.

    Args:
        project: Absolute path to the project root directory.

    Returns:
        True if any immediate child directory matches TX_FOLDER_RE.
    """
    for item in project.iterdir():
        if item.is_dir() and not item.name.startswith('.') and TX_FOLDER_RE.match(item.name):
            return True
    return False


def detect_scenes(project: Path) -> list:
    """Return sorted list of scene folder names found at project root.

    A folder is a "scene" if it:
      1. Is a directory
      2. Is NOT a v3.0 managed dir (01_Media, 99_Pipeline, etc.)
      3. Is NOT a system/hidden directory
      4. Does NOT start with an archive prefix
      5. Is NOT a TX folder (TX01/, TX02/, TX02_2/)
      6. Contains at least one video file (recursively)

    Args:
        project: Absolute path to the project root directory.

    Returns:
        Sorted list of scene folder names (e.g. ['al_qudra_lake', 'apartment', 'volleyball']).
    """
    scenes = []
    for d in sorted(project.iterdir()):
        if not d.is_dir():
            continue
        if d.name in V3_MANAGED_DIRS:
            continue
        if d.name in SYSTEM_DIRS or d.name.startswith('.'):
            continue
        if d.name.lower().startswith(ARCHIVE_PREFIXES):
            continue
        if TX_FOLDER_RE.match(d.name):
            continue
        # Must contain at least one video file
        if any(f.suffix.lower() in VIDEO_EXTS for f in d.rglob('*') if f.is_file()):
            scenes.append(d.name)
    return scenes


# ---------------------------------------------------------------------------
# Folder skeleton creation
# ---------------------------------------------------------------------------

def create_v3_skeleton(project: Path, template_dir: Path, dry_run: bool = False) -> int:
    """Deep-merge template directory structure into the project.

    Replicates _deep_merge_template() from run_pipeline.py:
      - Walks the template_dir recursively
      - Creates missing directories in project (preserving nesting)
      - Copies non-.gitkeep files that don't already exist
      - Always ensures 99_Pipeline/DJI_Audio/ exists

    Args:
        project: Absolute path to the project root directory.
        template_dir: Absolute path to Type2_Production template directory.
        dry_run: If True, print planned operations without creating anything.

    Returns:
        Count of directories created (0 in dry_run mode).
    """
    created = 0

    if not template_dir.exists():
        print(f"[WARNING] Template directory not found: {template_dir}")
    else:
        for root, dirs, files in os.walk(template_dir):
            rel = Path(root).relative_to(template_dir)
            dst_dir = project / rel
            if not dst_dir.exists():
                if dry_run:
                    print(f"  [dry-run] Would create dir: {rel}/")
                else:
                    dst_dir.mkdir(parents=True, exist_ok=True)
                created += 1
            for fname in files:
                if fname == ".gitkeep":
                    continue
                dst_file = dst_dir / fname
                if not dst_file.exists():
                    if dry_run:
                        print(f"  [dry-run] Would copy file: {rel / fname}")
                    else:
                        shutil.copy2(str(Path(root) / fname), str(dst_file))

    # Always ensure 99_Pipeline/DJI_Audio/ exists (even if not in template)
    dji_audio = project / "99_Pipeline" / "DJI_Audio"
    if not dji_audio.exists():
        if dry_run:
            print(f"  [dry-run] Would create dir: 99_Pipeline/DJI_Audio/")
        else:
            dji_audio.mkdir(parents=True, exist_ok=True)
        created += 1

    return created


# ---------------------------------------------------------------------------
# File move functions
# ---------------------------------------------------------------------------

def move_scene_clips(scenes: list, project: Path, video_dir: Path, dry_run: bool = False) -> bool:
    """Move video clips from scene folders into Source/Video/{scene}/ preserving subfolders.

    Uses clip.relative_to(scene_dir) so that GoPro subfolders (100GOPRO/, etc.)
    are preserved inside the destination scene directory.

    Args:
        scenes: List of scene folder names found at project root.
        project: Absolute path to the project root directory.
        video_dir: Destination root for video clips (01_Media/Source/Video).
        dry_run: If True, print planned operations without moving files.

    Returns:
        True if no errors.
    """
    ok = True
    for scene in scenes:
        scene_dir = project / scene
        for clip in scene_dir.rglob("*"):
            if not clip.is_file():
                continue
            if clip.suffix.lower() not in VIDEO_EXTS:
                continue
            rel = clip.relative_to(scene_dir)
            dest = video_dir / scene / rel
            if dry_run:
                print(f"  [dry-run] Would move video: {clip} -> {dest}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                print(f"[organize] Already exists, skip: {dest.name}")
                continue
            shutil.move(str(clip), str(dest))
    return ok


def move_dji_wavs(project: Path, dji_dir: Path, dry_run: bool = False) -> bool:
    """Move DJI WAV files from TX01/, TX02/, TX02_2/ etc. into DJI_Audio/ flat.

    Only files matching DJI_RAW_RE are moved (TX02_MIC037_... pattern).

    Args:
        project: Absolute path to the project root directory.
        dji_dir: Destination directory (99_Pipeline/DJI_Audio).
        dry_run: If True, print planned operations without moving files.

    Returns:
        True if no errors.
    """
    ok = True
    for d in project.iterdir():
        if not d.is_dir():
            continue
        if not TX_FOLDER_RE.match(d.name):
            continue
        for wav in d.rglob("*"):
            if not wav.is_file():
                continue
            if wav.suffix.lower() not in AUDIO_EXTS:
                continue
            if not DJI_RAW_RE.match(wav.name):
                continue
            dest = dji_dir / wav.name
            if dry_run:
                print(f"  [dry-run] Would move WAV: {wav.name} -> {dest}")
                continue
            if dest.exists():
                print(f"[organize] Already exists, skip: {wav.name}")
                continue
            shutil.move(str(wav), str(dest))
    # Remove empty TX directories after moves
    if not dry_run:
        for d in project.iterdir():
            if not d.is_dir():
                continue
            if not TX_FOLDER_RE.match(d.name):
                continue
            try:
                d.rmdir()  # Only removes if empty (safe)
            except OSError:
                pass  # Not empty — leave it
    return ok


def build_clip_scene_map(scenes: list, project: Path) -> dict:
    """Build a mapping from clip stem to scene name, from video files found in each scene dir.

    Args:
        scenes: List of scene folder names at project root.
        project: Absolute path to the project root.

    Returns:
        Dict mapping clip stem (e.g. "C5089") to scene name (e.g. "apartment").
    """
    clip_scene_map = {}
    for scene in scenes:
        scene_dir = project / scene
        for f in scene_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                clip_scene_map[f.stem] = scene
    return clip_scene_map


def xml_to_clip_id(xml_path: Path, video_stems: set) -> str | None:
    """Extract the clip ID from a Sony XML sidecar filename by matching video stems.

    Sony XML naming: C5089M01.XML — try progressively shorter prefixes of the
    stem until a match is found in video_stems.

    Args:
        xml_path: Path to the XML sidecar file.
        video_stems: Set of known video clip stems (e.g. {"C5089", "C5210"}).

    Returns:
        Matching clip stem (e.g. "C5089") or None if no match found.
    """
    stem = xml_path.stem  # e.g. "C5089M01"
    for length in range(len(stem), 0, -1):
        prefix = stem[:length]
        if prefix in video_stems:
            return prefix
    return None


def move_xml_sidecars(project: Path, scenes: list, tr_dir: Path, dry_run: bool = False) -> bool:
    """Move Sony XML sidecar files to Transcription/per_clip/{scene}/{clip}/.

    The scene is determined by the scene directory the XML file is found in.
    If no video stem match is found, falls back to flat per_clip/{clip}/ path.

    Args:
        project: Absolute path to the project root directory.
        scenes: List of scene folder names at project root.
        tr_dir: Destination transcription root (01_Media/Source/Transcription).
        dry_run: If True, print planned operations without moving files.

    Returns:
        True if no errors.
    """
    # Collect all video stems for clip ID matching.
    # Scan both the original scene dirs (before move) and the destination Video dir
    # (after move_scene_clips has already run) to handle both call orderings.
    video_stems: set = set()
    for scene in scenes:
        scene_dir = project / scene
        for f in scene_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                video_stems.add(f.stem)
    # Also scan the destination video dir (clips may already be moved)
    video_dir = project / "01_Media" / "Source" / "Video"
    if video_dir.exists():
        for f in video_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
                video_stems.add(f.stem)

    ok = True
    for scene in scenes:
        scene_dir = project / scene
        for xml in scene_dir.rglob("*"):
            if not xml.is_file():
                continue
            if xml.suffix.lower() not in SIDECAR_EXTS:
                continue
            clip_id = xml_to_clip_id(xml, video_stems)
            if clip_id:
                # Use the scene where the XML was found (not where the clip lives)
                dest = tr_dir / "per_clip" / scene / clip_id / xml.name
            else:
                # Fall back to flat path for unmatched XMLs
                dest = tr_dir / "per_clip" / xml.stem / xml.name
            if dry_run:
                print(f"  [dry-run] Would move XML: {xml.name} -> {dest}")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                print(f"[organize] Already exists, skip: {xml.name}")
                continue
            shutil.move(str(xml), str(dest))
    return ok


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def organize(project: Path, dry_run: bool = False) -> bool:
    """Orchestrate the organize stage for a project.

    Steps:
      1. Detect if nested (TX folders present)
      2. Detect scene folders
      3. Create v3.0 folder skeleton from template
      4. TODO: Move video clips per scene into Source/Video/{scene}/  (Plan 02)
      5. TODO: Move DJI WAVs flat into 99_Pipeline/DJI_Audio/        (Plan 02)
      6. TODO: Move XML sidecars to per_clip/{scene}/{clip}/          (Plan 02)

    Args:
        project: Absolute path to the project root directory.
        dry_run: If True, print planned operations without moving files.

    Returns:
        True on success.
    """
    project = Path(project)

    nested = is_nested_project(project)
    scenes = detect_scenes(project) if nested else []

    if dry_run or True:  # Always print summary
        print(f"[organize] Project: {project.name}")
        print(f"[organize] Mode: {'nested' if nested else 'flat'}")
        if scenes:
            print(f"[organize] Scenes detected: {scenes}")

    # Resolve template path relative to this script's location:
    # scripts/01_prepare/0100_organize/ -> project_root -> YTAI_Folder_Templates/
    template_dir = (
        Path(__file__).resolve().parent.parent.parent.parent
        / "YTAI_Folder_Templates"
        / "Type2_Production"
    )

    create_v3_skeleton(project, template_dir, dry_run=dry_run)

    if nested:
        video_dir = project / "01_Media" / "Source" / "Video"
        dji_dir = project / "99_Pipeline" / "DJI_Audio"
        tr_dir = project / "01_Media" / "Source" / "Transcription"

        move_scene_clips(scenes, project, video_dir, dry_run=dry_run)
        move_dji_wavs(project, dji_dir, dry_run=dry_run)
        move_xml_sidecars(project, scenes, tr_dir, dry_run=dry_run)

        # Remove empty scene directories at project root after moves
        if not dry_run:
            for scene in scenes:
                scene_dir = project / scene
                try:
                    scene_dir.rmdir()  # Only removes if truly empty
                except OSError:
                    pass  # Not empty — leave it

    # Summary output
    print(f"[organize] Done — {len(scenes)} scene(s) processed.")

    return True


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Organize media files for a YTAI production project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--project",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to the project root directory.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print planned operations without modifying files.",
    )
    args = parser.parse_args()

    success = organize(args.project, dry_run=args.dry_run)
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
