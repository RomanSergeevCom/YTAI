#!/usr/bin/env python3
"""
YTAI: Sync DJI audio with camera video clips

DJI wireless mics record mono WAV (24-bit, 48kHz) with a maximum of 30 minutes per file.
This script trims and concatenates DJI WAV files to match each camera video clip,
using metadata timestamps for synchronization.

Usage:
    python 03_sync_dji_audio.py --project "/Volumes/RYA Blue/YTCG37_Project" --tz-offset 4
    python 03_sync_dji_audio.py --project "/Volumes/RYA Blue/YTCG37_Project" --tz-offset 4 --dry-run

Output:
    01_Media/Source/Audio/
    ├── RYA-FX3-0099_TX02.wav     (trimmed DJI WAV for clip 0099)
    ├── RYA-FX3-0100_TX02.wav     (concat + trim for clip 0100)
    └── ...

    01_Media/Source/Setup/logs/
    └── YTCG37_Project_sync_dji_audio_20260311_120000.log
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

WAV_EXTS = {".wav", ".WAV"}

CLIPS_SUBDIR = "01_Media/Source/Video"
DJI_SUBDIR = "99_Pipeline/DJI_Audio"
AUDIO_SUBDIR = "01_Media/Source/Audio"
LOGS_SUBDIR = "01_Media/Source/Setup/logs"

MIN_OK_BYTES = 100_000  # 100KB minimum for a valid WAV


# ============================================================================
# Utilities
# ============================================================================

def natural_key(s: str):
    """Natural sort for strings with numbers: clip1, clip2, clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    """Check whether ffmpeg/ffprobe is available."""
    try:
        subprocess.run(["ffprobe", "-version"], check=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def tee_print(log_f, msg: str) -> None:
    """Print to both console and log file."""
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def run_ffmpeg(cmd: list[str], log_f, verbose: bool = False) -> int:
    """Run an ffmpeg command with logging."""
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None

    output_lines = []
    for line in p.stdout:
        output_lines.append(line.rstrip("\n"))
        if verbose:
            tee_print(log_f, f"    {line.rstrip()}")

    rc = p.wait()

    if rc != 0 and not verbose:
        tee_print(log_f, "    FFmpeg output:")
        for line in output_lines[-5:]:
            tee_print(log_f, f"    {line}")

    return rc


def format_size(size_bytes: int) -> str:
    """Format file size for display."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def format_duration(seconds: float) -> str:
    """Format duration as HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ============================================================================
# ffprobe helpers
# ============================================================================

def ffprobe_json(filepath: Path) -> dict:
    """Get metadata via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(filepath),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {filepath}: {result.stderr}")
    return json.loads(result.stdout)


def get_video_clip_info(filepath: Path) -> dict:
    """Get creation_time (UTC) and duration of a video clip."""
    info = ffprobe_json(filepath)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))
    tags = fmt.get("tags", {})

    creation_time_str = tags.get("creation_time", "")
    creation_utc = None
    if creation_time_str:
        # Format: "2026-03-06T06:26:08.000000Z"
        for fmt_str in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                creation_utc = datetime.strptime(creation_time_str, fmt_str).replace(
                    tzinfo=timezone.utc
                )
                break
            except ValueError:
                continue

    return {
        "clip_id": filepath.stem,
        "path": filepath,
        "duration": duration,
        "creation_utc": creation_utc,
    }


def get_dji_wav_info(filepath: Path, tz_offset_hours: float) -> dict:
    """Get DJI WAV metadata: tx_id, creation_time, duration."""
    info = ffprobe_json(filepath)
    fmt = info.get("format", {})
    duration = float(fmt.get("duration", 0))
    tags = fmt.get("tags", {})

    # Parse tx_id from filename: TX02_MIC037_20260306_102304_orig.wav
    name = filepath.stem
    tx_match = re.match(r"(TX\d+)", name, re.IGNORECASE)
    tx_id = tx_match.group(1).upper() if tx_match else "TX00"

    # Parse creation time from tags
    date_str = tags.get("date", "")
    time_str = tags.get("creation_time", "")

    creation_utc = None
    if date_str and time_str:
        # DJI records in local time
        local_tz = timezone(timedelta(hours=tz_offset_hours))
        try:
            local_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            local_dt = local_dt.replace(tzinfo=local_tz)
            creation_utc = local_dt.astimezone(timezone.utc)
        except ValueError:
            pass

    # Fallback: parse from filename
    if creation_utc is None:
        ts_match = re.search(r"(\d{8})_(\d{6})", name)
        if ts_match:
            local_tz = timezone(timedelta(hours=tz_offset_hours))
            try:
                local_dt = datetime.strptime(
                    f"{ts_match.group(1)}_{ts_match.group(2)}",
                    "%Y%m%d_%H%M%S"
                )
                local_dt = local_dt.replace(tzinfo=local_tz)
                creation_utc = local_dt.astimezone(timezone.utc)
            except ValueError:
                pass

    # Audio stream properties
    audio_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "audio"),
        {}
    )
    sample_rate = int(audio_stream.get("sample_rate", 48000))
    bits = int(audio_stream.get("bits_per_sample", 24))
    channels = int(audio_stream.get("channels", 1))

    return {
        "tx_id": tx_id,
        "path": filepath,
        "duration": duration,
        "creation_utc": creation_utc,
        "sample_rate": sample_rate,
        "bits_per_sample": bits,
        "channels": channels,
    }


# ============================================================================
# Sync logic
# ============================================================================

def find_overlapping_wavs(clip: dict, wavs: list[dict]) -> list[dict]:
    """Find DJI WAV files that overlap with the clip's time range.

    Returns:
        List of dicts: [{wav, trim_start, trim_duration}, ...]
    """
    clip_start = clip["creation_utc"]
    clip_end = clip_start + timedelta(seconds=clip["duration"])
    segments = []

    for wav in wavs:
        wav_start = wav["creation_utc"]
        wav_end = wav_start + timedelta(seconds=wav["duration"])

        # Overlap?
        overlap_start = max(clip_start, wav_start)
        overlap_end = min(clip_end, wav_end)

        if overlap_start < overlap_end:
            trim_start = (overlap_start - wav_start).total_seconds()
            trim_duration = (overlap_end - overlap_start).total_seconds()
            segments.append({
                "wav": wav,
                "trim_start": trim_start,
                "trim_duration": trim_duration,
            })

    # Sort by overlap start time
    segments.sort(key=lambda s: s["wav"]["creation_utc"])
    return segments


def build_ffmpeg_cmd(segments: list[dict], output_path: Path) -> list[str]:
    """Build ffmpeg command for trim (1 WAV) or concat+trim (N WAV).

    Quality: PCM lossless -- preserves original DJI parameters (24-bit, 48kHz).
    """
    if len(segments) == 1:
        # Simple trim -- lossless copy
        seg = segments[0]
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-ss", f"{seg['trim_start']:.6f}",
            "-t", f"{seg['trim_duration']:.6f}",
            "-i", str(seg["wav"]["path"]),
            "-c", "copy",
            str(output_path),
        ]
    else:
        # Concat filter -- pcm_s24le for lossless quality
        inputs = []
        filter_parts = []
        concat_inputs = []

        for i, seg in enumerate(segments):
            inputs.extend(["-i", str(seg["wav"]["path"])])
            label = f"a{i}"
            filter_parts.append(
                f"[{i}]atrim=start={seg['trim_start']:.6f}:"
                f"end={seg['trim_start'] + seg['trim_duration']:.6f},"
                f"asetpts=N/SR/TB[{label}]"
            )
            concat_inputs.append(f"[{label}]")

        n = len(segments)
        filter_str = (
            ";".join(filter_parts) +
            f";{''.join(concat_inputs)}concat=n={n}:v=0:a=1[out]"
        )

        sample_rate = segments[0]["wav"]["sample_rate"]
        bits = segments[0]["wav"]["bits_per_sample"]
        codec = f"pcm_s{bits}le"

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            *inputs,
            "-filter_complex", filter_str,
            "-map", "[out]",
            "-c:a", codec,
            "-ar", str(sample_rate),
            str(output_path),
        ]


# ============================================================================
# Main
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="YTAI: Sync DJI audio with camera video clips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Project" --tz-offset 4
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Project" --tz-offset 4 --dry-run
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Project" --tz-offset 4 --dji-dir "DJI_Audio"
        """
    )
    ap.add_argument("--project", required=True,
                   help="Path to the project folder")
    ap.add_argument("--tz-offset", required=True, type=float,
                   help="Shooting timezone (UTC+N). Example: 4 for Dubai, 3 for Moscow")
    ap.add_argument("--clips-dir", default=CLIPS_SUBDIR,
                   help=f'Folder with video clips (default: "{CLIPS_SUBDIR}")')
    ap.add_argument("--dji-dir", default=DJI_SUBDIR,
                   help=f'Folder with DJI WAV files (default: "{DJI_SUBDIR}")')
    ap.add_argument("--out-dir", default=AUDIO_SUBDIR,
                   help=f'Output folder (default: "{AUDIO_SUBDIR}")')
    ap.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing files")
    ap.add_argument("--dry-run", action="store_true",
                   help="Show what would be done without executing")
    ap.add_argument("--verbose", action="store_true",
                   help="Show ffmpeg output")
    args = ap.parse_args()

    # ---- Validate paths ----
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project folder not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    if not ffmpeg_exists():
        print("ERROR: ffprobe/ffmpeg not found. Install with: brew install ffmpeg",
              file=sys.stderr)
        sys.exit(1)

    clips_dir = (project_dir / args.clips_dir).resolve()
    if not clips_dir.exists():
        print(f"ERROR: Video clips folder not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    dji_dir = (project_dir / args.dji_dir).resolve()
    if not dji_dir.exists():
        print(f"ERROR: DJI WAV folder not found: {dji_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = (project_dir / LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # ---- Gather data ----
    video_files = sorted(
        [p for p in clips_dir.iterdir()
         if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name)
    )
    dji_files = sorted(
        [p for p in dji_dir.iterdir()
         if p.is_file() and p.suffix in WAV_EXTS and not p.name.startswith(".")],
        key=lambda p: natural_key(p.name)
    )

    if not video_files:
        print(f"ERROR: No video clips found in: {clips_dir}", file=sys.stderr)
        sys.exit(1)
    if not dji_files:
        print(f"ERROR: No DJI WAV files found in: {dji_dir}", file=sys.stderr)
        sys.exit(1)

    # ---- Logging ----
    project_name = project_dir.name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{project_name}_sync_dji_audio_{ts}.log"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "YTAI: DJI AUDIO SYNC")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp  : {ts}")
        tee_print(log_f, f"Project    : {project_name}")
        tee_print(log_f, f"Video      : {clips_dir} ({len(video_files)} files)")
        tee_print(log_f, f"DJI WAV    : {dji_dir} ({len(dji_files)} files)")
        tee_print(log_f, f"Output     : {out_dir}")
        tee_print(log_f, f"TZ offset  : UTC+{args.tz_offset}")
        tee_print(log_f, f"Log        : {log_path}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "*** DRY-RUN MODE ***")
            tee_print(log_f, "")

        # ============================================================
        # PHASE 1: Collect metadata
        # ============================================================
        tee_print(log_f, "PHASE 1: Collecting metadata")
        tee_print(log_f, "-" * 40)

        clips = []
        for vf in video_files:
            try:
                info = get_video_clip_info(vf)
                clips.append(info)
                tee_print(log_f,
                    f"  Video: {vf.name}  "
                    f"dur={format_duration(info['duration'])}  "
                    f"created={info['creation_utc'].strftime('%H:%M:%S') if info['creation_utc'] else '?'} UTC"
                )
            except Exception as e:
                tee_print(log_f, f"  ✗ {vf.name}: {e}")

        dji_wavs = []
        for df in dji_files:
            try:
                info = get_dji_wav_info(df, args.tz_offset)
                dji_wavs.append(info)
                tee_print(log_f,
                    f"  DJI:   {df.name}  "
                    f"dur={format_duration(info['duration'])}  "
                    f"created={info['creation_utc'].strftime('%H:%M:%S') if info['creation_utc'] else '?'} UTC  "
                    f"tx={info['tx_id']}  "
                    f"{info['bits_per_sample']}bit/{info['sample_rate']}Hz"
                )
            except Exception as e:
                tee_print(log_f, f"  ✗ {df.name}: {e}")

        tee_print(log_f, "")

        # Check that all entries have timestamps
        clips_ok = [c for c in clips if c["creation_utc"] is not None]
        wavs_ok = [w for w in dji_wavs if w["creation_utc"] is not None]

        if not clips_ok:
            tee_print(log_f, "ERROR: No video clips contain creation_time!")
            sys.exit(1)
        if not wavs_ok:
            tee_print(log_f, "ERROR: No DJI WAV files contain creation_time!")
            sys.exit(1)

        if len(clips_ok) < len(clips):
            tee_print(log_f,
                f"WARNING: {len(clips) - len(clips_ok)} video(s) without creation_time -- skipped")
        if len(wavs_ok) < len(dji_wavs):
            tee_print(log_f,
                f"WARNING: {len(dji_wavs) - len(wavs_ok)} DJI WAV(s) without creation_time -- skipped")

        # Group DJI files by transmitter
        dji_by_tx: dict[str, list[dict]] = {}
        for wav in wavs_ok:
            tx = wav["tx_id"]
            dji_by_tx.setdefault(tx, []).append(wav)
        # Sort by time within each group
        for tx in dji_by_tx:
            dji_by_tx[tx].sort(key=lambda w: w["creation_utc"])

        tx_ids = sorted(dji_by_tx.keys())
        tee_print(log_f, f"Transmitters: {', '.join(tx_ids)}")
        for tx in tx_ids:
            tee_print(log_f, f"  {tx}: {len(dji_by_tx[tx])} file(s)")
        tee_print(log_f, "")

        # ============================================================
        # PHASE 2: Sync and trim
        # ============================================================
        tee_print(log_f, "PHASE 2: Sync and trim")
        tee_print(log_f, "-" * 40)

        success_count = 0
        skip_count = 0
        fail_count = 0
        no_overlap_count = 0
        total_size = 0

        for clip in clips_ok:
            for tx in tx_ids:
                output_name = f"{clip['clip_id']}_{tx}.wav"
                output_path = out_dir / output_name

                # Skip if already exists
                if output_path.exists() and not args.overwrite:
                    size = output_path.stat().st_size
                    if size >= MIN_OK_BYTES:
                        tee_print(log_f,
                            f"  {clip['clip_id']} × {tx} → SKIP (already exists)")
                        skip_count += 1
                        total_size += size
                        continue

                # Find overlapping WAV files
                segments = find_overlapping_wavs(clip, dji_by_tx[tx])

                if not segments:
                    tee_print(log_f,
                        f"  {clip['clip_id']} × {tx} → no overlap with DJI")
                    no_overlap_count += 1
                    continue

                # Segment info
                total_covered = sum(s["trim_duration"] for s in segments)
                coverage_pct = (total_covered / clip["duration"]) * 100

                tee_print(log_f, f"  {clip['clip_id']} × {tx}:")
                for seg in segments:
                    wav_name = seg["wav"]["path"].name
                    tee_print(log_f,
                        f"    {wav_name}: "
                        f"offset={seg['trim_start']:.1f}s  "
                        f"dur={seg['trim_duration']:.1f}s"
                    )
                tee_print(log_f,
                    f"    Coverage: {format_duration(total_covered)} / "
                    f"{format_duration(clip['duration'])} ({coverage_pct:.0f}%)")

                if args.dry_run:
                    tee_print(log_f, f"    → {output_name} (dry-run)")
                    success_count += 1
                    continue

                # Build and run ffmpeg
                cmd = build_ffmpeg_cmd(segments, output_path)

                if args.verbose:
                    tee_print(log_f, f"    cmd: {' '.join(shlex.quote(a) for a in cmd)}")

                rc = run_ffmpeg(cmd, log_f, verbose=args.verbose)

                if rc != 0 or not output_path.exists() or output_path.stat().st_size < MIN_OK_BYTES:
                    tee_print(log_f, f"    ✗ ERROR!")
                    fail_count += 1
                    if output_path.exists():
                        output_path.unlink()
                else:
                    size = output_path.stat().st_size
                    total_size += size
                    tee_print(log_f, f"    ✓ {output_name} ({format_size(size)})")
                    success_count += 1

        # ============================================================
        # Summary
        # ============================================================
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "RESULT")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"  Succeeded  : {success_count}")
        tee_print(log_f, f"  Skipped    : {skip_count}")
        tee_print(log_f, f"  No overlap : {no_overlap_count}")
        tee_print(log_f, f"  Errors     : {fail_count}")
        if not args.dry_run and total_size > 0:
            tee_print(log_f, f"  Total size : {format_size(total_size)}")
        tee_print(log_f, "")
        tee_print(log_f, f"Output: {out_dir}/")
        tee_print(log_f, f"Log   : {log_path}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
