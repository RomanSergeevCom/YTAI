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
        comment = m.get('comment', '')

        # User edit markers (/ prefix in comment) — always include in assembly
        if comment.startswith('/'):
            assembly.append(m)
            continue

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


def enrich_markers_with_timecodes(markers: list, transcript: dict) -> list:
    """Add tc_in, tc_out, source_file to each marker using position-based matching.

    Uses Source: markers as clip anchors on the timeline, then finds the
    transcript segment at the marker's offset within each clip.
    """
    # Build clip timeline from Source: markers
    clip_regions = []
    for m in sorted(markers, key=lambda x: x['position_sec']):
        if m['name'].startswith('Source: '):
            clip_regions.append({
                'timeline_start': m['position_sec'],
                'filename': m['name'].replace('Source: ', ''),
            })

    if not clip_regions:
        return markers

    # Build per-clip segment index from transcript
    clip_segments = {}
    for clip in transcript.get('clips', []):
        segs = []
        for s in clip.get('segments', []):
            segs.append({
                'start': s['start'], 'end': s['end'],
                'text': s.get('text', ''),
                'confidence': s.get('confidence', s.get('avg_confidence', 0)),
                'low_confidence': s.get('low_confidence', False),
            })
        clip_segments[clip['filename']] = segs

    def find_clip_and_offset(pos):
        for i, cr in enumerate(clip_regions):
            next_start = clip_regions[i + 1]['timeline_start'] if i + 1 < len(clip_regions) else float('inf')
            if cr['timeline_start'] <= pos < next_start:
                return cr['filename'], pos - cr['timeline_start']
        return None, 0

    def find_segment_at_offset(filename, offset, tolerance=5.0):
        best, best_dist = None, float('inf')
        for s in clip_segments.get(filename, []):
            if s['start'] - tolerance <= offset <= s['end'] + tolerance:
                dist = abs((s['start'] + s['end']) / 2 - offset)
                if dist < best_dist:
                    best_dist = dist
                    best = s
        return best

    # Enrich each marker
    enriched = 0
    for m in markers:
        if m['name'].startswith('Source:'):
            continue
        fname, offset = find_clip_and_offset(m['position_sec'])
        if not fname:
            continue
        seg = find_segment_at_offset(fname, offset)
        if seg:
            m['source_file'] = fname
            m['tc_in'] = round(seg['start'], 1)
            m['tc_out'] = round(seg['end'], 1)
            m['full_text'] = seg['text']
            m['confidence'] = round(seg['confidence'], 3)
            m['low_confidence'] = seg['low_confidence']
            enriched += 1
        else:
            m['source_file'] = fname

    print(f"Enriched: {enriched}/{len([m for m in markers if not m['name'].startswith('Source:')])} markers with tc_in/tc_out")
    return markers


def build_marker_entry(m: dict) -> dict:
    """Build clean marker dict for output."""
    entry = {
        'name': m['name'],
        'position_sec': m['position_sec'],
    }
    if m.get('source_file'):
        entry['source_file'] = m['source_file']
    if m.get('tc_in') is not None:
        entry['tc_in'] = m['tc_in']
        entry['tc_out'] = m['tc_out']
    if m.get('full_text'):
        entry['full_text'] = m['full_text']
    if m.get('confidence'):
        entry['confidence'] = m['confidence']
    if m.get('low_confidence'):
        entry['low_confidence'] = True
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

    # Enrich with tc_in/tc_out from transcript
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    transcript_path = tr_dir / f"{project.name}_transcript.json"
    if transcript_path.exists():
        with open(transcript_path) as f:
            full_tx = json.load(f)
        named = enrich_markers_with_timecodes(named, full_tx)
    else:
        full_tx = {}

    # Classify into Assembly and Review
    assembly_markers, review_markers = classify_markers(named)
    assembly_chapters = [m for m in assembly_markers if m.get('duration_sec', 0) > 0 and not m['name'].startswith('Source:')]
    review_chapters = [m for m in review_markers if m.get('duration_sec', 0) > 0 and not m['name'].startswith('Source:')]

    print(f"Assembly: {len(assembly_markers)} markers ({len(assembly_chapters)} chapters)")
    print(f"Review:   {len(review_markers)} markers ({len(review_chapters)} chapters)")

    # Build output
    code = re.match(r'^(YT[A-Z]{2,4}\d+)_', project.name)
    code_str = code.group(1) if code else project.name
    seq_name = code_str + "_Assembly"

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

    # Transcript NOT embedded — too large (3MB+), Claude Desktop has transcript_assembly.json separately

    # Embed latest brief so Claude Desktop has segments + / comments in one file
    assembly_dir = project / "01_Media" / "Source" / "Setup" / "Assembly"
    assembly_dir.mkdir(parents=True, exist_ok=True)
    brief_re = re.compile(re.escape(code_str) + r'_Assembly_v(\d+)_in\.json$')
    latest_brief = None
    latest_brief_ver = 0
    if assembly_dir.exists():
        for f in assembly_dir.iterdir():
            bm = brief_re.search(f.name)
            if bm:
                bv = int(bm.group(1))
                if bv > latest_brief_ver:
                    latest_brief_ver = bv
                    latest_brief = f
    if latest_brief:
        with open(latest_brief, encoding='utf-8') as bf:
            output['brief'] = json.load(bf)
        output['brief_source'] = latest_brief.name
        print(f"Brief:      {latest_brief.name} embedded ({len(output['brief'].get('segments', []))} segments)")

    # Write to Setup/Assembly/

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
