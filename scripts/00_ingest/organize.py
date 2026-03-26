#!/usr/bin/env python3
"""
00_ingest: Organize — Create project from discovery report.

Reads the discovery report, creates a v3.0 folder structure,
and moves files into scene-organized directories.

Usage:
    python organize.py "/path/to/raw" --dry-run
    python organize.py "/path/to/raw"
    python organize.py "/path/to/raw" --name YTRF05_Custom
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

# Template directory
SCRIPTS_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = SCRIPTS_DIR.parent / "YTAI_Folder_Templates"


# ── ANSI colors ──────────────────────────────────────────────────────────────

class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    CYAN = '\033[96m'
    RESET = '\033[0m'


def _deep_merge_template(template_path: Path, project: Path,
                         dry_run: bool = False) -> int:
    """
    Recursively merge template into project, creating missing dirs/files.
    Same logic as run_pipeline.py::_deep_merge_template.
    """
    created = 0
    for root, dirs, files in os.walk(template_path):
        rel = Path(root).relative_to(template_path)
        dst_dir = project / rel
        if not dst_dir.exists():
            if not dry_run:
                dst_dir.mkdir(parents=True, exist_ok=True)
            created += 1
        for fname in files:
            if fname == ".gitkeep":
                continue
            dst_file = dst_dir / fname
            if not dst_file.exists() and not dry_run:
                shutil.copy2(str(Path(root) / fname), str(dst_file))
    return created


def _human_size(nbytes: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} PB"


def main():
    parser = argparse.ArgumentParser(
        description="Create organized project from discovery report.")
    parser.add_argument("raw_folder", type=Path,
                        help="Path to raw footage folder "
                             "(must contain _discovery/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without doing it")
    parser.add_argument("--name",
                        help="Override project name (e.g. YTRF05_Custom)")
    parser.add_argument("--report", type=Path,
                        help="Path to discovery report "
                             "(default: _discovery/discovery_report.json)")
    args = parser.parse_args()

    raw_folder = args.raw_folder.resolve()
    if not raw_folder.is_dir():
        print(f"{C.RED}Error:{C.RESET} Not a directory: {raw_folder}")
        sys.exit(1)

    # Load report
    report_path = (args.report or
                   raw_folder / "_discovery" / "discovery_report.json")
    if not report_path.exists():
        print(f"{C.RED}Error:{C.RESET} Report not found: {report_path}")
        print(f"Run discover.py first.")
        sys.exit(1)

    with open(report_path, encoding='utf-8') as f:
        report = json.load(f)

    # Determine project name and target
    project_name = args.name or report["classification"]["project_name"]
    project_type = report["classification"]["project_type"]
    target = raw_folder.parent / project_name

    print()
    print(f"{C.BOLD}00_ingest: Organize{C.RESET}"
          f"{' (DRY RUN)' if args.dry_run else ''}")
    print(f"  Source:  {raw_folder}")
    print(f"  Target:  {target}")
    print(f"  Type:    {project_type}")
    print()

    # Check target doesn't already exist
    if target.exists() and not args.dry_run:
        print(f"{C.RED}Error:{C.RESET} Target already exists: {target}")
        print(f"Remove or rename it, or use --name to choose a different name.")
        sys.exit(1)

    # ── Step 1: Create v3.0 template ─────────────────────────────────────
    template_name = ("Type1_Footage" if project_type == "Type1_Footage"
                     else "Type2_Production")
    template_path = TEMPLATES_DIR / template_name

    if not template_path.is_dir():
        print(f"{C.RED}Error:{C.RESET} Template not found: {template_path}")
        sys.exit(1)

    print(f"  {C.CYAN}[1/4]{C.RESET} Creating v3.0 structure "
          f"from {template_name}...")

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    created = _deep_merge_template(template_path, target, dry_run=args.dry_run)
    print(f"  {C.GREEN}✓{C.RESET} {created} directories"
          f"{' would be created' if args.dry_run else ' created'}")
    print()

    # ── Step 2: Create scene subdirectories ──────────────────────────────
    scenes = report.get("scenes", [])
    print(f"  {C.CYAN}[2/4]{C.RESET} Creating {len(scenes)} scene "
          f"directories...")

    for scene in scenes:
        scene_dir = target / "01_Media" / "Source" / "Video" / scene["suggested_name"]
        audio_dir = target / "01_Media" / "Source" / "Audio" / scene["suggested_name"]
        if not args.dry_run:
            scene_dir.mkdir(parents=True, exist_ok=True)
            audio_dir.mkdir(parents=True, exist_ok=True)
        print(f"    {scene['suggested_name']}/  "
              f"{C.DIM}({scene['clip_count']} clips, "
              f"{scene['duration_human']}){C.RESET}")
    print()

    # ── Step 3: Move files ───────────────────────────────────────────────
    moves = report.get("organization_plan", {}).get("moves", [])
    print(f"  {C.CYAN}[3/4]{C.RESET} "
          f"{'Would move' if args.dry_run else 'Moving'} "
          f"{len(moves)} files...")

    moved = 0
    failed = 0
    total_size = 0

    for move in moves:
        src = raw_folder / move["from"]
        dst = target / move["to"]

        if not src.exists():
            print(f"    {C.YELLOW}⚠{C.RESET} Not found: {move['from']}")
            failed += 1
            continue

        if args.dry_run:
            size = src.stat().st_size
            total_size += size
            moved += 1
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                size = src.stat().st_size
                shutil.move(str(src), str(dst))
                total_size += size
                moved += 1
            except OSError as e:
                print(f"    {C.RED}✗{C.RESET} Failed: {move['from']} → {e}")
                failed += 1

    verb = "would be moved" if args.dry_run else "moved"
    print(f"  {C.GREEN}✓{C.RESET} {moved} files {verb} "
          f"({_human_size(total_size)})")
    if failed:
        print(f"  {C.YELLOW}⚠{C.RESET} {failed} files skipped")
    print()

    # ── Step 4: Handle Archive/ ──────────────────────────────────────────
    archive_info = report.get("inventory", {}).get("archive", {})
    archive_dir = None
    for candidate in ["Archive", "Архив", "archive"]:
        p = raw_folder / candidate
        if p.is_dir():
            archive_dir = p
            break

    if archive_dir and archive_dir.is_dir():
        print(f"  {C.CYAN}[4/4]{C.RESET} "
              f"{'Would move' if args.dry_run else 'Moving'} "
              f"Archive/ → Setup/Archive/...")
        dst_archive = target / "01_Media" / "Source" / "Setup" / "Archive"
        if not args.dry_run:
            dst_archive.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archive_dir), str(dst_archive))
        print(f"  {C.GREEN}✓{C.RESET} Archive "
              f"{'would be moved' if args.dry_run else 'moved'}")
    else:
        print(f"  {C.CYAN}[4/4]{C.RESET} No archive folder "
              f"{C.DIM}(skipped){C.RESET}")
    print()

    # ── Copy _discovery/ for audit trail ─────────────────────────────────
    discovery_src = raw_folder / "_discovery"
    if discovery_src.is_dir() and not args.dry_run:
        dst_discovery = target / "01_Media" / "Source" / "Setup" / "_discovery"
        shutil.copytree(str(discovery_src), str(dst_discovery),
                        dirs_exist_ok=True)

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"  {C.BOLD}{'Plan' if args.dry_run else 'Done'}:{C.RESET}")
    print(f"    Project: {C.GREEN}{project_name}{C.RESET}")
    print(f"    Location: {target}")
    print(f"    Files: {moved} moved, {failed} skipped")
    print()

    if args.dry_run:
        print(f"  {C.BOLD}To apply:{C.RESET}")
        print(f"    python scripts/00_ingest/organize.py \"{raw_folder}\"")
    else:
        print(f"  {C.BOLD}Next:{C.RESET}")
        print(f"    python scripts/run_pipeline.py \"{target}\"")
    print()


if __name__ == "__main__":
    main()
