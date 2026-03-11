#!/usr/bin/env python3
"""
YTAI: Process All
Master script - runs all transcript processing stages.

Usage:
    python process_all.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python process_all.py --project "/path/to/project" --no-pause
    python process_all.py --project "/path/to/project" --start-from 3

Stages:
    1. 01_extract_speakers.py  - Extract speaker utterances
    2. 02_analyze_speakers.py  - LLM name analysis
    3. 03_apply_names.py       - Apply names to transcript
    4. 04_split_clips.py       - Split by video clips
"""

import argparse
import sys
import subprocess
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    get_project_paths,
    ensure_dirs,
    generate_timestamp,
    format_duration,
    setup_logging,
    print_header,
    print_section,
)


# ============================================================================
# Stage execution
# ============================================================================

def run_stage(
    stage_num: int,
    script_name: str,
    project_path: str,
    extra_args: list = None,
    logger = None
) -> bool:
    """
    Run a single stage.

    Returns:
        True if successful
    """
    scripts_dir = Path(__file__).parent
    script_path = scripts_dir / script_name
    
    if not script_path.exists():
        if logger:
            logger.error(f"Script not found: {script_path}")
        return False
    
    cmd = [
        sys.executable,
        str(script_path),
        "--project", project_path
    ]
    
    if extra_args:
        cmd.extend(extra_args)
    
    if logger:
        logger.debug(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # Show output in real time
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        if logger:
            logger.error(f"Error running {script_name}: {e}")
        return False


def ask_continue(prompt: str = "Continue?") -> bool:
    """Ask the user whether to continue."""
    try:
        response = input(f"\n{prompt} [Y/n]: ").strip().lower()
        return response != "n"
    except (EOFError, KeyboardInterrupt):
        print()
        return False


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI: Run all transcript processing stages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Full cycle with pauses for review
    python process_all.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"

    # Automatic without pauses
    python process_all.py --project "/path/to/project" --no-pause

    # Start from stage 3 (speakers already analyzed)
    python process_all.py --project "/path/to/project" --start-from 3

    # Only stages 1-2
    python process_all.py --project "/path/to/project" --stop-after 2
        """
    )
    
    parser.add_argument("--project", required=True, help="Path to project folder")
    parser.add_argument("--no-pause", action="store_true", help="Do not pause for review")
    parser.add_argument("--start-from", type=int, choices=[1, 2, 3, 4], default=1,
                        help="Start from stage N (default: 1)")
    parser.add_argument("--stop-after", type=int, choices=[1, 2, 3, 4], default=4,
                        help="Stop after stage N (default: 4)")
    parser.add_argument("--force", action="store_true",
                        help="Pass --force to 02_analyze_speakers.py")
    
    args = parser.parse_args()
    
    # Validate paths
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    
    ensure_dirs(paths)
    
    project_name = paths["project_name"]
    
    # Set up logging
    logger = setup_logging(paths["logs_dir"], project_name, "process_all")
    
    # ================================================================
    # Header
    # ================================================================
    print_header("YTAI: FULL TRANSCRIPT PROCESSING")
    logger.info(f"Project: {project_name}")
    logger.info(f"Path: {paths['project_root']}")
    logger.info(f"Stages: {args.start_from} - {args.stop_after}")
    if args.no_pause:
        logger.info("Mode: automatic (no pauses)")
    else:
        logger.info("Mode: interactive (with pauses for review)")
    logger.info("")
    
    start_time = time.time()
    stages_completed = 0
    
    # ================================================================
    # STAGE 1: Extract Speakers
    # ================================================================
    if args.start_from <= 1 <= args.stop_after:
        print_section("[1/4] EXTRACTING SPEAKER UTTERANCES")
        logger.info("Running 01_extract_speakers.py...")
        logger.info("")

        success = run_stage(1, "01_extract_speakers.py", str(paths["project_root"]), logger=logger)

        if not success:
            logger.error("Stage 1 failed")
            sys.exit(1)

        stages_completed += 1

        if not args.no_pause and args.stop_after > 1:
            logger.info("")
            logger.info("→ Review files in 02_02_Speakers/")
            logger.info("→ Load the SRT onto master video to verify speaker separation")

            if not ask_continue():
                logger.info("Stopped by user")
                sys.exit(0)
    
    # ================================================================
    # STAGE 2: Analyze Speakers
    # ================================================================
    if args.start_from <= 2 <= args.stop_after:
        print_section("[2/4] SPEAKER ANALYSIS (LLM)")
        logger.info("Running 02_analyze_speakers.py...")
        logger.info("")

        extra_args = []
        if args.force:
            extra_args.append("--force")

        success = run_stage(2, "02_analyze_speakers.py", str(paths["project_root"]),
                           extra_args=extra_args, logger=logger)

        if not success:
            logger.error("Stage 2 failed")
            sys.exit(1)

        stages_completed += 1

        if not args.no_pause and args.stop_after > 2:
            logger.info("")
            logger.info("→ Review *_analyze_speakers_*_report.txt")
            logger.info("→ Edit *_analyze_speakers_*.json if needed")

            if not ask_continue():
                logger.info("Stopped by user")
                sys.exit(0)
    
    # ================================================================
    # STAGE 3: Apply Names
    # ================================================================
    if args.start_from <= 3 <= args.stop_after:
        print_section("[3/4] APPLYING NAMES")
        logger.info("Running 03_apply_names.py...")
        logger.info("")

        success = run_stage(3, "03_apply_names.py", str(paths["project_root"]), logger=logger)

        if not success:
            logger.error("Stage 3 failed")
            sys.exit(1)

        stages_completed += 1

        if not args.no_pause and args.stop_after > 3:
            logger.info("")
            logger.info("→ Review *_apply_names_*.txt - read the dialogue")

            if not ask_continue():
                logger.info("Stopped by user")
                sys.exit(0)
    
    # ================================================================
    # STAGE 4: Split Clips
    # ================================================================
    if args.start_from <= 4 <= args.stop_after:
        print_section("[4/4] SPLITTING BY CLIPS")
        logger.info("Running 04_split_clips.py...")
        logger.info("")

        success = run_stage(4, "04_split_clips.py", str(paths["project_root"]), logger=logger)

        if not success:
            logger.error("Stage 4 failed")
            sys.exit(1)

        stages_completed += 1
    
    # ================================================================
    # Summary
    # ================================================================
    elapsed = time.time() - start_time

    print()
    print_header("PROCESSING COMPLETE", char="=")
    logger.info(f"Stages completed: {stages_completed}")
    logger.info(f"Time: {format_duration(elapsed)}")
    logger.info("")
    logger.info("Results:")
    logger.info(f"  02_03_Named/     - Transcript with names (.json, .txt, .srt)")
    logger.info(f"  02_04_ByClips/   - XLSX table + SRT for each clip")
    logger.info("")
    logger.info("To verify in Premiere Pro:")
    logger.info("  1. Import the clip and its corresponding SRT")
    logger.info("  2. Make sure the subtitles match the speech")


if __name__ == "__main__":
    main()
