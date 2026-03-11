#!/usr/bin/env python3
"""
YTAI Stage 05: Generate Screen Cues SRT

Reads edit_brief.json (screens[] + segments[]) and generates a timeline-accurate
SRT file with Production Cue descriptions:
  Output: {project}_4_ScreenCues_captions.srt

Each SRT entry describes one screen cue:
  - Screen type (CHAPTER TITLE, LOWER THIRD, etc.)
  - Title, subtitle, body content

Timeline positions mirror the UXP Assembly sequence:
  segments sorted by block ASC + brief order → cumulative positions.

Usage:
    python generate_screen_cues.py --brief YTAI_Edit_edit_brief.json
    python generate_screen_cues.py --brief path/to/edit_brief.json --output custom.srt
"""

import argparse
import json
import sys
import os

# ---------------------------------------------------------------------------
# Constants (mirror constants.js SCREEN_TYPES)
# ---------------------------------------------------------------------------

SCREEN_TYPES = [
    'chapter_title', 'half_overlay', 'three_fifths_overlay',
    'lower_third', 'product_shot', 'list', 'info_graphic'
]

SCREEN_REQUIRED_FIELDS = {
    'chapter_title':        ['title'],
    'half_overlay':         ['title'],
    'three_fifths_overlay': ['title'],
    'lower_third':          ['title'],
    'product_shot':         ['title'],
    'list':                 ['title', 'body'],
    'info_graphic':         ['title', 'body'],
}

# Default cue display duration in SRT (seconds)
CUE_DISPLAY_DURATION = 3.0


# ---------------------------------------------------------------------------
# Timecode helpers (same as generate_assembly_captions.py)
# ---------------------------------------------------------------------------

def parse_timecode(tc_str: str) -> float:
    """Parse MM:SS.s or HH:MM:SS.s timecode string to seconds."""
    if isinstance(tc_str, (int, float)):
        return float(tc_str)
    tc_str = str(tc_str).strip().replace(",", ".")
    parts = tc_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            return float(tc_str) or 0.0
    except (ValueError, TypeError):
        return 0.0


def format_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp HH:MM:SS,mmm."""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    ms = int(round((s - int(s)) * 1000))
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


# ---------------------------------------------------------------------------
# Brief loading and segment sorting (mirrors assemblyBuilder.js)
# ---------------------------------------------------------------------------

def load_brief(brief_path: str) -> dict:
    """Load edit_brief.json and return parsed dict."""
    with open(brief_path, "r", encoding="utf-8") as f:
        return json.load(f)


def sort_assembly_segments(segments: list) -> list:
    """Filter use=TRUE + block!=99, sort by block ASC + brief order.

    Mirrors assemblyBuilder.js sortSegments() exactly.
    """
    use_segs = [
        s for s in segments
        if str(s.get("use", "FALSE")).upper() == "TRUE" and s.get("block", 99) != 99
    ]
    tagged = [(i, s) for i, s in enumerate(use_segs)]
    tagged.sort(key=lambda x: (x[1].get("block", 99), x[0]))
    return [s for _, s in tagged]


def build_segment_positions(sorted_segments: list) -> dict:
    """Build { segment_id: timeline_start_sec } from sorted Assembly segments.

    Same cumulative pattern as createAssemblyMarkers() in index.js.
    """
    positions = {}
    cum_time = 0.0
    for seg in sorted_segments:
        seg_id = seg.get("segment_id", "")
        tc_in = parse_timecode(seg.get("tc_in", "0"))
        tc_out = parse_timecode(seg.get("tc_out", "0"))
        duration = round(tc_out - tc_in, 1)
        if duration <= 0:
            duration = 0.1
        positions[seg_id] = cum_time
        cum_time = round(cum_time + duration, 1)
    return positions


# ---------------------------------------------------------------------------
# Screen cues parsing and SRT generation
# ---------------------------------------------------------------------------

def parse_screens(screens_raw: list, seg_map: dict) -> list:
    """Parse and validate screens[] from brief.

    Returns list of parsed screen dicts with resolved segment info.
    """
    parsed = []
    for i, raw in enumerate(screens_raw):
        if not isinstance(raw, dict):
            continue

        screen_id = raw.get("screen_id", f"scr_{i+1:03d}")
        screen_type = str(raw.get("type", "")).lower().strip()

        if screen_type not in SCREEN_TYPES:
            print(f"  WARN: {screen_id}: invalid type '{raw.get('type')}', skipped")
            continue

        segment_id = raw.get("segment_id", "")
        if segment_id not in seg_map:
            print(f"  WARN: {screen_id}: segment_id '{segment_id}' not found, skipped")
            continue

        # Check required fields
        required = SCREEN_REQUIRED_FIELDS.get(screen_type, ['title'])
        missing = [f for f in required if not str(raw.get(f, "")).strip()]
        if missing:
            print(f"  WARN: {screen_id}: missing [{', '.join(missing)}] for '{screen_type}', skipped")
            continue

        seg = seg_map[segment_id]
        tc_in_str = raw.get("tc_in") or seg.get("tc_in", "00:00.0")
        tc_in_sec = parse_timecode(tc_in_str)

        parsed.append({
            "id": screen_id,
            "type": screen_type,
            "segment_id": segment_id,
            "tc_in_sec": tc_in_sec,
            "seg_in_sec": parse_timecode(seg.get("tc_in", "0")),
            "seg_duration": round(
                parse_timecode(seg.get("tc_out", "0")) - parse_timecode(seg.get("tc_in", "0")), 1
            ),
            "title": str(raw.get("title", "")).strip()[:100],
            "subtitle": str(raw.get("subtitle", "")).strip()[:100],
            "body": str(raw.get("body", "")).strip()[:500],
        })

    return parsed


def format_screen_srt_text(screen: dict) -> str:
    """Format screen content for SRT subtitle entry."""
    lines = []
    type_label = "[" + screen["type"].upper().replace("_", " ") + "]"
    lines.append(type_label)
    if screen["title"]:
        lines.append(screen["title"])
    if screen["subtitle"]:
        lines.append(screen["subtitle"])
    if screen["body"]:
        lines.append(screen["body"].replace("\n", " | "))
    return "\n".join(lines)


def generate_screen_cues_srt(brief_path: str) -> tuple:
    """Generate Screen Cues SRT from edit_brief.json.

    Returns: (srt_string, stats_dict)
    """
    brief = load_brief(brief_path)
    segments = brief.get("segments", [])
    screens_raw = brief.get("screens", [])

    if not screens_raw:
        return "", {"screens_parsed": 0, "srt_blocks": 0, "skipped": 0}

    # Build segment lookup
    seg_map = {}
    for seg in segments:
        seg_id = seg.get("segment_id", "")
        if seg_id:
            seg_map[seg_id] = seg

    # Sort Assembly segments and build position map
    sorted_segs = sort_assembly_segments(segments)
    seg_positions = build_segment_positions(sorted_segs)

    # Parse screens
    parsed_screens = parse_screens(screens_raw, seg_map)

    # Generate SRT entries
    srt_blocks = []
    block_num = 0
    skipped = 0

    for screen in parsed_screens:
        seg_start = seg_positions.get(screen["segment_id"])
        if seg_start is None:
            # Segment not in Assembly (use=FALSE) → skip
            print(f"  WARN: {screen['id']}: segment '{screen['segment_id']}' not in Assembly timeline, skipped")
            skipped += 1
            continue

        # Calculate timeline position
        offset = screen["tc_in_sec"] - screen["seg_in_sec"]
        if offset < 0:
            offset = 0
        if offset > screen["seg_duration"]:
            offset = screen["seg_duration"]

        timeline_start = round(seg_start + offset, 3)
        timeline_end = round(timeline_start + CUE_DISPLAY_DURATION, 3)

        # Format SRT text
        srt_text = format_screen_srt_text(screen)

        block_num += 1
        srt_blocks.append(
            f"{block_num}\n"
            f"{format_srt_time(timeline_start)} --> {format_srt_time(timeline_end)}\n"
            f"{srt_text}\n"
        )

    srt_string = "\n".join(srt_blocks) + "\n" if srt_blocks else ""

    stats = {
        "screens_parsed": len(parsed_screens),
        "srt_blocks": block_num,
        "skipped": skipped,
    }

    return srt_string, stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Screen Cues SRT from edit brief (screens[] section)"
    )
    parser.add_argument(
        "--brief", required=True,
        help="Path to {project}_edit_brief.json"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output SRT path (default: auto-named next to brief)"
    )
    args = parser.parse_args()

    brief_path = os.path.abspath(args.brief)
    if not os.path.isfile(brief_path):
        print(f"ERROR: Brief file not found: {brief_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Screen Cues SRT Generator")
    print(f"  Brief: {brief_path}")

    # Generate SRT
    srt_string, stats = generate_screen_cues_srt(brief_path)

    if stats["screens_parsed"] == 0:
        print("\n  No screens[] found in brief — nothing to generate.")
        sys.exit(0)

    # Determine output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        brief = load_brief(brief_path)
        project_name = brief.get("project", {}).get("project_name", "YTAI")
        output_path = os.path.join(
            os.path.dirname(brief_path),
            f"{project_name}_4_ScreenCues_captions.srt"
        )

    # Write SRT
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_string)

    # Summary
    print(f"\nScreen Cues Summary:")
    print(f"  Screens parsed: {stats['screens_parsed']}")
    if stats["skipped"]:
        print(f"  Skipped (not in Assembly): {stats['skipped']}")
    print(f"  SRT blocks: {stats['srt_blocks']}")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
