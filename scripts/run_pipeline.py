#!/usr/bin/env python3
"""
YTAI Pipeline Runner — single entry point for the full pipeline.

Usage:
    python run_pipeline.py "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python run_pipeline.py "$PROJECT" --speakers 2 --no-pause
    python run_pipeline.py "$PROJECT" --only transcribe
    python run_pipeline.py "$PROJECT" --list
    python run_pipeline.py "$PROJECT" --dry-run

Stages:
    0. init           — Create v3.0 folder structure (auto if missing)
    1. extract_audio  — Extract WAV from video clips + concat FULL_AUDIO
    2. sync_dji       — Sync DJI wireless audio to clips (optional)
    3. transcribe     — Whisper + Pyannote diarization

Speaker ID is done separately via Claude Desktop project.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# ============================================================================
# Constants
# ============================================================================

SCRIPTS_DIR = Path(__file__).parent
TEMPLATES_DIR = SCRIPTS_DIR.parent / "YTAI_Folder_Templates"

STAGES = [
    {
        "id": "init",
        "name": "Init folders",
        "script": None,  # built-in
    },
    {
        "id": "extract_audio",
        "name": "Extract audio",
        "script": "01_prepare/02_extract_audio.py",
    },
    {
        "id": "sync_dji",
        "name": "DJI sync",
        "script": "01_prepare/03_sync_dji_audio.py",
        "optional": True,
    },
    {
        "id": "transcribe",
        "name": "Transcribe",
        "script": "02_transcribe/020101_transcribe/transcribe_project.py",
    },
]

STAGE_IDS = [s["id"] for s in STAGES]


# ============================================================================
# Formatting
# ============================================================================

def fmt_duration(seconds: float) -> str:
    """Format seconds as 'Xm Ys'."""
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def print_header(project_name: str) -> None:
    line = "━" * 58
    print(f"\n{line}")
    print(f" YTAI Pipeline — {project_name}")
    print(f"{line}\n")


def print_footer(completed: int, total: int, elapsed: float, project: Path) -> None:
    line = "━" * 58
    print(f"\n{line}")
    print(f"✅ Done! {completed}/{total} stages in {fmt_duration(elapsed)}")
    print()
    print("Output:")
    print(f"  Transcription/*_transcript.json    — transcript")
    print(f"  Transcription/*_transcript.srt     — subtitles")
    print(f"  Setup/*_ingest.json                — Premiere UXP")
    print()
    print("Next:")
    print(f"  → Speaker ID via Claude Desktop project")
    print(f'  → Or manually: python 03_speaker_id/00_process_all.py --project "{project}"')
    print(f"{line}\n")


def stage_label(idx: int, total: int, name: str) -> str:
    return f"[{idx}/{total}] {name}"


# ============================================================================
# Stage checks
# ============================================================================

def check_init(project: Path) -> bool:
    """True if v3.0 folder structure exists."""
    return (project / "01_Media" / "Source" / "Video").is_dir()


def check_extract_audio(project: Path) -> bool:
    """True if FULL_AUDIO.wav exists."""
    tr = project / "01_Media" / "Source" / "Transcription"
    return tr.is_dir() and any(tr.glob("*_FULL_AUDIO.wav"))


def check_sync_dji(project: Path) -> bool:
    """True if synced DJI audio exists."""
    audio = project / "01_Media" / "Source" / "Audio"
    return audio.is_dir() and any(audio.glob("*.wav"))


def check_transcribe(project: Path) -> bool:
    """True if transcript JSON exists."""
    tr = project / "01_Media" / "Source" / "Transcription"
    return tr.is_dir() and any(tr.glob("*_transcript.json"))


def has_dji_files(project: Path) -> bool:
    """True if DJI source audio files exist."""
    dji = project / "99_Pipeline" / "DJI_Audio"
    if not dji.is_dir():
        return False
    return any(dji.glob("*.wav"))


def has_video_files(project: Path) -> bool:
    """True if video source files exist."""
    video = project / "01_Media" / "Source" / "Video"
    if not video.is_dir():
        return False
    exts = (".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv")
    return any(f for f in video.iterdir() if f.suffix.lower() in exts)


CHECK_FNS = {
    "init": check_init,
    "extract_audio": check_extract_audio,
    "sync_dji": check_sync_dji,
    "transcribe": check_transcribe,
}


# ============================================================================
# Init stage — create folder structure
# ============================================================================

def run_init(project: Path, folder_type: str, dry_run: bool = False) -> bool:
    """Create v3.0 folder structure if missing."""
    if check_init(project):
        return True

    template_name = "Type1_Footage" if folder_type == "footage" else "Type2_Production"
    template_path = TEMPLATES_DIR / template_name

    if not template_path.is_dir():
        print(f"  ✗ Template not found: {template_path}")
        return False

    if dry_run:
        print(f"  → Would create {folder_type} structure from {template_name}/")
        return True

    # Copy template
    if project.is_dir():
        # Folder exists — add missing items
        for item in os.listdir(template_path):
            src = template_path / item
            dst = project / item
            if not dst.exists():
                if src.is_dir():
                    shutil.copytree(str(src), str(dst))
                else:
                    shutil.copy2(str(src), str(dst))
    else:
        shutil.copytree(str(template_path), str(project))

    # Remove .gitkeep files
    for root, dirs, files in os.walk(project):
        for f in files:
            if f == ".gitkeep":
                os.remove(os.path.join(root, f))

    print(f"  → Created {folder_type} structure")
    return True


# ============================================================================
# Run a pipeline script as subprocess
# ============================================================================

def run_script(
    script_rel: str,
    project: Path,
    extra_args: list = None,
    dry_run: bool = False,
) -> bool:
    """Run a pipeline script via subprocess with live output."""
    script_path = SCRIPTS_DIR / script_rel

    if not script_path.exists():
        print(f"  ✗ Script not found: {script_path}")
        return False

    cmd = [sys.executable, str(script_path), "--project", str(project)]
    if extra_args:
        cmd.extend(extra_args)

    if dry_run:
        print(f"  → Would run: {' '.join(cmd)}")
        return True

    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        return result.returncode == 0
    except KeyboardInterrupt:
        print("\n  ⚠ Interrupted by user")
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False


# ============================================================================
# Ask continue
# ============================================================================

def ask_continue(stage_name: str) -> bool:
    """Prompt user to continue after a stage."""
    try:
        response = input(f"\n  {stage_name} complete. Continue? [Y/n]: ").strip().lower()
        return response != "n"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ============================================================================
# List mode
# ============================================================================

def list_stages(project: Path) -> None:
    """Print status of each stage for this project."""
    project_name = project.name
    print_header(project_name)

    for i, stage in enumerate(STAGES):
        sid = stage["id"]
        name = stage["name"]
        check_fn = CHECK_FNS.get(sid)

        if check_fn and check_fn(project):
            status = "✓ done"
        elif sid == "sync_dji" and not has_dji_files(project):
            status = "⏭ no DJI files"
        else:
            status = "○ pending"

        label = f"[{i}/{len(STAGES) - 1}] {name}"
        print(f"  {label:<35} {status}")

    print()


# ============================================================================
# Main pipeline
# ============================================================================

def run_pipeline(args) -> int:
    """Execute the pipeline stages."""
    project = Path(args.project).resolve()
    project_name = project.name

    # --list mode
    if args.list:
        list_stages(project)
        return 0

    print_header(project_name)

    # Determine which stages to run
    if args.only:
        stage_ids_to_run = [args.only]
    else:
        start = STAGE_IDS.index(args.start_from) if args.start_from else 0
        end = STAGE_IDS.index(args.stop_after) if args.stop_after else len(STAGES) - 1
        stage_ids_to_run = STAGE_IDS[start : end + 1]

    # Filter to active stages
    active_stages = [s for s in STAGES if s["id"] in stage_ids_to_run]
    total = len(active_stages)

    start_time = time.time()
    completed = 0

    for idx, stage in enumerate(active_stages):
        sid = stage["id"]
        name = stage["name"]
        label = stage_label(idx, total - 1, name)
        check_fn = CHECK_FNS.get(sid)

        # Smart skip: already done?
        if not args.force and check_fn and check_fn(project):
            print(f"  {label:<40} ✓ already done")
            completed += 1
            continue

        # Optional stage: skip if no source files
        if stage.get("optional") and sid == "sync_dji":
            if not has_dji_files(project):
                print(f"  {label:<40} ⏭ skipped (no DJI files)")
                completed += 1
                continue
            # sync_dji requires --tz-offset
            if args.tz_offset is None:
                print(f"  {label:<40} ⏭ skipped (--tz-offset not provided)")
                completed += 1
                continue

        # Pre-flight: video files exist?
        if sid in ("extract_audio", "sync_dji") and not has_video_files(project):
            if args.dry_run:
                print(f"  {label:<40} ⚠ no video files yet")
                completed += 1
                continue
            print(f"  {label:<40} ✗ no video files in Source/Video/")
            return 1

        print(f"  {label:<40} ⏳ running...")
        stage_start = time.time()

        # Run
        success = False
        if sid == "init":
            success = run_init(project, args.type, dry_run=args.dry_run)
        else:
            extra = build_extra_args(sid, args)
            success = run_script(
                stage["script"], project,
                extra_args=extra,
                dry_run=args.dry_run,
            )

        stage_elapsed = time.time() - stage_start

        if success:
            print(f"  {label:<40} ✓ {fmt_duration(stage_elapsed)}")
            completed += 1
        else:
            print(f"  {label:<40} ✗ failed ({fmt_duration(stage_elapsed)})")
            return 1

        # Pause between stages
        if not args.no_pause and not args.dry_run and idx < total - 1:
            if not ask_continue(name):
                print("\n  Stopped by user.")
                return 0

    elapsed = time.time() - start_time

    if not args.dry_run:
        print_footer(completed, total, elapsed, project)

    return 0


def build_extra_args(stage_id: str, args) -> list:
    """Build extra CLI arguments for a stage script."""
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
  # Full pipeline
  python run_pipeline.py "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --speakers 2

  # With DJI audio sync
  python run_pipeline.py "$PROJECT" --speakers 2 --tz-offset 4

  # Single stage
  python run_pipeline.py "$PROJECT" --only transcribe --speakers 2

  # Check status
  python run_pipeline.py "$PROJECT" --list

  # Dry run
  python run_pipeline.py "$PROJECT" --dry-run

Stages:
  0. init           Create v3.0 folder structure (auto)
  1. extract_audio  Extract WAV from clips + FULL_AUDIO
  2. sync_dji       Sync DJI wireless audio (optional)
  3. transcribe     Whisper + Pyannote diarization

Speaker ID is done separately via Claude Desktop project.
        """,
    )

    # Positional
    parser.add_argument("project", help="Path to project folder")

    # Stage selection
    parser.add_argument("--only", choices=STAGE_IDS,
                        help="Run only this stage")
    parser.add_argument("--from", dest="start_from", choices=STAGE_IDS,
                        help="Start from this stage (default: init)")
    parser.add_argument("--to", dest="stop_after", choices=STAGE_IDS,
                        help="Stop after this stage (default: transcribe)")

    # Pipeline parameters
    parser.add_argument("-n", "--speakers", type=int,
                        help="Number of speakers for Pyannote diarization")
    parser.add_argument("--language",
                        help="Language code for Whisper (default: auto-detect)")
    parser.add_argument("-m", "--model", default=None,
                        help="Whisper model (default: large-v3)")
    parser.add_argument("--tz-offset", type=float,
                        help="Timezone offset for DJI sync (e.g. 4 for Dubai)")
    parser.add_argument("--type", choices=["footage", "production"],
                        default="footage",
                        help="Folder type for init (default: footage)")

    # Behavior
    parser.add_argument("--no-pause", action="store_true",
                        help="Run without pausing between stages")
    parser.add_argument("--force", action="store_true",
                        help="Re-run stages even if output exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing")
    parser.add_argument("--list", action="store_true",
                        help="Show status of each stage and exit")

    args = parser.parse_args()
    sys.exit(run_pipeline(args))


if __name__ == "__main__":
    main()
