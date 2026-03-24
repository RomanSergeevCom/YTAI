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
import numpy as np

SCRIPT_VERSION = "1.2.0"  # v1.2.0: 3-decimal precision (frame-exact at 29.97fps) + calibration


def fmt_duration(seconds: float) -> str:
    """Format seconds as M:SS.sss (1ms precision, frame-exact at 29.97fps)."""
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"


def fmt_total_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}:{m:02d}:{s:02d}"


def _find_onset(audio, sr, start_s, end_s, threshold_ratio=0.20, window_ms=20,
                 sustain_windows=3, gap_windows=3):
    """Find actual speech energy onset within a time range.

    Gap-aware: if there's a silence gap inside the word range (e.g. tail of
    previous word + gap + real word), returns onset AFTER the last gap.
    This prevents capturing tails of slurred previous words.

    Algorithm:
    1. Compute RMS in windows across the range
    2. Find all silence gaps (gap_windows consecutive below threshold)
    3. If gaps found: search for onset AFTER the last gap
    4. If no gaps: search from the beginning (original behavior)
    """
    window = int(window_ms * sr / 1000)
    s = max(0, int(start_s * sr))
    e = min(len(audio), int(end_s * sr))
    chunk = audio[s:e]
    if len(chunk) < window:
        return start_s

    max_rms = 0.0
    energies = []
    for i in range(0, len(chunk) - window, window):
        rms = float(np.sqrt(np.mean(chunk[i:i + window] ** 2)))
        t = start_s + i / sr
        energies.append((t, rms))
        if rms > max_rms:
            max_rms = rms

    if max_rms < 1e-6:
        return start_s

    threshold = max_rms * threshold_ratio

    # Find last silence gap (gap_windows consecutive below threshold)
    last_gap_end = 0  # index after the last gap
    silent_run = 0
    for idx, (t, rms) in enumerate(energies):
        if rms <= threshold:
            silent_run += 1
            if silent_run >= gap_windows:
                last_gap_end = idx + 1  # search after this gap
        else:
            silent_run = 0

    # Search for sustained onset starting after the last gap
    search_start = last_gap_end
    run = 0
    for idx in range(search_start, len(energies)):
        t, rms = energies[idx]
        if rms > threshold:
            run += 1
            if run >= sustain_windows:
                onset_idx = idx - sustain_windows + 1
                return round(energies[onset_idx][0], 3)
        else:
            run = 0

    return start_s


def _find_offset(audio, sr, start_s, end_s, threshold_ratio=0.15, window_ms=20):
    """Find actual speech energy offset (end) within a time range."""
    window = int(window_ms * sr / 1000)
    s = max(0, int(start_s * sr))
    e = min(len(audio), int(end_s * sr))
    chunk = audio[s:e]
    if len(chunk) < window:
        return end_s

    max_rms = 0.0
    energies = []
    for i in range(0, len(chunk) - window, window):
        rms = float(np.sqrt(np.mean(chunk[i:i + window] ** 2)))
        t = start_s + i / sr
        energies.append((t, rms))
        if rms > max_rms:
            max_rms = rms

    if max_rms < 1e-6:
        return end_s

    threshold = max_rms * threshold_ratio
    # Walk backwards to find last energy above threshold
    for t, rms in reversed(energies):
        if rms > threshold:
            return round(t + window_ms / 1000, 3)  # end of last active window
    return end_s


def calibrate_word_timestamps(data: dict, transcript_path: Path):
    """Calibrate word timestamps using audio energy analysis.

    For each word in words_data, check if Whisper's start/end matches
    actual speech energy. Shift to real onset/offset when they differ.
    Modifies data in-place.
    """
    try:
        import soundfile as sf
    except ImportError:
        print("  soundfile not available — skipping calibration", file=sys.stderr)
        return 0

    transcription_dir = transcript_path.parent
    total_calibrated = 0

    for clip in data.get("clips", []):
        clip_id = clip.get("clip_id", "")
        wav_path = transcription_dir / "per_clip" / clip_id / f"{clip_id}_audio.wav"
        if not wav_path.exists():
            continue

        audio, sr = sf.read(str(wav_path))
        if audio.ndim > 1:
            audio = audio[:, 0]  # mono

        for seg in clip.get("segments", []):
            words = seg.get("words_data", [])
            if not words:
                continue

            for w in words:
                ws = w.get("start", 0)
                we = w.get("end", 0)
                dur = we - ws

                # Skip short words (< 0.3s) — Whisper is precise enough
                if dur < 0.3:
                    continue

                # Calibrate onset only — offset stays as Whisper assigned
                # (offset calibration can over-trim words)
                onset = _find_onset(audio, sr, ws, we)
                if onset > ws + 0.05:  # significant shift
                    w["start"] = onset
                    total_calibrated += 1

    return total_calibrated


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

            # Word-level timestamps (compact: w/s/e)
            words_data = seg.get("words_data", [])
            if words_data:
                seg_out["words"] = [
                    {"w": w["word"], "s": fmt_duration(w["start"]), "e": fmt_duration(w["end"])}
                    for w in words_data
                    if "start" in w and "end" in w and w.get("word", "").strip()
                ]

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

    print(f"Script:   generate_transcript_assembly v{SCRIPT_VERSION}")
    print(f"Format:   MM:SS.ss (10ms precision)")

    with open(args.transcript, encoding="utf-8") as f:
        data = json.load(f)

    # Calibrate word timestamps using audio energy analysis
    n_calibrated = calibrate_word_timestamps(data, args.transcript)
    print(f"Calibrate: {n_calibrated} word onset(s) adjusted via audio energy")

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
