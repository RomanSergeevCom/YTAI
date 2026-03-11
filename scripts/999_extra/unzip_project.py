#!/usr/bin/env python3
"""
unzip_project.py — Extract all .zip files in-place into the same folder.

Designed for Google Drive multi-part zip downloads (e.g. YTCG37_Anamaria).
Flattens nested folders and skips macOS junk (__MACOSX, .DS_Store).

Usage:
    source ~/YTAI/environment/.venv_ytai-prod/bin/activate
    python ~/YTAI/scripts/999_extra/unzip_project.py --path ~/Desktop/YTCG37_Anamaria

Flags:
    --path      Path to folder containing .zip files (required)
"""

import argparse
import shutil
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

# Files/folders to skip during extraction
JUNK_PREFIXES = ("__MACOSX", "._", ".DS_Store")


def is_junk(name: str) -> bool:
    """Check if a zip entry is macOS junk."""
    for part in Path(name).parts:
        if any(part.startswith(p) or part == p for p in JUNK_PREFIXES):
            return True
    return False


def format_size(size_bytes: float) -> str:
    """Human-readable file size."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def format_duration(seconds: float) -> str:
    """Human-readable duration."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.0f}s"


def unzip_project(target_path: Path) -> None:
    """Extract all .zip files from target_path into target_path/extracted/."""

    start_time = time.time()

    # ── Validate ──
    if not target_path.exists():
        print(f"ERROR: Path does not exist: {target_path}")
        sys.exit(1)
    if not target_path.is_dir():
        print(f"ERROR: Not a directory: {target_path}")
        sys.exit(1)

    # ── Find zip files ──
    zips = sorted(target_path.glob("*.zip"))
    if not zips:
        print(f"ERROR: No .zip files found in {target_path}")
        sys.exit(1)

    total_zip_size = sum(z.stat().st_size for z in zips)
    print(f"Found {len(zips)} zip file(s) in: {target_path}")
    print(f"Total archive size: {format_size(total_zip_size)}\n")
    for i, z in enumerate(zips, 1):
        print(f"  {i}. {z.name}  ({format_size(z.stat().st_size)})")

    # ── Output ──
    output_dir = target_path

    # ── Extract ──
    print(f"\nExtracting to: {output_dir}\n")

    total_files = 0
    total_size = 0
    total_skipped_junk = 0
    errors = 0
    all_extensions = Counter()
    seen_filenames = {}  # filename -> source zip (for duplicate detection)

    for zip_path in zips:
        zip_files = 0
        zip_size = 0
        zip_skipped = 0

        print(f"── {zip_path.name} ──")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                all_members = zf.namelist()
                valid_members = [m for m in all_members if not is_junk(m) and not m.endswith("/")]
                junk_count = len(all_members) - len(valid_members) - sum(1 for m in all_members if m.endswith("/"))
                zip_skipped = junk_count

                for member in valid_members:
                    try:
                        info = zf.getinfo(member)

                        # Flatten: extract to top level
                        filename = Path(member).name
                        dest = output_dir / filename

                        # Duplicate check
                        if dest.exists() or filename in seen_filenames:
                            prev = seen_filenames.get(filename, "filesystem")
                            print(f"  ⚠ DUPLICATE: {filename} (already from {prev})")

                        # Extract to temp, then move to top level
                        zf.extract(member, output_dir / "__tmp__")
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        src = output_dir / "__tmp__" / member
                        src.rename(dest)

                        seen_filenames[filename] = zip_path.name
                        ext = Path(member).suffix.upper() or "(no ext)"
                        all_extensions[ext] += 1
                        zip_files += 1
                        zip_size += info.file_size

                    except Exception as e:
                        print(f"  ✗ Failed: '{member}': {e}")
                        errors += 1

                print(f"  ✓ {zip_files} file(s), {format_size(zip_size)}", end="")
                if zip_skipped > 0:
                    print(f", skipped {zip_skipped} junk", end="")
                print()

        except zipfile.BadZipFile:
            print(f"  ✗ Bad zip file, skipping")
            errors += 1
        except Exception as e:
            print(f"  ✗ Error: {e}")
            errors += 1

        total_files += zip_files
        total_size += zip_size
        total_skipped_junk += zip_skipped

    # Clean up temp folder if flatten was used
    tmp_dir = output_dir / "__tmp__"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    # ── Summary ──
    elapsed = time.time() - start_time

    print()
    print(f"{'='*55}")
    print(f"  EXTRACTION COMPLETE")
    print(f"{'='*55}")
    print(f"  Zip archives:     {len(zips)}")
    print(f"  Files extracted:   {total_files}")
    print(f"  Total size:        {format_size(total_size)}")
    if total_skipped_junk:
        print(f"  Junk skipped:      {total_skipped_junk}")
    if errors:
        print(f"  Errors:            {errors}")
    print(f"  Time:              {format_duration(elapsed)}")
    print(f"  Output:            {output_dir}")

    # File type breakdown
    if all_extensions:
        print(f"\n  File types:")
        for ext, count in all_extensions.most_common():
            print(f"    {ext:<10} {count} file(s)")

    print(f"{'='*55}")

    # Status
    if errors:
        print(f"\n⚠ Completed with {errors} error(s)")
    else:
        print(f"\n✓ All OK")


def main():
    parser = argparse.ArgumentParser(
        description="Extract all .zip files from a folder into an 'extracted/' subfolder."
    )
    parser.add_argument(
        "--path",
        type=str,
        required=True,
        help="Path to folder containing .zip files",
    )

    args = parser.parse_args()
    target = Path(args.path).expanduser().resolve()
    unzip_project(target)


if __name__ == "__main__":
    main()
