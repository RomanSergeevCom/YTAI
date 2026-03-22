#!/usr/bin/env python3
"""Place a downloaded Assembly brief into the correct project folder.

Finds the latest *_Assembly_*_in.json in ~/Downloads/ and copies it
to the project's Setup/Assembly/ directory with proper versioning.

Usage:
    python place_brief.py <project_path>
    python place_brief.py /Volumes/RYA\ T7\ Black/YTCR01_Arty_Dzis

Or with explicit file:
    python place_brief.py <project_path> --file ~/Downloads/YTCR01_Assembly_v1_in.json
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def find_latest_brief_in_downloads(code: str) -> Path | None:
    """Find the most recent *_Assembly_*_in.json in ~/Downloads/."""
    downloads = Path.home() / "Downloads"
    pattern = f"{code}_Assembly_*_in.json"
    candidates = sorted(downloads.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def find_next_version(assembly_dir: Path, code: str) -> int:
    """Find next available version number."""
    max_ver = 0
    for f in assembly_dir.iterdir():
        m = re.search(rf'{re.escape(code)}_Assembly_v(\d+)', f.name)
        if m:
            v = int(m.group(1))
            if v > max_ver:
                max_ver = v
    return max_ver + 1


def main():
    parser = argparse.ArgumentParser(description="Place Assembly brief into project folder")
    parser.add_argument("project", type=Path, help="Project root path")
    parser.add_argument("--file", "-f", type=Path, default=None,
                        help="Specific brief file (default: latest from ~/Downloads/)")
    args = parser.parse_args()

    if not args.project.exists():
        print(f"Error: project path not found: {args.project}", file=sys.stderr)
        sys.exit(1)

    # Extract project code
    code_match = re.match(r'^(YT[A-Z]{2,4}\d+)', args.project.name)
    if not code_match:
        print(f"Error: can't extract project code from '{args.project.name}'", file=sys.stderr)
        sys.exit(1)
    code = code_match.group(1)

    # Find source file
    if args.file:
        src = args.file
    else:
        src = find_latest_brief_in_downloads(code)
        if not src:
            print(f"Error: no {code}_Assembly_*_in.json found in ~/Downloads/", file=sys.stderr)
            sys.exit(1)

    if not src.exists():
        print(f"Error: file not found: {src}", file=sys.stderr)
        sys.exit(1)

    # Validate JSON
    try:
        with open(src) as f:
            data = json.load(f)
        seg_count = len(data.get("segments", []))
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    # Ensure Assembly directory exists
    assembly_dir = args.project / "01_Media" / "Source" / "Setup" / "Assembly"
    assembly_dir.mkdir(parents=True, exist_ok=True)

    # Determine target name with proper version
    next_ver = find_next_version(assembly_dir, code)

    # Check if source already has a version
    src_ver_match = re.search(r'_v(\d+)_in\.json$', src.name)
    if src_ver_match:
        src_ver = int(src_ver_match.group(1))
        # Use source version if it doesn't conflict, otherwise use next
        target_name = f"{code}_Assembly_v{src_ver}_in.json"
        if (assembly_dir / target_name).exists():
            target_name = f"{code}_Assembly_v{next_ver}_in.json"
    else:
        target_name = f"{code}_Assembly_v{next_ver}_in.json"

    target = assembly_dir / target_name
    shutil.copy2(src, target)

    print(f"Source:   {src.name} ({seg_count} segments)")
    print(f"Target:   {target}")
    print(f"Done.")


if __name__ == "__main__":
    main()
