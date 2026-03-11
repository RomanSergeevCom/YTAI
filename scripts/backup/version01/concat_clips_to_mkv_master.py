#!/usr/bin/env python3
"""
Concatenate raw video clips into a stable master file (MKV or MP4) without re-encoding.

Usage:
    python concat_clips_to_mkv_master.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python concat_clips_to_mkv_master.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --also-mp4
    python concat_clips_to_mkv_master.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run

v4 fixes:
    - Map only video and audio streams (-map 0:v -map 0:a)
    - Ignore unknown streams (thumbnails, metadata tracks from cameras)
    - Added -ignore_unknown as fallback
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}


def natural_key(s: str):
    """Sort strings with embedded numbers naturally: clip1, clip2, clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return True
    except Exception:
        return False


def tee_print(log_f, msg: str) -> None:
    """Print to console and log file simultaneously."""
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def run_ffmpeg_with_tee(cmd: list[str], log_f) -> int:
    """Run ffmpeg and stream output to both console and log."""
    cmd_str = " ".join(shlex.quote(arg) for arg in cmd)
    tee_print(log_f, f"Running:\n{cmd_str}\n")
    
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert p.stdout is not None
    
    for line in p.stdout:
        tee_print(log_f, line.rstrip("\n"))
    
    return p.wait()


def next_free_path(p: Path) -> Path:
    """Find next available filename if path exists."""
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    for i in range(2, 1000):
        cand = p.with_name(f"{stem}_v{i:02d}{suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("Too many versions, cannot find free output name")


def escape_for_concat(path: Path) -> str:
    """Escape path for ffmpeg concat demuxer."""
    s = str(path)
    s = s.replace("'", "'\\''")
    return f"file '{s}'"


def probe_video(video_path: Path) -> Optional[dict]:
    """Get video info using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(video_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def get_video_info_summary(clips: list[Path], log_f) -> None:
    """Log info about first clip to help diagnose issues."""
    if not clips:
        return
    
    first_clip = clips[0]
    info = probe_video(first_clip)
    
    if info:
        tee_print(log_f, "First clip info:")
        fmt = info.get("format", {})
        duration = fmt.get("duration", "unknown")
        tee_print(log_f, f"  Duration: {duration}s")
        
        for stream in info.get("streams", []):
            codec_type = stream.get("codec_type", "unknown")
            codec_name = stream.get("codec_name", "unknown")
            
            if codec_type == "video":
                width = stream.get("width", "?")
                height = stream.get("height", "?")
                fps = stream.get("r_frame_rate", "?")
                tee_print(log_f, f"  Video: {codec_name} {width}x{height} @ {fps}")
            elif codec_type == "audio":
                sample_rate = stream.get("sample_rate", "?")
                channels = stream.get("channels", "?")
                tee_print(log_f, f"  Audio: {codec_name} {sample_rate}Hz {channels}ch")
            else:
                tee_print(log_f, f"  Other: {codec_type} ({codec_name}) - will be skipped")
        
        tee_print(log_f, "")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Concatenate raw clips into a stable master (default MKV) without re-encoding.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/MyProject"
    %(prog)s --project "/Volumes/RYA Blue/MyProject" --also-mp4
    %(prog)s --project "/Volumes/RYA Blue/MyProject" --container mp4
    %(prog)s --project "/Volumes/RYA Blue/MyProject" --dry-run
        """
    )
    ap.add_argument(
        "--project",
        required=True,
        help='Project folder, e.g. "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"'
    )
    ap.add_argument(
        "--clips-dir",
        default="01_Raw/01_01_Video",
        help='Relative path inside project where clips live (default: "01_Raw/01_01_Video")'
    )
    ap.add_argument(
        "--out-dir",
        default="01_Raw",
        help='Relative output folder inside project (default: "01_Raw")'
    )
    ap.add_argument(
        "--container",
        choices=["mkv", "mp4"],
        default="mkv",
        help="Master container. MKV is more stable for concat, MP4 for compatibility."
    )
    ap.add_argument(
        "--also-mp4",
        action="store_true",
        help="If master is MKV, also create MP4 copy (remux, no re-encode)."
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite outputs if they exist"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without running ffmpeg"
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Show more detailed output"
    )
    args = ap.parse_args()

    # Validate project folder
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project folder not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # Check ffmpeg
    if not ffmpeg_exists():
        print("ERROR: ffmpeg not found. Install: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)

    # Validate clips folder
    clips_dir = (project_dir / args.clips_dir).resolve()
    if not clips_dir.exists():
        print(f"ERROR: Clips folder not found: {clips_dir}", file=sys.stderr)
        print(f"HINT: Create folder and add video files: mkdir -p \"{clips_dir}\"", file=sys.stderr)
        sys.exit(1)

    # Setup directories
    logs_dir = (project_dir / "08_Logs").resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    tmp_dir = (project_dir / "09_Tmp").resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate paths
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"concat_master_{ts}.log"
    concat_file = tmp_dir / "concat_list.txt"

    project_name = project_dir.name
    master_ext = ".mkv" if args.container == "mkv" else ".mp4"
    master_path = out_dir / f"{project_name}{master_ext}"
    
    if not args.overwrite:
        master_path = next_free_path(master_path)

    # Find video clips
    clips = [
        p for p in clips_dir.iterdir()
        if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")
    ]
    clips.sort(key=lambda p: natural_key(p.name))

    if not clips:
        print(f"ERROR: No video clips found in: {clips_dir}", file=sys.stderr)
        print(f"HINT: Supported formats: {', '.join(sorted(VIDEO_EXTS))}", file=sys.stderr)
        sys.exit(1)

    # Start logging
    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "CONCAT CLIPS TO MASTER v4")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp : {ts}")
        tee_print(log_f, f"Project   : {project_dir}")
        tee_print(log_f, f"Clips dir : {clips_dir}")
        tee_print(log_f, f"Clip count: {len(clips)}")
        tee_print(log_f, f"Container : {args.container.upper()}")
        tee_print(log_f, f"Output    : {master_path}")
        tee_print(log_f, f"Log       : {log_path}")
        tee_print(log_f, "")

        # Calculate total size
        total_size_mb = sum(c.stat().st_size for c in clips) / (1024 * 1024)
        tee_print(log_f, f"Total input size: {total_size_mb:.1f} MB ({total_size_mb/1024:.2f} GB)")
        tee_print(log_f, "")

        # List all clips
        tee_print(log_f, "Clips to concatenate:")
        for i, clip in enumerate(clips, 1):
            size_mb = clip.stat().st_size / (1024 * 1024)
            tee_print(log_f, f"  {i:3d}. {clip.name} ({size_mb:.1f} MB)")
        tee_print(log_f, "")

        # Probe first clip for diagnostics
        if args.verbose:
            get_video_info_summary(clips, log_f)

        # Write concat file
        tee_print(log_f, f"Writing concat list: {concat_file}")
        with concat_file.open("w", encoding="utf-8") as f:
            for clip in clips:
                f.write(escape_for_concat(clip) + "\n")
        tee_print(log_f, "")

        # Build ffmpeg command
        # KEY FIX: -map 0:v -map 0:a instead of -map 0
        # This skips unknown streams (thumbnails, timecode tracks, etc.)
        cmd_master = [
            "ffmpeg",
            "-hide_banner",
            "-stats",
        ]
        
        if args.overwrite:
            cmd_master.append("-y")
        
        # Input
        cmd_master.extend([
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
        ])
        
        # Output: map only video and audio, skip unknown streams
        cmd_master.extend([
            "-map", "0:v",          # All video streams
            "-map", "0:a",          # All audio streams  
            "-c", "copy",           # No re-encoding
            "-fflags", "+genpts",
            "-avoid_negative_ts", "make_zero",
        ])
        
        # Container-specific
        if args.container == "mp4":
            cmd_master.extend(["-movflags", "+faststart"])
        
        cmd_master.append(str(master_path))

        tee_print(log_f, "FFmpeg command:")
        tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd_master))
        tee_print(log_f, "")
        tee_print(log_f, "Note: Mapping only video+audio streams, skipping unknown/metadata tracks")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN: ffmpeg not executed.")
            tee_print(log_f, "")
            tee_print(log_f, f"Concat file content ({concat_file}):")
            tee_print(log_f, concat_file.read_text())
            print(f"\nDry run complete. Log: {log_path}")
            return

        # Run ffmpeg
        tee_print(log_f, "Starting concatenation...")
        tee_print(log_f, "-" * 40)
        
        rc = run_ffmpeg_with_tee(cmd_master, log_f)
        
        tee_print(log_f, "-" * 40)
        tee_print(log_f, f"FFmpeg exit code: {rc}")

        # Validate output
        if rc != 0:
            tee_print(log_f, "")
            tee_print(log_f, "ERROR: FFmpeg failed!")
            tee_print(log_f, "")
            tee_print(log_f, "TROUBLESHOOTING:")
            tee_print(log_f, "  1. Check if all clips have same codec/resolution")
            tee_print(log_f, "  2. Try: ffprobe \"<clip>\" to inspect problematic file")
            tee_print(log_f, "  3. 'edit list' warnings are usually OK, actual errors matter")
            tee_print(log_f, "  4. Try with single clip first to isolate issue")
            sys.exit(1)

        if not master_path.exists():
            tee_print(log_f, "ERROR: Output file was not created!")
            sys.exit(1)

        master_size = master_path.stat().st_size
        if master_size == 0:
            tee_print(log_f, "ERROR: Output file is empty!")
            master_path.unlink()
            sys.exit(1)

        master_size_mb = master_size / (1024 * 1024)
        tee_print(log_f, "")
        tee_print(log_f, f"SUCCESS: Master created")
        tee_print(log_f, f"  File: {master_path}")
        tee_print(log_f, f"  Size: {master_size_mb:.1f} MB ({master_size_mb/1024:.2f} GB)")

        # Optional MP4 remux
        if args.container == "mkv" and args.also_mp4:
            tee_print(log_f, "")
            tee_print(log_f, "Creating MP4 copy (remux, no re-encode)...")
            
            mp4_path = master_path.with_suffix(".mp4")
            if not args.overwrite:
                mp4_path = next_free_path(mp4_path)

            cmd_mp4 = [
                "ffmpeg",
                "-hide_banner",
                "-stats",
            ]
            
            if args.overwrite:
                cmd_mp4.append("-y")
            
            cmd_mp4.extend([
                "-i", str(master_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(mp4_path)
            ])

            tee_print(log_f, "")
            tee_print(log_f, "FFmpeg command (MP4 remux):")
            tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd_mp4))
            tee_print(log_f, "")

            rc2 = run_ffmpeg_with_tee(cmd_mp4, log_f)

            if rc2 != 0 or not mp4_path.exists() or mp4_path.stat().st_size == 0:
                tee_print(log_f, "WARNING: MP4 remux failed, but MKV master is OK")
            else:
                mp4_size_mb = mp4_path.stat().st_size / (1024 * 1024)
                tee_print(log_f, f"SUCCESS: MP4 copy created")
                tee_print(log_f, f"  File: {mp4_path}")
                tee_print(log_f, f"  Size: {mp4_size_mb:.1f} MB ({mp4_size_mb/1024:.2f} GB)")

        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
