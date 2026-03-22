#!/usr/bin/env python3
"""
snap_to_words.py — Snap brief tc_in/tc_out to word boundaries.

Reads pre_edit_brief.json + {project}_transcript.json, and for each segment
adjusts tc_in/tc_out so they don't cut words mid-pronunciation. Whole
sentences can still be excluded — this only prevents partial word clipping.

Usage:
    python snap_to_words.py --brief Setup/YTCR01_pre_edit_brief.json \
                            --transcript Transcription/YTCR01_Arty_Dzis_transcript.json

Writes updated brief in-place (backs up original to _pre_snap.json).
"""
import argparse
import json
import shutil
import sys
from pathlib import Path


SNAP_TOLERANCE = 0.5   # tc_in: only snap if adjustment < 0.5s
ALREADY_OK = 0.05      # Consider already aligned if within 50ms
# tc_out has NO tolerance cap — we always extend to include the full last word,
# because clipping a spoken word is worse than adding a few extra seconds.


def parse_timecode(tc_str: str) -> float:
    """Parse MM:SS.s or HH:MM:SS.s to seconds."""
    tc_str = str(tc_str).strip().replace(",", ".")
    parts = tc_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(tc_str) or 0.0
    except (ValueError, TypeError):
        return 0.0


def format_timecode(seconds: float) -> str:
    """Format seconds to MM:SS.s (one decimal)."""
    m = int(seconds) // 60
    s = seconds % 60
    return f"{m:02d}:{s:04.1f}"


def build_words_lookup(transcript: dict) -> dict:
    """Build {filename: [words]} from transcript.json.

    Each word: {start, end, word}.
    """
    lookup = {}
    for clip in transcript.get("clips", []):
        fname = clip.get("filename", "")
        words = []
        for seg in clip.get("segments", []):
            for w in seg.get("words_data", []):
                words.append({
                    "start": w.get("start", 0),
                    "end": w.get("end", 0),
                    "word": w.get("word", ""),
                })
        words.sort(key=lambda w: w["start"])
        lookup[fname] = words
    return lookup


def snap_segment(seg: dict, words: list) -> dict:
    """Snap tc_in/tc_out to word boundaries without clipping spoken words.

    tc_in  → start of the first word that ends AFTER tc_in (never cut intro)
    tc_out → end   of the last  word that starts BEFORE tc_out (never cut tail)

    Returns dict with snapped values and log info, or None if no change.
    """
    tc_in = parse_timecode(seg.get("tc_in", "0"))
    tc_out = parse_timecode(seg.get("tc_out", "0"))

    if not words or tc_in >= tc_out:
        return None

    # tc_in: find the word being spoken at tc_in (if any) → snap to its start
    # If tc_in is in silence, find the next word → snap with tolerance
    word_at_in = None
    next_word_after_in = None
    for w in words:
        if w["start"] <= tc_in < w["end"]:
            word_at_in = w
            break
        if w["start"] > tc_in and next_word_after_in is None:
            next_word_after_in = w

    # tc_out: find the word being spoken at tc_out (if any) → snap to its end
    # If tc_out is in silence, find the previous word → snap with tolerance
    word_at_out = None
    prev_word_before_out = None
    for w in words:
        if w["start"] < tc_out:
            prev_word_before_out = w
        if w["start"] <= tc_out < w["end"]:
            word_at_out = w

    changes = {}

    # tc_in logic: if cutting a word mid-pronunciation, ALWAYS fix (no tolerance cap)
    # if in silence, snap to next word start within SNAP_TOLERANCE
    if word_at_in:
        # Cutting a word — always extend back to include full word
        delta = abs(word_at_in["start"] - tc_in)
        if delta > ALREADY_OK:
            changes["tc_in"] = format_timecode(word_at_in["start"])
            changes["tc_in_word"] = word_at_in["word"]
            changes["tc_in_delta"] = round(word_at_in["start"] - tc_in, 3)
    elif next_word_after_in:
        # In silence — snap forward to next word start (with tolerance)
        delta = abs(next_word_after_in["start"] - tc_in)
        if delta > ALREADY_OK and delta < SNAP_TOLERANCE:
            changes["tc_in"] = format_timecode(next_word_after_in["start"])
            changes["tc_in_word"] = next_word_after_in["word"]
            changes["tc_in_delta"] = round(next_word_after_in["start"] - tc_in, 3)

    # tc_out logic: if cutting a word mid-pronunciation, ALWAYS fix (no tolerance cap)
    # if in silence, snap to previous word end within SNAP_TOLERANCE
    if word_at_out:
        # Cutting a word — always extend forward to include full word
        delta = abs(word_at_out["end"] - tc_out)
        if delta > ALREADY_OK:
            changes["tc_out"] = format_timecode(word_at_out["end"])
            changes["tc_out_word"] = word_at_out["word"]
            changes["tc_out_delta"] = round(word_at_out["end"] - tc_out, 3)
    elif prev_word_before_out:
        # In silence — snap back to previous word end (with tolerance)
        delta = abs(prev_word_before_out["end"] - tc_out)
        if delta > ALREADY_OK and delta < SNAP_TOLERANCE:
            changes["tc_out"] = format_timecode(prev_word_before_out["end"])
            changes["tc_out_word"] = prev_word_before_out["word"]
            changes["tc_out_delta"] = round(prev_word_before_out["end"] - tc_out, 3)

    return changes if changes else None


def snap_brief(brief: dict, transcript: dict) -> tuple:
    """Snap all segments in brief to word boundaries.

    Returns (updated_brief, adjustments_log).
    """
    words_lookup = build_words_lookup(transcript)
    adjustments = []

    for seg in brief.get("segments", []):
        source = seg.get("source_file", "")
        words = words_lookup.get(source, [])
        if not words:
            continue

        changes = snap_segment(seg, words)
        if changes:
            seg_id = seg.get("segment_id", "?")
            log = f"{seg_id} ({source}): "
            parts = []
            if "tc_in" in changes:
                old_tc = seg["tc_in"]
                seg["tc_in"] = changes["tc_in"]
                parts.append(f"tc_in {old_tc} → {changes['tc_in']} ('{changes['tc_in_word']}', {changes['tc_in_delta']:+.3f}s)")
            if "tc_out" in changes:
                old_tc = seg["tc_out"]
                seg["tc_out"] = changes["tc_out"]
                parts.append(f"tc_out {old_tc} → {changes['tc_out']} ('{changes['tc_out_word']}', {changes['tc_out_delta']:+.3f}s)")
            log += " | ".join(parts)
            adjustments.append(log)

    return brief, adjustments


def main():
    ap = argparse.ArgumentParser(description="Snap brief tc_in/tc_out to word boundaries")
    ap.add_argument("--brief", required=True, type=Path, help="Path to pre_edit_brief.json")
    ap.add_argument("--transcript", required=True, type=Path, help="Path to {project}_transcript.json")
    ap.add_argument("--dry-run", action="store_true", help="Show adjustments without modifying brief")
    args = ap.parse_args()

    if not args.brief.exists():
        print(f"Error: brief not found: {args.brief}", file=sys.stderr)
        sys.exit(1)
    if not args.transcript.exists():
        print(f"Error: transcript not found: {args.transcript}", file=sys.stderr)
        sys.exit(1)

    with open(args.brief) as f:
        brief = json.load(f)
    with open(args.transcript) as f:
        transcript = json.load(f)

    updated_brief, adjustments = snap_brief(brief, transcript)

    if not adjustments:
        print("No adjustments needed — all timecodes already on word boundaries.")
        return

    print(f"Adjustments ({len(adjustments)}):")
    for a in adjustments:
        print(f"  {a}")

    if args.dry_run:
        print(f"\n[dry-run] Would update {len(adjustments)} timecodes in {args.brief.name}")
        return

    # Backup original
    backup = args.brief.with_name(args.brief.stem + "_pre_snap.json")
    shutil.copy2(args.brief, backup)
    print(f"\nBackup: {backup.name}")

    # Write updated brief
    with open(args.brief, "w") as f:
        json.dump(updated_brief, f, indent=2, ensure_ascii=False)
    print(f"Updated: {args.brief.name} ({len(adjustments)} timecodes snapped)")


if __name__ == "__main__":
    main()
