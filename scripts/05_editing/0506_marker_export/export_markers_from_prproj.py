#!/usr/bin/env python3
"""
Export markers from Premiere Pro .prproj file as JSON.

Reads gzip .prproj, extracts DVAMarker blocks, classifies into Assembly vs Review,
embeds full transcript, and outputs a single comprehensive JSON.

Output: Setup/Assembly/{CODE}_2_Assembly_v{N}_out.json + ~/Downloads/

Usage:
    python export_markers_from_prproj.py --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis"
"""
import argparse
import gzip
import json
import re
import shutil
import sys
from pathlib import Path
from datetime import datetime

TICKS_PER_SEC = 254016000000


def find_prproj(project: Path) -> Path | None:
    """Find the main .prproj file."""
    media_dir = project / "01_Media"
    candidates = list(media_dir.glob("*.prproj"))
    if candidates:
        return max(candidates, key=lambda p: p.stat().st_mtime)
    auto_dir = media_dir / "Adobe Premiere Pro Auto-Save"
    if auto_dir.exists():
        auto_files = list(auto_dir.glob("*.prproj"))
        if auto_files:
            return max(auto_files, key=lambda p: p.stat().st_mtime)
    return None


def parse_markers(prproj_path: Path) -> list:
    """Extract all DVAMarker blocks from .prproj file."""
    with gzip.open(prproj_path, 'rb') as f:
        text = f.read().decode('utf-8', errors='replace')

    blocks = re.findall(r'<DVAMarker>(.*?)</DVAMarker>', text, re.DOTALL)

    markers = []
    for raw in blocks:
        try:
            obj = json.loads(raw)
            dva = obj.get('DVAMarker', {})

            st = dva.get('mStartTime', {})
            start_ticks = st.get('ticks', 0) if isinstance(st, dict) else int(st or 0)
            dur = dva.get('mDuration', {})
            dur_ticks = dur.get('ticks', 0) if isinstance(dur, dict) else int(dur or 0)

            markers.append({
                'name': dva.get('mName', ''),
                'comment': dva.get('mComment', ''),
                'position_sec': round(start_ticks / TICKS_PER_SEC, 2),
                'duration_sec': round(dur_ticks / TICKS_PER_SEC, 2) if dur_ticks else 0,
                'type': dva.get('mType', ''),
            })
        except Exception:
            pass

    return markers


def classify_markers(markers: list) -> tuple:
    """Split markers into Assembly and Review lists.

    Assembly: named segments, chapter markers (Hook, Intro, etc.)
    Review: [CUT], [ALT], [SKIP] prefixed markers
    Source: markers appear in both (clip boundaries)
    """
    assembly = []
    review = []

    for m in markers:
        name = m.get('name', '')
        if not name:
            continue

        if name.startswith('[CUT]') or name.startswith('[ALT]') or name.startswith('[SKIP]'):
            review.append(m)
        elif name.startswith('Source:'):
            assembly.append(m)
            review.append(m)
        else:
            assembly.append(m)

    # Deduplicate by (name, position)
    def dedup(lst):
        seen = set()
        result = []
        for m in sorted(lst, key=lambda x: x['position_sec']):
            key = (m['name'], m['position_sec'])
            if key not in seen:
                seen.add(key)
                result.append(m)
        return result

    return dedup(assembly), dedup(review)


def build_marker_entry(m: dict) -> dict:
    """Build clean marker dict for output."""
    entry = {
        'name': m['name'],
        'position_sec': m['position_sec'],
    }
    if m['duration_sec'] > 0:
        entry['duration_sec'] = m['duration_sec']
        entry['is_chapter'] = True
    if m['comment']:
        entry['comment'] = m['comment']
    if m['type']:
        entry['type'] = m['type']
    return entry


def find_next_version(assembly_dir: Path, prefix: str) -> int:
    """Find next version number."""
    max_ver = 0
    pattern = re.compile(re.escape(prefix) + r'_v(\d+)')
    if assembly_dir.exists():
        for f in assembly_dir.iterdir():
            m = pattern.search(f.name)
            if m:
                v = int(m.group(1))
                if v > max_ver:
                    max_ver = v
    return max_ver + 1


def export_markers(project: Path) -> Path:
    """Export markers with full transcript as one comprehensive JSON."""
    prproj = find_prproj(project)
    if not prproj:
        print(f"Error: No .prproj file found in {project / '01_Media'}", file=sys.stderr)
        sys.exit(1)

    print(f"Project:  {project.name}")
    print(f"Prproj:   {prproj.name}")

    all_markers = parse_markers(prproj)
    named = [m for m in all_markers if m['name']]
    with_comments = [m for m in all_markers if m['comment']]

    print(f"Markers:  {len(all_markers)} total, {len(named)} named, {len(with_comments)} with comments")

    # Classify into Assembly and Review
    assembly_markers, review_markers = classify_markers(named)
    assembly_chapters = [m for m in assembly_markers if m.get('duration_sec', 0) > 0 and not m['name'].startswith('Source:')]
    review_chapters = [m for m in review_markers if m.get('duration_sec', 0) > 0 and not m['name'].startswith('Source:')]

    print(f"Assembly: {len(assembly_markers)} markers ({len(assembly_chapters)} chapters)")
    print(f"Review:   {len(review_markers)} markers ({len(review_chapters)} chapters)")

    # Build output
    code = re.match(r'^(YT[A-Z]{2,4}\d+)_', project.name)
    seq_name = (code.group(1) if code else project.name) + "_2_Assembly"

    output = {
        "sequence": seq_name,
        "source": prproj.name,
        "exported_at": datetime.now().isoformat(),
        "assembly": {
            "markers_count": len(assembly_markers),
            "chapters_count": len(assembly_chapters),
            "markers": [build_marker_entry(m) for m in assembly_markers],
        },
        "review": {
            "markers_count": len(review_markers),
            "chapters_count": len(review_chapters),
            "markers": [build_marker_entry(m) for m in review_markers],
        },
    }

    # Embed full transcript
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    transcript_path = tr_dir / f"{project.name}_transcript.json"
    if transcript_path.exists():
        with open(transcript_path) as f:
            full_tx = json.load(f)
        output['transcript'] = {
            'project': full_tx.get('project', ''),
            'language': full_tx.get('language', ''),
            'speakers': full_tx.get('speakers', {}),
            'stats': full_tx.get('stats', {}),
            'clips': full_tx.get('clips', []),
        }
        print(f"Transcript: {len(full_tx.get('clips', []))} clips embedded")

    # Write to Setup/Assembly/
    assembly_dir = project / "01_Media" / "Source" / "Setup" / "Assembly"
    assembly_dir.mkdir(parents=True, exist_ok=True)

    version = find_next_version(assembly_dir, seq_name)
    output['version'] = version
    output['direction'] = 'out'

    filename = f"{seq_name}_v{version}_out.json"

    out_path = assembly_dir / filename
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nWritten:  Setup/Assembly/{filename} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")

    # Copy to Downloads
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        dl_path = downloads / filename
        shutil.copy2(out_path, dl_path)
        print(f"Copied:   ~/Downloads/{filename}")

    # Summary
    print(f"\n=== Assembly ({len(assembly_chapters)} blocks) ===")
    for ch in assembly_chapters:
        print(f"  {ch['name']:<45s} {ch['duration_sec']:>6.1f}s")

    print(f"\n=== Review ({len(review_markers) - len([m for m in review_markers if m['name'].startswith('Source:')])} segments) ===")
    cuts = sum(1 for m in review_markers if m['name'].startswith('[CUT]'))
    alts = sum(1 for m in review_markers if m['name'].startswith('[ALT]'))
    skips = sum(1 for m in review_markers if m['name'].startswith('[SKIP]'))
    print(f"  CUT: {cuts} | ALT: {alts} | SKIP: {skips}")

    return out_path


def main():
    ap = argparse.ArgumentParser(description="Export markers from .prproj file")
    ap.add_argument("--project", required=True, type=Path, help="Project root path")
    args = ap.parse_args()

    project = args.project.resolve()
    if not project.exists():
        print(f"Error: {project} not found", file=sys.stderr)
        sys.exit(1)

    export_markers(project)


if __name__ == "__main__":
    main()
