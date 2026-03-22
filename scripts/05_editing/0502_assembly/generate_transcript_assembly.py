#!/usr/bin/env python3
"""Generate a compact transcript for Claude Desktop Assembly workflow.

Reads the full {project}_transcript.json and strips heavy data (words_data,
media metadata, file paths, empty clips) to produce a lightweight
{project}_transcript_assembly.json suitable for Claude Desktop Project Knowledge.

Typical compression: 5.1MB → ~326KB (16× reduction).

Usage:
    python generate_transcript_assembly.py <transcript.json> [--output <path>]
"""
import argparse
import json
import sys
from pathlib import Path


def fmt_duration(seconds: float) -> str:
    """Format seconds as M:SS.s for segments or H:MM:SS for totals."""
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def fmt_total_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def generate_assembly_transcript(data: dict) -> dict:
    """Strip heavy fields, keep what Claude Desktop needs for editing decisions."""
    # Speakers — names only
    speakers = []
    speaker_names = {}
    for sp_id, sp_info in data.get("speakers", {}).items():
        name = sp_info.get("name", sp_id) if isinstance(sp_info, dict) else sp_id
        speakers.append(name)
        speaker_names[sp_id] = name

    # Scenes (nested projects)
    scenes = data.get("structure", {}).get("scenes", [])

    # Stats
    stats = data.get("stats", {})
    total_dur = stats.get("total_duration", 0)

    compact = {
        "project": data.get("project", ""),
        "language": data.get("language", ""),
        "total_duration": fmt_total_duration(total_dur),
        "total_words": stats.get("total_words", 0),
        "total_segments": stats.get("total_segments", 0),
        "speakers": speakers,
    }
    if scenes:
        compact["scenes"] = scenes

    # Clips — skip empty, strip media/files/words
    clips_out = []
    for clip in data.get("clips", []):
        segments = clip.get("segments", [])
        if not segments:
            continue

        # Get fps from media (needed for brief generation)
        media = clip.get("media", {})
        fps = media.get("fps")

        clip_out = {
            "clip_id": clip["clip_id"],
            "filename": clip["filename"],
            "duration": fmt_duration(clip.get("duration", 0)),
        }
        if fps:
            clip_out["fps"] = fps
        if clip.get("scene"):
            clip_out["scene"] = clip["scene"]

        segs_out = []
        for seg in segments:
            # Resolve speaker name
            sp = seg.get("speaker", seg.get("speaker_id", ""))
            sp_name = speaker_names.get(sp, sp)

            seg_out = {
                "start": fmt_duration(seg.get("start", 0)),
                "end": fmt_duration(seg.get("end", 0)),
                "speaker": sp_name,
                "text": seg.get("text", ""),
            }

            # Flag low confidence
            conf = seg.get("confidence", seg.get("avg_confidence", 1.0))
            if conf < 0.7:
                seg_out["low_conf"] = True

            segs_out.append(seg_out)

        clip_out["segments"] = segs_out
        clips_out.append(clip_out)

    compact["clips"] = clips_out
    return compact


def main():
    parser = argparse.ArgumentParser(
        description="Generate compact transcript for Assembly workflow"
    )
    parser.add_argument("transcript", type=Path, help="Path to full transcript JSON")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output path (default: {dir}/{project}_transcript_assembly.json)")
    args = parser.parse_args()

    if not args.transcript.exists():
        print(f"Error: {args.transcript} not found", file=sys.stderr)
        sys.exit(1)

    with open(args.transcript, encoding="utf-8") as f:
        data = json.load(f)

    compact = generate_assembly_transcript(data)

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        project = data.get("project", args.transcript.stem)
        # Use project code (YTXX01) not full name
        import re
        _m = re.match(r'^(YT[A-Z]{2,4}\d+)_', project)
        code = _m.group(1) if _m else project
        # Output to Setup/ if available
        setup = args.transcript.parent.parent / "Setup"
        parent = setup if setup.is_dir() else args.transcript.parent
        out_path = parent / f"{code}_Claude4_assembly.json"

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(compact, f, indent=2, ensure_ascii=False)

    # Report
    in_size = args.transcript.stat().st_size
    out_size = out_path.stat().st_size
    ratio = in_size / out_size if out_size > 0 else 0
    n_clips = len(compact["clips"])
    n_segs = sum(len(c["segments"]) for c in compact["clips"])

    print(f"Input:    {args.transcript.name} ({in_size / 1024:.0f}KB)")
    print(f"Output:   {out_path.name} ({out_size / 1024:.0f}KB)")
    print(f"Ratio:    {ratio:.1f}x compression")
    print(f"Clips:    {n_clips} (with speech)")
    print(f"Segments: {n_segs}")
    print(f"Saved to: {out_path}")


if __name__ == "__main__":
    main()
