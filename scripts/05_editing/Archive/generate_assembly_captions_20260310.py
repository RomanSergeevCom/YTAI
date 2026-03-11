#!/usr/bin/env python3
"""
YTAI Stage 05: Generate Assembly / Review Captions SRT

Reads edit_brief.json + per-clip transcript JSONs (word-level timing)
and generates timeline-accurate SRT captions:
  - Assembly: {project}_2_Assembly_captions.srt (used segments)
  - Review:   {project}_3_Review_captions.srt   (unused segments)

Algorithm mirrors assemblyBuilder.js / reviewBuilder.js:
  Assembly: Filter use=TRUE + block!=99, sort by block ASC + brief order
  Review:   Complement approach (Ingest minus Assembly) + brief merge
  Both:     Cumulative position on timeline with round(cumulative + duration, 1)

Usage:
    python generate_assembly_captions.py --brief YTAI_Edit_edit_brief.json
    python generate_assembly_captions.py --brief path/to/edit_brief.json --review
    python generate_assembly_captions.py --brief path/to/edit_brief.json --words-per-block 4
"""

import argparse
import json
import sys
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Timecode helpers
# ---------------------------------------------------------------------------

def parse_timecode(tc_str: str) -> float:
    """Parse MM:SS.s or HH:MM:SS.s timecode string to seconds.

    Mirrors briefParser.js parseTimecode() exactly.
    """
    if isinstance(tc_str, (int, float)):
        return float(tc_str)
    tc_str = str(tc_str).strip().replace(",", ".")
    parts = tc_str.split(":")
    try:
        if len(parts) == 2:          # MM:SS.s
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:        # HH:MM:SS.s
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
# Brief loading and segment sorting
# ---------------------------------------------------------------------------

def load_brief(brief_path: str) -> dict:
    """Load edit_brief.json and return parsed dict."""
    with open(brief_path, "r", encoding="utf-8") as f:
        return json.load(f)


def sort_segments(segments: list) -> list:
    """Filter use=TRUE + block!=99, sort by block ASC + brief order.

    Mirrors assemblyBuilder.js sortSegments() exactly:
    - block 99 always excluded (along with use=FALSE)
    - sort by block number ascending
    - within same block: preserve original JSON array order (_brief_idx)
    """
    # Tag with brief index for stable sort
    for i, seg in enumerate(segments):
        seg["_brief_idx"] = i

    use_segs = [
        s for s in segments
        if s.get("use", "FALSE").upper() == "TRUE" and s.get("block", 99) != 99
    ]

    use_segs.sort(key=lambda s: (s["block"], s["_brief_idx"]))
    return use_segs


def compute_complement(assembly_ranges: list, clip_duration: float, min_gap: float = 0.3) -> list:
    """Compute complement of assembly ranges within [0, clip_duration].

    Returns ranges NOT covered by assembly. Skips gaps < min_gap.
    Mirrors reviewBuilder.js computeComplement().
    """
    complement = []
    pos = 0.0
    for r in assembly_ranges:
        if r["in"] > pos:
            gap_dur = r["in"] - pos
            if gap_dur >= min_gap:
                complement.append({"in": pos, "out": r["in"]})
        if r["out"] > pos:
            pos = r["out"]
    if clip_duration > pos:
        tail_dur = clip_duration - pos
        if tail_dur >= min_gap:
            complement.append({"in": pos, "out": clip_duration})
    return complement


def subtract_brief_from_range(comp_range: dict, brief_segs: list) -> list:
    """Subtract brief segments from a complement range, returning uncovered gaps.

    Mirrors reviewBuilder.js subtractBriefFromRange().
    """
    # Collect overlapping brief ranges, clamped to comp_range
    cuts = []
    for bs in brief_segs:
        b_in = parse_timecode(bs.get("tc_in", "0"))
        b_out = parse_timecode(bs.get("tc_out", "0"))
        c_in = max(b_in, comp_range["in"])
        c_out = min(b_out, comp_range["out"])
        if c_in < c_out:
            cuts.append({"in": c_in, "out": c_out})
    cuts.sort(key=lambda c: c["in"])

    # Walk through and collect uncovered parts
    gaps = []
    pos = comp_range["in"]
    for c in cuts:
        if c["in"] > pos:
            gaps.append({"in": pos, "out": c["in"]})
        if c["out"] > pos:
            pos = c["out"]
    if comp_range["out"] > pos:
        gaps.append({"in": pos, "out": comp_range["out"]})
    return gaps


def sec_to_tc(seconds: float) -> str:
    """Convert seconds to MM:SS.s format."""
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:04.1f}"


def load_clip_duration(per_clip_dir: Path, clip_id: str) -> float:
    """Load clip duration from per-clip transcript JSON.

    Falls back to 0.0 if not found.
    """
    transcript_path = per_clip_dir / clip_id / f"{clip_id}_transcript.json"
    if not transcript_path.is_file():
        return 0.0
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return float(data.get("duration", 0.0))
    except (json.JSONDecodeError, ValueError):
        return 0.0


def get_clip_durations_from_brief(segments: list) -> dict:
    """Fallback: compute clip durations as max(out_sec) per source_file."""
    durations = {}
    for s in segments:
        f = s.get("source_file", "")
        out = parse_timecode(s.get("tc_out", "0"))
        if f and out > durations.get(f, 0):
            durations[f] = out
    return durations


def sort_review_segments(segments: list, clip_durations: dict = None) -> list:
    """Build review segments using complement approach (Ingest minus Assembly).

    When clip_durations is provided:
    - Computes complement of assembly ranges per clip
    - Merges with existing use=FALSE brief segments
    - Creates gap segments for uncovered complement areas

    Falls back to old filter when clip_durations is None.
    Mirrors reviewBuilder.js sortReviewSegments().
    """
    if not clip_durations:
        # Fallback: old filter approach
        review_segs = [
            s for s in segments
            if s.get("use", "FALSE").upper() != "TRUE" or s.get("block", 0) == 99
        ]
        review_segs.sort(key=lambda s: (
            s.get("source_file", ""),
            parse_timecode(s.get("tc_in", "0"))
        ))
        return review_segs

    # Collect assembly ranges and brief segments per clip
    assembly_by_clip = {}
    brief_by_clip = {}
    min_gap = 0.3

    for s in segments:
        f = s.get("source_file", "")
        if not f:
            continue
        in_sec = parse_timecode(s.get("tc_in", "0"))
        out_sec = parse_timecode(s.get("tc_out", "0"))
        is_use = s.get("use", "FALSE").upper() == "TRUE"
        block = s.get("block", 0)

        if is_use and block != 99:
            assembly_by_clip.setdefault(f, []).append({"in": in_sec, "out": out_sec})
        else:
            brief_by_clip.setdefault(f, []).append(s)

    result = []

    for source_file, clip_dur in sorted(clip_durations.items()):
        # Get assembly ranges sorted by in
        asm_ranges = sorted(assembly_by_clip.get(source_file, []), key=lambda r: r["in"])
        # Compute complement
        complement = compute_complement(asm_ranges, clip_dur, min_gap)
        # Get brief segments for this clip
        brief_segs = brief_by_clip.get(source_file, [])

        for comp_range in complement:
            # Find overlapping brief segments
            overlapping = []
            for bs in brief_segs:
                b_in = parse_timecode(bs.get("tc_in", "0"))
                b_out = parse_timecode(bs.get("tc_out", "0"))
                if b_in < comp_range["out"] and b_out > comp_range["in"]:
                    overlapping.append(bs)

            # Add overlapping brief segments
            for bs in overlapping:
                result.append(bs)

            # Compute gap ranges not covered by brief
            gap_ranges = subtract_brief_from_range(comp_range, overlapping)
            for gap in gap_ranges:
                gap_dur = round(gap["out"] - gap["in"], 1)
                if gap_dur < min_gap:
                    continue
                clip_id = os.path.splitext(source_file)[0]
                result.append({
                    "segment_id": f"gap_{clip_id}_{gap['in']:.1f}",
                    "source_file": source_file,
                    "tc_in": sec_to_tc(gap["in"]),
                    "tc_out": sec_to_tc(gap["out"]),
                    "block": 0,
                    "block_name": "",
                    "use": "FALSE",
                    "speaker": "",
                    "transcript": "",
                    "priority": 1,
                    "color": "Purple",
                    "_is_gap": True,
                })

    # Sort by source_file then tc_in
    result.sort(key=lambda s: (
        s.get("source_file", ""),
        parse_timecode(s.get("tc_in", "0"))
    ))
    return result


# ---------------------------------------------------------------------------
# Per-clip transcript loading
# ---------------------------------------------------------------------------

def find_per_clip_dir(brief_path: str, transcription_dir: str, project_name: str) -> Path:
    """Locate the per_clip directory.

    Search order:
    1. {brief_dir}/{transcription_dir}/per_clip/
    2. {brief_dir}/../{transcription_dir}/per_clip/  (one level up)
    3. Walk up to find 02_transcribe/{project_name}/{transcription_dir}/per_clip/
    """
    brief_dir = Path(brief_path).parent

    # Option 1: sibling of brief
    candidate = brief_dir / transcription_dir / "per_clip"
    if candidate.is_dir():
        return candidate

    # Option 2: one level up (brief is in project subfolder)
    candidate = brief_dir.parent / transcription_dir / "per_clip"
    if candidate.is_dir():
        return candidate

    # Option 3: walk up looking for standard YTAI structure
    search = brief_dir
    for _ in range(6):  # max 6 levels up
        search = search.parent
        candidate = search / "scripts" / "02_transcribe" / project_name / transcription_dir / "per_clip"
        if candidate.is_dir():
            return candidate

    # Fallback: try with default transcription_dir name
    if not transcription_dir:
        fallback_dir = f"{project_name}_transcription"
        return find_per_clip_dir(brief_path, fallback_dir, project_name)

    return None


def load_clip_words(per_clip_dir: Path, clip_id: str) -> list:
    """Load all words from per-clip transcript JSON.

    Collects words from ALL segments in the clip transcript,
    returns flat list sorted by word start time.
    """
    transcript_path = per_clip_dir / clip_id / f"{clip_id}_transcript.json"
    if not transcript_path.is_file():
        return []

    with open(transcript_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    all_words = []
    for segment in data.get("segments", []):
        for word in segment.get("words", []):
            if "start" in word and "end" in word and "word" in word:
                all_words.append(word)

    # Sort by start time (should already be sorted, but ensure)
    all_words.sort(key=lambda w: w["start"])
    return all_words


def extract_words_in_range(all_words: list, in_sec: float, out_sec: float) -> list:
    """Filter words whose start falls within [in_sec, out_sec).

    A word is included if its start time >= in_sec and start time < out_sec.
    This ensures words that begin within the segment range are captured,
    even if their end slightly exceeds out_sec.
    """
    return [
        w for w in all_words
        if w["start"] >= in_sec and w["start"] < out_sec
    ]


# ---------------------------------------------------------------------------
# SRT generation
# ---------------------------------------------------------------------------

def group_words_to_blocks(words: list, words_per_block: int = 6) -> list:
    """Group remapped words into SRT subtitle blocks.

    Each block contains up to words_per_block words, split into 2 lines.
    Returns list of dicts: {start, end, lines: [line1, line2]}
    """
    blocks = []
    for i in range(0, len(words), words_per_block):
        chunk = words[i:i + words_per_block]
        if not chunk:
            continue

        start = chunk[0]["assembly_start"]
        end = chunk[-1]["assembly_end"]

        # Split into 2 roughly equal lines
        mid = len(chunk) // 2
        if mid == 0:
            mid = len(chunk)

        line1 = " ".join(w["word"] for w in chunk[:mid])
        line2 = " ".join(w["word"] for w in chunk[mid:]) if mid < len(chunk) else ""

        lines = [line1]
        if line2:
            lines.append(line2)

        blocks.append({
            "start": start,
            "end": end,
            "lines": lines,
        })

    return blocks


def generate_captions_srt(brief_path: str, words_per_block: int = 6, mode: str = "assembly") -> tuple:
    """Main function: generate SRT from edit brief + clip transcripts.

    mode="assembly": use=TRUE + block!=99, sorted by block (Assembly timeline)
    mode="review":   use=FALSE OR block=99, sorted by source_file + tc_in (Review timeline)

    Returns (srt_string, stats_dict).
    """
    # Load brief
    brief = load_brief(brief_path)
    segments = brief.get("segments", [])
    project = brief.get("project", {})
    project_name = project.get("project_name", "YTAI")
    transcription_dir = project.get("_transcription_dir", "")

    if not transcription_dir:
        transcription_dir = f"{project_name}_transcription"

    # Find per_clip directory
    per_clip_dir = find_per_clip_dir(brief_path, transcription_dir, project_name)
    if per_clip_dir is None or not per_clip_dir.is_dir():
        print(f"ERROR: Could not find per_clip directory for '{transcription_dir}'", file=sys.stderr)
        print(f"  Searched from: {Path(brief_path).parent}", file=sys.stderr)
        sys.exit(1)

    print(f"  Transcripts: {per_clip_dir}")

    # Filter and sort segments based on mode
    if mode == "review":
        # Try to load clip durations from per-clip transcripts
        clip_durations = {}
        if per_clip_dir and per_clip_dir.is_dir():
            for seg in segments:
                sf = seg.get("source_file", "")
                if sf and sf not in clip_durations:
                    cid = os.path.splitext(sf)[0]
                    dur = load_clip_duration(per_clip_dir, cid)
                    if dur > 0:
                        clip_durations[sf] = dur
        if not clip_durations:
            clip_durations = get_clip_durations_from_brief(segments)
            print("  WARNING: Using brief-based clip durations (no per-clip transcripts)", file=sys.stderr)
        use_segs = sort_review_segments(segments, clip_durations)
        print(f"  Review segments: {len(use_segs)} (of {len(segments)} total)")
    else:
        use_segs = sort_segments(segments)
        print(f"  Assembly segments: {len(use_segs)} (of {len(segments)} total)")

    # Cache loaded clip words to avoid re-reading same file
    clip_words_cache = {}

    # For Review mode: compute clip offsets for absolute positioning (Ingest layout)
    clip_offsets = {}
    if mode == "review" and clip_durations:
        offset = 0.0
        for clip_name in sorted(clip_durations.keys()):
            clip_offsets[clip_name] = offset
            offset += clip_durations[clip_name]

    # Process segments — Assembly: cumulative, Review: absolute (Ingest layout)
    all_srt_blocks = []
    cumulative = 0.0
    stats = {
        "segments_processed": 0,
        "segments_skipped": 0,
        "words_mapped": 0,
        "clips_loaded": set(),
    }

    for seg in use_segs:
        source_file = seg.get("source_file", "")
        clip_id = os.path.splitext(source_file)[0]  # C5403.MP4 -> C5403
        in_sec = parse_timecode(seg.get("tc_in", "0"))
        out_sec = parse_timecode(seg.get("tc_out", "0"))
        duration = max(0.0, out_sec - in_sec)
        seg_id = seg.get("segment_id", "?")

        # Calculate timeline position based on mode
        if mode == "review" and clip_offsets:
            # Absolute position: clip offset + source timecode (Ingest layout)
            timeline_start = clip_offsets.get(source_file, 0.0) + in_sec
        else:
            # Sequential (Assembly)
            timeline_start = cumulative

        # Load clip words (cached)
        if clip_id not in clip_words_cache:
            clip_words_cache[clip_id] = load_clip_words(per_clip_dir, clip_id)
            if clip_words_cache[clip_id]:
                stats["clips_loaded"].add(clip_id)
            else:
                print(f"  WARNING: No transcript for {clip_id} — {seg_id} will have no captions", file=sys.stderr)

        clip_words = clip_words_cache[clip_id]

        # Extract words in tc_in..tc_out range
        seg_words = extract_words_in_range(clip_words, in_sec, out_sec)

        if not seg_words:
            print(f"  WARNING: No words in range {seg.get('tc_in')}..{seg.get('tc_out')} for {seg_id} ({clip_id})", file=sys.stderr)
            stats["segments_skipped"] += 1
        else:
            stats["segments_processed"] += 1
            stats["words_mapped"] += len(seg_words)

        # Remap word timecodes to timeline
        remapped_words = []
        for w in seg_words:
            remapped_words.append({
                "word": w["word"],
                "assembly_start": timeline_start + (w["start"] - in_sec),
                "assembly_end": timeline_start + (w["end"] - in_sec),
            })

        # Group THIS segment's words into SRT blocks (respects segment boundaries)
        seg_blocks = group_words_to_blocks(remapped_words, words_per_block)
        all_srt_blocks.extend(seg_blocks)

        # Advance cumulative position (Assembly mode only)
        cumulative = round(cumulative + duration, 1)

    # Timeline duration: Review = Ingest total, Assembly = cumulative
    if mode == "review" and clip_offsets:
        stats["timeline_duration"] = sum(clip_durations.values())
    else:
        stats["timeline_duration"] = cumulative
    stats["srt_blocks"] = len(all_srt_blocks)
    srt_blocks = all_srt_blocks

    # Format SRT
    srt_lines = []
    for idx, block in enumerate(srt_blocks, start=1):
        srt_lines.append(str(idx))
        srt_lines.append(f"{format_srt_time(block['start'])} --> {format_srt_time(block['end'])}")
        for line in block["lines"]:
            srt_lines.append(line)
        srt_lines.append("")  # blank line between blocks

    srt_string = "\n".join(srt_lines)
    return srt_string, stats


def generate_assembly_srt(brief_path: str, words_per_block: int = 6) -> tuple:
    """Generate Assembly SRT. Backward-compatible wrapper."""
    return generate_captions_srt(brief_path, words_per_block, mode="assembly")


def generate_review_srt(brief_path: str, words_per_block: int = 6) -> tuple:
    """Generate Review SRT."""
    return generate_captions_srt(brief_path, words_per_block, mode="review")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Assembly or Review captions SRT from edit brief + per-clip transcripts"
    )
    parser.add_argument(
        "--brief", required=True,
        help="Path to {project}_edit_brief.json"
    )
    parser.add_argument(
        "--words-per-block", type=int, default=6,
        help="Words per SRT subtitle block (default: 6)"
    )
    parser.add_argument(
        "--output", default=None,
        help="Output SRT path (default: auto-named next to brief)"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Generate Review captions (unused segments) instead of Assembly"
    )
    args = parser.parse_args()

    brief_path = os.path.abspath(args.brief)
    if not os.path.isfile(brief_path):
        print(f"ERROR: Brief file not found: {brief_path}", file=sys.stderr)
        sys.exit(1)

    mode = "review" if args.review else "assembly"
    mode_label = "Review" if args.review else "Assembly"
    print(f"{mode_label} Captions Generator")
    print(f"  Brief: {brief_path}")

    # Generate SRT
    srt_string, stats = generate_captions_srt(brief_path, args.words_per_block, mode=mode)

    # Determine output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        brief = load_brief(brief_path)
        project_name = brief.get("project", {}).get("project_name", "YTAI")
        suffix = "3_Review" if args.review else "2_Assembly"
        output_path = os.path.join(
            os.path.dirname(brief_path),
            f"{project_name}_{suffix}_captions.srt"
        )

    # Write SRT
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_string)

    # Summary
    print(f"\n{mode_label} Captions Summary:")
    print(f"  Segments processed: {stats['segments_processed']}")
    if stats["segments_skipped"]:
        print(f"  Segments skipped (no words): {stats['segments_skipped']}")
    print(f"  Clips loaded: {len(stats['clips_loaded'])} ({', '.join(sorted(stats['clips_loaded']))})")
    print(f"  Words mapped: {stats['words_mapped']}")
    print(f"  SRT blocks: {stats['srt_blocks']}")
    print(f"  Timeline duration: {stats['timeline_duration']:.1f}s")
    print(f"  Output: {output_path}")


if __name__ == "__main__":
    main()
