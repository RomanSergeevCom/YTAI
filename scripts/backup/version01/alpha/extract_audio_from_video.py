#!/usr/bin/env python3
"""
Extract audio from video file to WAV 48kHz stereo 16-bit PCM.

Usage:
    python extract_audio_from_video.py --video "/path/to/video.mp4"
    python extract_audio_from_video.py --video "/path/to/video.mp4" --project "/path/to/project"

v2 changes:
    - Removed -ignore_editlist (not supported as global option in ffmpeg 8.x)
    - Added shlex for proper command display
    - Added duration/size estimation in output
    - Simplified flags for compatibility
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
from datetime import datetime
from pathlib import Path


DEFAULT_AUDIO_SUBDIR = Path("01_Raw/01_02_Audio")
DEFAULT_LOGS_DIRNAME = "08_Logs"

# WAV 48kHz stereo 16-bit = 192,000 bytes/sec
# 1 minute = ~11.5 MB, so 1 MB minimum catches empty files
MIN_OK_BYTES = 1_000_000


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
    """Print to console and log file."""
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


def infer_project(video_path: Path) -> Path:
    """Infer project folder from video path by looking for 01_Raw in path."""
    parts = list(video_path.parts)
    if "01_Raw" in parts:
        idx = parts.index("01_Raw")
        if idx > 0:
            return Path(*parts[:idx]).resolve()
    raise SystemExit('Cannot infer project folder from path. Pass --project explicitly.')


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract audio from video to WAV 48kHz stereo 16-bit PCM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --video "/Volumes/RYA Blue/Project/01_Raw/video.mp4"
    %(prog)s --video "/path/to/video.mp4" --project "/path/to/project"
    %(prog)s --video "/path/to/video.mp4" --dry-run
        """
    )
    ap.add_argument("--video", required=True, help="Path to input video file")
    ap.add_argument("--project", default=None, help="Project folder path (auto-detected from video path if omitted)")
    ap.add_argument(
        "--out-dir",
        default=str(DEFAULT_AUDIO_SUBDIR),
        help='Relative output folder inside project (default: "01_Raw/01_02_Audio")'
    )
    ap.add_argument("--overwrite", action="store_true", help="Overwrite output if exists")
    ap.add_argument("--dry-run", action="store_true", help="Print actions without running ffmpeg")
    ap.add_argument("--min-bytes", type=int, default=MIN_OK_BYTES, help="Minimum output size to treat as success")
    args = ap.parse_args()

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        raise SystemExit(f"ERROR: Video file not found: {video_path}")
    
    if not ffmpeg_exists():
        raise SystemExit("ERROR: ffmpeg not found. Install: brew install ffmpeg")

    project_dir = Path(args.project).expanduser().resolve() if args.project else infer_project(video_path)
    if not project_dir.exists():
        raise SystemExit(f"ERROR: Project folder not found: {project_dir}")

    # Setup directories
    logs_dir = (project_dir / DEFAULT_LOGS_DIRNAME).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    out_dir = (project_dir / Path(args.out_dir)).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Generate paths
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"extract_audio_{ts}.log"
    
    out_path = out_dir / f"{video_path.stem}_AUDIO.wav"
    if not args.overwrite:
        out_path = next_free_path(out_path)

    # Get input file size
    input_size = video_path.stat().st_size

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "EXTRACT AUDIO FROM VIDEO v2")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp : {ts}")
        tee_print(log_f, f"Project   : {project_dir}")
        tee_print(log_f, f"Input     : {video_path}")
        tee_print(log_f, f"Input size: {format_size(input_size)}")
        tee_print(log_f, f"Output    : {out_path}")
        tee_print(log_f, f"Format    : WAV 48000Hz stereo 16-bit PCM")
        tee_print(log_f, f"Log       : {log_path}")
        tee_print(log_f, "")

        # Build ffmpeg command
        # Simplified flags - removed -ignore_editlist (causes issues in ffmpeg 8.x)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-stats",
        ]
        
        if args.overwrite:
            cmd.append("-y")
        
        # Input options
        cmd.extend([
            "-probesize", "100M",
            "-analyzeduration", "100M",
            "-i", str(video_path),
        ])
        
        # Output options
        cmd.extend([
            "-map", "0:a:0",      # First audio stream only
            "-vn",                # No video
            "-sn",                # No subtitles
            "-dn",                # No data streams
            "-ar", "48000",       # Sample rate
            "-ac", "2",           # Stereo
            "-c:a", "pcm_s16le",  # 16-bit PCM little-endian
            str(out_path),
        ])

        tee_print(log_f, "FFmpeg command:")
        tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd))
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN: ffmpeg not executed.")
            print(f"\nDry run complete. Log: {log_path}")
            return

        # Run ffmpeg
        tee_print(log_f, "Extracting audio...")
        tee_print(log_f, "-" * 40)
        
        rc = run_ffmpeg_with_tee(cmd, log_f)
        
        tee_print(log_f, "-" * 40)
        tee_print(log_f, f"FFmpeg exit code: {rc}")

        # Check output
        size = out_path.stat().st_size if out_path.exists() else 0
        tee_print(log_f, f"Output size: {format_size(size)}")

        # Validate
        if rc != 0 or size < args.min_bytes:
            if out_path.exists():
                try:
                    out_path.unlink()
                except Exception:
                    pass
            tee_print(log_f, "")
            tee_print(log_f, "ERROR: Extraction failed!")
            tee_print(log_f, "")
            tee_print(log_f, "TROUBLESHOOTING:")
            tee_print(log_f, "  1. Check if video has audio track: ffprobe -i <video>")
            tee_print(log_f, "  2. Try different audio stream: -map 0:a:1")
            tee_print(log_f, "  3. Check disk space")
            raise SystemExit(2)

        # Calculate duration from file size
        # WAV 48kHz stereo 16-bit = 48000 * 2 * 2 = 192000 bytes/sec
        duration_sec = (size - 44) / 192000  # -44 for WAV header
        
        tee_print(log_f, "")
        tee_print(log_f, f"SUCCESS: Audio extracted")
        tee_print(log_f, f"  File    : {out_path}")
        tee_print(log_f, f"  Size    : {format_size(size)}")
        tee_print(log_f, f"  Duration: ~{format_duration(duration_sec)}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
