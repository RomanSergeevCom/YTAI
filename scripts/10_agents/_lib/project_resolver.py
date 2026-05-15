"""Resolve YTAI project paths from a project ID (e.g. YTCR01).

Handles the messy reality:
- Mount names vary: "RYA Blue", "RYA T7 Blue 2", "RYA_T9_Black".
- Exports folder is 02_Exports/ in older projects, 03_Exports/ in newer.
- Thumbnail folder is 04_Thumbnail/ or 05_Thumbnail/.
- Filename form inside folders ≠ folder name (folder YTCR01_Arty_Dzis/, files YTCR1_review_*.json).
- Multiple projects with the same ID across disks → return ambiguity error.

Usage:
    python project_resolver.py --id YTCR01
    python project_resolver.py --id YTCR01 --json
    python project_resolver.py --id YTCR01 --root /absolute/path/to/project
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

PROJECT_ID_RE = re.compile(r"^(YT[A-Z]{2,4})(\d+)_")

DEFAULT_SEARCH_ROOTS = [
    Path.home() / "YTAI",
    Path("/Volumes"),
]


def extract_channel_code(project_id: str) -> str:
    """YTCR01 → YTCR, YTCG37 → YTCG, YTRF02 → YTRF."""
    m = re.match(r"^(YT[A-Z]{2,4})\d+$", project_id)
    if not m:
        raise ValueError(f"invalid project_id {project_id!r}; expected like 'YTCR01'")
    return m.group(1)


def expand_filename_forms(project_id: str) -> list[str]:
    """YTCR01 → ['YTCR01', 'YTCR1']  (handle zero-padding in file names vs folder names)."""
    m = re.match(r"^(YT[A-Z]{2,4})(\d+)$", project_id)
    if not m:
        return [project_id]
    channel, num = m.group(1), m.group(2)
    forms = {project_id}
    # leading-zero stripped form (YTCR01 → YTCR1, YTCG037 → YTCG37)
    forms.add(f"{channel}{int(num)}")
    # zero-padded to width 2 (YTCR1 → YTCR01)
    if len(num) == 1:
        forms.add(f"{channel}0{num}")
    return sorted(forms)


def find_project_folders(project_id: str, search_roots: list[Path]) -> list[Path]:
    """Find folders whose name matches '{project_id}_...'."""
    forms = expand_filename_forms(project_id)
    patterns = [re.compile(rf"^{re.escape(form)}(_.*)?$") for form in forms]

    matches: list[Path] = []
    seen: set[Path] = set()

    for root in search_roots:
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            if any(p.match(name) for p in patterns):
                resolved = entry.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    matches.append(entry)
            elif root == Path("/Volumes"):
                # one level deeper: project folders live INSIDE volumes, not as siblings of them.
                try:
                    sub_entries = list(entry.iterdir())
                except (PermissionError, OSError):
                    continue
                for sub in sub_entries:
                    if not sub.is_dir():
                        continue
                    if any(p.match(sub.name) for p in patterns):
                        resolved = sub.resolve()
                        if resolved not in seen:
                            seen.add(resolved)
                            matches.append(sub)

    return matches


def find_dir_by_glob(root: Path, patterns: list[str]) -> Optional[Path]:
    """Find first directory under root matching any of the case-insensitive patterns.

    Searches both the root and one level deeper (for nested versioned folders).
    Returns the newest by mtime if multiple match.
    """
    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend(root.glob(pat))
        candidates.extend(root.glob(f"**/{pat}"))
    candidates = [c for c in candidates if c.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def find_file_by_glob(root: Path, patterns: list[str]) -> Optional[Path]:
    """Like find_dir_by_glob but returns newest file."""
    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend(root.glob(pat))
        candidates.extend(root.glob(f"**/{pat}"))
    candidates = [c for c in candidates if c.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def resolve_project(project_root: Path, project_id: str) -> dict:
    """Resolve all artefact paths inside a known project root."""
    channel_code = extract_channel_code(project_id)
    filename_forms = expand_filename_forms(project_id)

    exports_dir = find_dir_by_glob(project_root, ["*Exports*", "*exports*"])
    thumbnail_dir = find_dir_by_glob(project_root, ["*Thumbnail*", "*thumbnail*"])

    # Review can live either at project root OR inside a versioned export folder.
    # Prefer the one with actual review_*.json files.
    review_dir = None
    review_analysis_json = None
    review_transcript_json = None

    review_candidates = list(project_root.glob("**/Review"))
    review_candidates = [r for r in review_candidates if r.is_dir()]
    # pick the one that actually contains review files
    for candidate in sorted(review_candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        analyses: list[Path] = []
        transcripts: list[Path] = []
        for form in filename_forms:
            analyses.extend(candidate.glob(f"{form}_review_analysis.json"))
            transcripts.extend(candidate.glob(f"{form}_review_transcript.json"))
        # fallback: any *_review_analysis.json / *_review_transcript.json
        if not analyses:
            analyses = list(candidate.glob("*_review_analysis.json"))
        if not transcripts:
            transcripts = list(candidate.glob("*_review_transcript.json"))
        if analyses and transcripts:
            review_dir = candidate
            review_analysis_json = analyses[0]
            review_transcript_json = transcripts[0]
            break

    # YouTube output folder. Prefer existing; otherwise default to {project_root}/06_YouTube.
    youtube_dir = find_dir_by_glob(project_root, ["*YouTube*", "*youtube*"])
    if youtube_dir is None:
        youtube_dir = project_root / "06_YouTube"

    # final video — newest *.mp4 under exports_dir
    final_video = None
    if exports_dir is not None:
        final_video = find_file_by_glob(exports_dir, ["*.mp4", "*.MP4", "*.mov", "*.MOV"])

    result = {
        "project_id": project_id,
        "channel_code": channel_code,
        "filename_forms": filename_forms,
        "project_root": str(project_root),
        "exports_dir": str(exports_dir) if exports_dir else None,
        "thumbnail_dir": str(thumbnail_dir) if thumbnail_dir else None,
        "review_dir": str(review_dir) if review_dir else None,
        "youtube_dir": str(youtube_dir),
        "final_video": str(final_video) if final_video else None,
        "review_analysis_json": str(review_analysis_json) if review_analysis_json else None,
        "review_transcript_json": str(review_transcript_json) if review_transcript_json else None,
    }

    warnings = []
    if exports_dir is None:
        warnings.append("no *Exports* folder found — Draper can still write description/titles, but no thumbnail reference frames")
    if review_dir is None or review_analysis_json is None:
        warnings.append("no Review/ with review_analysis.json — Draper cannot make chapters or thumbnails; run 0508_review first")
    if review_transcript_json is None:
        warnings.append("no review_transcript.json — titles/description will be weaker (no word-level timestamps)")
    if final_video is None and exports_dir is not None:
        warnings.append("Exports folder exists but no .mp4 inside — Draper packs from Review JSON only")
    if thumbnail_dir is None:
        warnings.append("no *Thumbnail* folder — concepts will be written to {project_root}/05_Thumbnail/concepts/ (created on demand)")

    result["warnings"] = warnings
    return result


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--id", dest="project_id", required=True, help="project ID, e.g. YTCR01")
    parser.add_argument("--root", dest="explicit_root", default=None, help="absolute path to project root (skip search)")
    parser.add_argument("--json", dest="emit_json", action="store_true", help="emit JSON to stdout")
    args = parser.parse_args(argv)

    project_id = args.project_id.strip()

    if args.explicit_root:
        project_root = Path(args.explicit_root).expanduser().resolve()
        if not project_root.exists():
            err = {"error": "project root does not exist", "tried": str(project_root)}
            print(json.dumps(err, indent=2, ensure_ascii=False))
            return 2
        result = resolve_project(project_root, project_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    matches = find_project_folders(project_id, DEFAULT_SEARCH_ROOTS)

    if not matches:
        searched = [str(r) for r in DEFAULT_SEARCH_ROOTS if r.exists()]
        # also enumerate volumes that exist
        if Path("/Volumes").exists():
            try:
                for v in Path("/Volumes").iterdir():
                    if v.is_dir() and v.name != "Macintosh HD":
                        searched.append(str(v))
            except OSError:
                pass
        err = {
            "error": f"project {project_id} not found",
            "searched_roots": searched,
            "hint": "attach the disk or pass --root /absolute/path/to/project",
        }
        print(json.dumps(err, indent=2, ensure_ascii=False))
        return 1

    if len(matches) > 1:
        err = {
            "error": f"multiple projects matched {project_id}",
            "matches": [
                {
                    "path": str(p),
                    "mtime": p.stat().st_mtime,
                }
                for p in matches
            ],
            "hint": "pass --root with the absolute path to disambiguate",
        }
        print(json.dumps(err, indent=2, ensure_ascii=False))
        return 2

    project_root = matches[0]
    result = resolve_project(project_root, project_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
