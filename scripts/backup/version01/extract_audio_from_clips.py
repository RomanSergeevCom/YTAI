#!/usr/bin/env python3
"""
Extract audio from video clips:
1. Individual WAV files for each clip (for transcription)
2. One concatenated WAV file (for speaker/voice analysis)

Usage:
    python extract_audio_from_clips.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python extract_audio_from_clips.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run

Output:
    01_Raw/01_02_Audio/
    ├── RYA-ZVE1-1146_AUDIO.wav      (individual)
    ├── RYA-ZVE1-1147_AUDIO.wav      (individual)
    ├── ...
    └── YTCG37_Hadi_Dawani_FULL_AUDIO.wav  (concatenated for voice analysis)
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

DEFAULT_CLIPS_SUBDIR = "01_Raw/01_01_Video"
DEFAULT_AUDIO_SUBDIR = "01_Raw/01_02_Audio"
DEFAULT_TMP_SUBDIR = "09_Tmp"
DEFAULT_LOGS_SUBDIR = "08_Logs"

MIN_OK_BYTES = 100_000  # 100KB minimum


def natural_key(s: str):
    """Sort strings with embedded numbers naturally."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], check=True,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def tee_print(log_f, msg: str) -> None:
    """Print to console and log file."""
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def run_ffmpeg(cmd: list[str], log_f, verbose: bool = False) -> int:
    """Run ffmpeg command."""
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
        for line in output_lines[-5:]:
            tee_print(log_f, f"    {line}")
    
    return rc


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable."""
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


def escape_for_concat(path: Path) -> str:
    """Escape path for ffmpeg concat demuxer."""
    s = str(path)
    s = s.replace("'", "'\\''")
    return f"file '{s}'"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract audio from clips: individual WAVs + one concatenated for voice analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --skip-concat
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run
        """
    )
    ap.add_argument("--project", required=True, help="Project folder path")
    ap.add_argument("--clips-dir", default=DEFAULT_CLIPS_SUBDIR,
                   help=f'Clips folder relative to project (default: "{DEFAULT_CLIPS_SUBDIR}")')
    ap.add_argument("--out-dir", default=DEFAULT_AUDIO_SUBDIR,
                   help=f'Output folder relative to project (default: "{DEFAULT_AUDIO_SUBDIR}")')
    ap.add_argument("--skip-concat", action="store_true",
                   help="Skip creating concatenated audio file")
    ap.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing WAV files")
    ap.add_argument("--dry-run", action="store_true",
                   help="Print actions without running ffmpeg")
    ap.add_argument("--verbose", action="store_true",
                   help="Show ffmpeg output for each clip")
    args = ap.parse_args()

    # Validate paths
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project folder not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    if not ffmpeg_exists():
        print("ERROR: ffmpeg not found. Install: brew install ffmpeg", file=sys.stderr)
        sys.exit(1)

    clips_dir = (project_dir / args.clips_dir).resolve()
    if not clips_dir.exists():
        print(f"ERROR: Clips folder not found: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    # Setup directories
    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    tmp_dir = (project_dir / DEFAULT_TMP_SUBDIR).resolve()
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = (project_dir / DEFAULT_LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Find clips
    clips = [
        p for p in clips_dir.iterdir()
        if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")
    ]
    clips.sort(key=lambda p: natural_key(p.name))

    if not clips:
        print(f"ERROR: No video clips found in: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    # Generate paths
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"extract_audio_{ts}.log"
    project_name = project_dir.name
    
    # Concatenated audio path
    concat_wav = out_dir / f"{project_name}_FULL_AUDIO.wav"
    concat_list_file = tmp_dir / "audio_concat_list.txt"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "EXTRACT AUDIO FROM CLIPS")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp  : {ts}")
        tee_print(log_f, f"Project    : {project_dir}")
        tee_print(log_f, f"Clips dir  : {clips_dir}")
        tee_print(log_f, f"Output dir : {out_dir}")
        tee_print(log_f, f"Clip count : {len(clips)}")
        tee_print(log_f, f"Format     : WAV 48000Hz stereo 16-bit PCM")
        tee_print(log_f, f"Log        : {log_path}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN MODE")
            tee_print(log_f, "")

        # ============================================================
        # PHASE 1: Extract individual audio files
        # ============================================================
        tee_print(log_f, "PHASE 1: Extracting individual audio files...")
        tee_print(log_f, "-" * 40)
        
        success_count = 0
        skip_count = 0
        fail_count = 0
        total_size = 0
        wav_files = []  # For concatenation
        
        for i, clip in enumerate(clips, 1):
            # Output: same name + _AUDIO.wav
            wav_name = f"{clip.stem}_AUDIO.wav"
            wav_path = out_dir / wav_name
            
            # Skip if exists and not overwriting
            if wav_path.exists() and not args.overwrite:
                size = wav_path.stat().st_size
                if size >= MIN_OK_BYTES:
                    tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name} → SKIP (exists)")
                    skip_count += 1
                    total_size += size
                    wav_files.append(wav_path)
                    continue
            
            tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name} → {wav_name}")
            
            if args.dry_run:
                wav_files.append(wav_path)
                success_count += 1
                continue
            
            # Build ffmpeg command
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-i", str(clip),
                "-map", "0:a:0",
                "-vn", "-sn", "-dn",
                "-ar", "48000",
                "-ac", "2",
                "-c:a", "pcm_s16le",
                str(wav_path),
            ]
            
            rc = run_ffmpeg(cmd, log_f, verbose=args.verbose)
            
            # Validate output
            if rc != 0 or not wav_path.exists() or wav_path.stat().st_size < MIN_OK_BYTES:
                tee_print(log_f, f"           FAILED!")
                fail_count += 1
                if wav_path.exists():
                    wav_path.unlink()
            else:
                size = wav_path.stat().st_size
                total_size += size
                tee_print(log_f, f"           OK ({format_size(size)})")
                success_count += 1
                wav_files.append(wav_path)

        tee_print(log_f, "-" * 40)
        tee_print(log_f, "")
        tee_print(log_f, "Phase 1 Summary:")
        tee_print(log_f, f"  Success : {success_count}")
        tee_print(log_f, f"  Skipped : {skip_count}")
        tee_print(log_f, f"  Failed  : {fail_count}")
        if not args.dry_run:
            tee_print(log_f, f"  Total   : {format_size(total_size)}")
        tee_print(log_f, "")

        # ============================================================
        # PHASE 2: Concatenate all audio for voice analysis
        # ============================================================
        if args.skip_concat:
            tee_print(log_f, "PHASE 2: Skipped (--skip-concat)")
        elif not wav_files:
            tee_print(log_f, "PHASE 2: Skipped (no audio files)")
        else:
            tee_print(log_f, "PHASE 2: Creating concatenated audio for voice analysis...")
            tee_print(log_f, "-" * 40)
            tee_print(log_f, f"Output: {concat_wav}")
            tee_print(log_f, f"Files to concat: {len(wav_files)}")
            tee_print(log_f, "")

            if args.dry_run:
                tee_print(log_f, "Would concatenate all WAV files into:")
                tee_print(log_f, f"  {concat_wav}")
            else:
                # Check if already exists
                if concat_wav.exists() and not args.overwrite:
                    tee_print(log_f, f"SKIP: {concat_wav.name} already exists")
                else:
                    # Write concat list
                    with concat_list_file.open("w", encoding="utf-8") as f:
                        for wav in wav_files:
                            f.write(escape_for_concat(wav) + "\n")
                    
                    # Concatenate
                    cmd_concat = [
                        "ffmpeg",
                        "-hide_banner",
                        "-loglevel", "warning",
                        "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_list_file),
                        "-c", "copy",
                        str(concat_wav),
                    ]
                    
                    tee_print(log_f, "FFmpeg command:")
                    tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd_concat))
                    tee_print(log_f, "")

                    rc = run_ffmpeg(cmd_concat, log_f, verbose=True)

                    if rc != 0 or not concat_wav.exists():
                        tee_print(log_f, "WARNING: Concatenation failed!")
                    else:
                        concat_size = concat_wav.stat().st_size
                        duration_sec = (concat_size - 44) / 192000
                        tee_print(log_f, "")
                        tee_print(log_f, f"Concatenated audio created:")
                        tee_print(log_f, f"  File    : {concat_wav}")
                        tee_print(log_f, f"  Size    : {format_size(concat_size)}")
                        tee_print(log_f, f"  Duration: ~{format_duration(duration_sec)}")
                    
                    # Cleanup temp file
                    try:
                        concat_list_file.unlink()
                    except Exception:
                        pass

        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "OUTPUT FILES")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Individual audio: {out_dir}/")
        tee_print(log_f, f"  {len(wav_files)} files: <clip_name>_AUDIO.wav")
        if not args.skip_concat and wav_files:
            tee_print(log_f, f"")
            tee_print(log_f, f"Full audio (for voice analysis):")
            tee_print(log_f, f"  {concat_wav}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
