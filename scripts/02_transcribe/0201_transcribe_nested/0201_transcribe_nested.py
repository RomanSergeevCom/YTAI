"""Scene orchestrator for nested multi-scene transcription projects.

This module provides core functions for detecting scene subfolders, invoking
transcribe_project.py per-scene via subprocess, collecting the output transcript
to the canonical Transcription/ path, and checking whether a scene needs
transcription.

Usage (called by Plan 02 CLI orchestrator):
  from 0201_transcribe_nested import detect_scenes, transcribe_scene, collect_scene_transcript

Per-scene invocation pattern (per 03-RESEARCH.md):
  - transcribe_project.py is called with --project pointing at the scene subfolder
  - This runs in flat mode: writes to {scene_dir}/{scene}_transcription/{scene}_transcript.json
  - collect_scene_transcript copies the output to the canonical v3 path:
    {project}/01_Media/Source/Transcription/{scene}_transcript.json
"""
import argparse
import json
import shutil
import subprocess
from pathlib import Path


def detect_scenes(project: Path) -> list:
    """Return sorted list of scene subdirectory Paths under Source/Video/.

    Excludes hidden directories (starting with "."). Does not require numeric
    prefix — matches any non-hidden subdirectory (consistent with Phase 1 + 2).

    Args:
        project: Project root path (contains 01_Media/Source/Video/).

    Returns:
        Sorted list of Path objects for each scene subdirectory.
    """
    video_dir = project / "01_Media" / "Source" / "Video"
    if not video_dir.exists():
        return []
    return sorted(
        [d for d in video_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda p: p.name,
    )


def should_transcribe_scene(project: Path, scene_name: str) -> bool:
    """Return True if the scene needs transcription (transcript not yet present).

    Checks for the canonical output file at:
      {project}/01_Media/Source/Transcription/{scene_name}_transcript.json

    Args:
        project: Project root path.
        scene_name: Name of the scene subfolder (e.g. "apartment").

    Returns:
        True if transcript file does NOT exist (scene needs transcription).
        False if transcript already exists (skip — idempotent re-run).
    """
    transcript_path = (
        project / "01_Media" / "Source" / "Transcription" / f"{scene_name}_transcript.json"
    )
    return not transcript_path.exists()


def transcribe_scene(scene_dir: Path, num_speakers: int, dry_run: bool = False) -> None:
    """Invoke transcribe_project.py for a single scene via subprocess.

    The script is called with the scene subfolder as --project (flat mode):
      {venv_python} transcribe_project.py --project {scene_dir} -n {num_speakers} -y [--dry-run]

    When transcribe_project.py runs in flat mode (no 01_Media/Source/Video/ inside
    the target), it writes the transcript to:
      {scene_dir}/{scene_name}_transcription/{scene_name}_transcript.json

    After this call, collect_scene_transcript() must be used to move the output
    to the canonical Transcription/ path.

    Args:
        scene_dir: Path to the scene subfolder (e.g. Source/Video/apartment).
        num_speakers: Number of speakers for diarization (-n flag).
        dry_run: If True, passes --dry-run to the transcription script.

    Raises:
        subprocess.CalledProcessError: If the subprocess exits with non-zero status.
    """
    venv_python = Path("~/YTAI/environment/.venv_transcribe/bin/python").expanduser()
    script = Path(
        "~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py"
    ).expanduser()
    cmd = [
        str(venv_python),
        str(script),
        "--project",
        str(scene_dir),
        "-n",
        str(num_speakers),
        "-y",
    ]
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=True)


def collect_scene_transcript(scene_dir: Path, project: Path) -> Path:
    """Copy per-scene transcript from legacy path to canonical Transcription/ path.

    transcribe_project.py (flat mode) writes to:
      {scene_dir}/{scene_name}_transcription/{scene_name}_transcript.json

    This function copies it to the canonical v3 location:
      {project}/01_Media/Source/Transcription/{scene_name}_transcript.json

    Args:
        scene_dir: Path to the scene subfolder (e.g. Source/Video/apartment).
        project: Project root path.

    Returns:
        Path to the destination transcript file.
    """
    scene_name = scene_dir.name
    src = scene_dir / f"{scene_name}_transcription" / f"{scene_name}_transcript.json"
    dst_dir = project / "01_Media" / "Source" / "Transcription"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{scene_name}_transcript.json"
    shutil.copy2(src, dst)
    return dst


def main():
    """CLI entry point (wired by Plan 02 orchestrator)."""
    ap = argparse.ArgumentParser(
        description="Transcribe nested multi-scene project by invoking transcribe_project.py per scene."
    )
    ap.add_argument("--project", required=True, type=Path, help="Project root path")
    ap.add_argument("--scene", default=None, help="Process single scene only (optional)")
    ap.add_argument("-n", "--speakers", type=int, default=2, help="Number of speakers for diarization")
    ap.add_argument("--dry-run", action="store_true", help="Pass --dry-run to transcription script")
    ap.add_argument("-y", action="store_true", help="Skip confirmations")
    args = ap.parse_args()

    project = args.project.resolve()
    scenes = detect_scenes(project)

    if args.scene:
        scenes = [s for s in scenes if s.name == args.scene]

    for scene_dir in scenes:
        scene_name = scene_dir.name
        if not should_transcribe_scene(project, scene_name):
            print(f"[SKIP] {scene_name}: transcript already exists")
            continue
        print(f"[TRANSCRIBE] {scene_name}")
        transcribe_scene(scene_dir, num_speakers=args.speakers, dry_run=args.dry_run)
        collect_scene_transcript(scene_dir, project)
        print(f"[DONE] {scene_name}: transcript collected")


if __name__ == "__main__":
    main()
