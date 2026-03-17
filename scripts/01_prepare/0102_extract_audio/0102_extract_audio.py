#!/usr/bin/env python3
"""
YTAI: Extract audio from video clips

Extracts WAV files for transcription:
1. Individual WAV for each clip → per_clip/{clip}/
2. One concatenated FULL_AUDIO.wav → Transcription/ root

Usage:
    python 02_extract_audio.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python 02_extract_audio.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run

Output:
    01_Media/Source/Transcription/
    ├── per_clip/
    │   ├── RYA-FX3-0099/
    │   │   └── RYA-FX3-0099_AUDIO.wav            (clip audio, 48kHz stereo)
    │   └── RYA-FX3-0100/
    │       └── RYA-FX3-0100_AUDIO.wav
    └── YTCG37_FULL_AUDIO.wav                      (concatenated for transcription)

    01_Media/Source/Setup/logs/
    └── YTCG37_Hadi_Dawani_extract_audio_20260113_120000.log
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

CLIPS_SUBDIR = "01_Media/Source/Video"
AUDIO_SUBDIR = "01_Media/Source/Transcription"
LOGS_SUBDIR = "01_Media/Source/Setup/logs"

MIN_OK_BYTES = 100_000  # 100KB minimum for a valid WAV

CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')


def project_code(project_dir: Path) -> str:
    """Extract short code (e.g. 'YTCG37') from project folder name."""
    m = CODE_RE.match(project_dir.name)
    return m.group(1) if m else project_dir.name


# ============================================================================
# Utilities
# ============================================================================

def natural_key(s: str):
    """Natural sort for strings with numbers: clip1, clip2, clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def ffmpeg_exists() -> bool:
    """Check if ffmpeg is available."""
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
    """Run ffmpeg command with logging."""
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
    
    # On error, show last lines
    if rc != 0 and not verbose:
        tee_print(log_f, "    FFmpeg output:")
        for line in output_lines[-5:]:
            tee_print(log_f, f"    {line}")
    
    return rc


def format_size(size_bytes: int) -> str:
    """Format file size."""
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


def escape_for_concat(path: Path) -> str:
    """Escape path for ffmpeg concat demuxer."""
    s = str(path)
    s = s.replace("'", "'\\''")
    return f"file '{s}'"


# ============================================================================
# Main logic
# ============================================================================

def main() -> None:
    ap = argparse.ArgumentParser(
        description="YTAI: Extract audio from video clips",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --skip-concat
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --dry-run
        """
    )
    ap.add_argument("--project", required=True,
                   help="Path to the project folder")
    ap.add_argument("--clips-dir", default=CLIPS_SUBDIR,
                   help=f'Clips folder (default: "{CLIPS_SUBDIR}")')
    ap.add_argument("--out-dir", default=AUDIO_SUBDIR,
                   help=f'Audio output folder (default: "{AUDIO_SUBDIR}")')
    ap.add_argument("--skip-concat", action="store_true",
                   help="Skip creating concatenated audio")
    ap.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing WAV files")
    ap.add_argument("--dry-run", action="store_true",
                   help="Show what would be done without executing")
    ap.add_argument("--verbose", action="store_true",
                   help="Show ffmpeg output")
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

    # Create directories
    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    logs_dir = (project_dir / LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Find clips
    clips = [
        p for p in clips_dir.rglob("*")
        if p.is_file() and p.suffix in VIDEO_EXTS and not p.name.startswith(".")
    ]
    clips.sort(key=lambda p: natural_key(p.name))

    if not clips:
        print(f"ERROR: No video clips found in: {clips_dir}", file=sys.stderr)
        sys.exit(1)

    # Generate paths
    project_name = project_dir.name
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"{project_name}_extract_audio_{ts}.log"
    
    # Path to concatenated audio
    concat_wav = out_dir / f"{project_code(project_dir)}_FULL_AUDIO.wav"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "YTAI: EXTRACT AUDIO FROM CLIPS")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Time       : {ts}")
        tee_print(log_f, f"Project    : {project_name}")
        tee_print(log_f, f"Path       : {project_dir}")
        tee_print(log_f, f"Clips      : {clips_dir}")
        tee_print(log_f, f"Output     : {out_dir}")
        tee_print(log_f, f"Count      : {len(clips)} clips")
        tee_print(log_f, f"Format     : WAV 48000Hz stereo 16-bit PCM")
        tee_print(log_f, f"Log        : {log_path}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "*** DRY-RUN MODE ***")
            tee_print(log_f, "")

        # ============================================================
        # PHASE 1: Extract individual audio files
        # ============================================================
        tee_print(log_f, "PHASE 1: Extract audio from each clip")
        tee_print(log_f, "-" * 40)
        
        success_count = 0
        skip_count = 0
        fail_count = 0
        total_size = 0
        wav_files = []  # For concatenation
        
        for i, clip in enumerate(clips, 1):
            # Output: per_clip/{clip_stem}/{clip_stem}_AUDIO.wav
            wav_name = f"{clip.stem}_AUDIO.wav"
            clip_per_clip = out_dir / "per_clip" / clip.stem
            clip_per_clip.mkdir(parents=True, exist_ok=True)
            wav_path = clip_per_clip / wav_name

            # Skip if already exists
            if wav_path.exists() and not args.overwrite:
                size = wav_path.stat().st_size
                if size >= MIN_OK_BYTES:
                    tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name}")
                    tee_print(log_f, f"           → SKIP (already exists)")
                    skip_count += 1
                    total_size += size
                    wav_files.append(wav_path)
                    continue

            tee_print(log_f, f"[{i:3d}/{len(clips)}] {clip.name}")
            tee_print(log_f, f"           → per_clip/{clip.stem}/{wav_name}")

            if args.dry_run:
                wav_files.append(wav_path)
                success_count += 1
                continue
            
            # FFmpeg command
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-y",
                "-i", str(clip),
                "-map", "0:a:0",        # First audio stream
                "-vn", "-sn", "-dn",    # No video, subtitles, data
                "-ar", "48000",         # Sample rate
                "-ac", "2",             # Stereo
                "-c:a", "pcm_s16le",    # 16-bit PCM
                str(wav_path),
            ]
            
            rc = run_ffmpeg(cmd, log_f, verbose=args.verbose)
            
            # Check result
            if rc != 0 or not wav_path.exists() or wav_path.stat().st_size < MIN_OK_BYTES:
                tee_print(log_f, f"           ✗ ERROR!")
                fail_count += 1
                if wav_path.exists():
                    wav_path.unlink()
            else:
                size = wav_path.stat().st_size
                total_size += size
                tee_print(log_f, f"           ✓ OK ({format_size(size)})")
                success_count += 1
                wav_files.append(wav_path)

        tee_print(log_f, "-" * 40)
        tee_print(log_f, "")
        tee_print(log_f, "Phase 1 Summary:")
        tee_print(log_f, f"  Succeeded : {success_count}")
        tee_print(log_f, f"  Skipped   : {skip_count}")
        tee_print(log_f, f"  Errors    : {fail_count}")
        if not args.dry_run:
            tee_print(log_f, f"  Size      : {format_size(total_size)}")
        tee_print(log_f, "")

        # ============================================================
        # PHASE 2: Concat all audio for transcription
        # ============================================================
        if args.skip_concat:
            tee_print(log_f, "PHASE 2: Skipped (--skip-concat)")
        elif not wav_files:
            tee_print(log_f, "PHASE 2: Skipped (no audio files)")
        else:
            tee_print(log_f, "PHASE 2: Concat audio for transcription")
            tee_print(log_f, "-" * 40)
            tee_print(log_f, f"Output : {concat_wav}")
            tee_print(log_f, f"Files  : {len(wav_files)}")
            tee_print(log_f, "")

            if args.dry_run:
                tee_print(log_f, "Will be created:")
                tee_print(log_f, f"  {concat_wav}")
            else:
                # Check if already exists
                if concat_wav.exists() and not args.overwrite:
                    tee_print(log_f, f"SKIP: {concat_wav.name} already exists")
                else:
                    # Write file list to temp file
                    tmp_f = tempfile.NamedTemporaryFile(
                        mode='w', suffix='_concat.txt',
                        delete=False, encoding='utf-8')
                    concat_list_path = Path(tmp_f.name)
                    try:
                        for wav in wav_files:
                            tmp_f.write(escape_for_concat(wav) + "\n")
                        tmp_f.close()

                        # FFmpeg concat
                        cmd_concat = [
                            "ffmpeg",
                            "-hide_banner",
                            "-loglevel", "warning",
                            "-y",
                            "-f", "concat",
                            "-safe", "0",
                            "-i", str(concat_list_path),
                            "-c", "copy",
                            str(concat_wav),
                        ]

                        tee_print(log_f, "FFmpeg command:")
                        tee_print(log_f, " ".join(shlex.quote(arg) for arg in cmd_concat))
                        tee_print(log_f, "")

                        rc = run_ffmpeg(cmd_concat, log_f, verbose=True)

                        if rc != 0 or not concat_wav.exists():
                            tee_print(log_f, "✗ ERROR: Concat failed!")
                        else:
                            concat_size = concat_wav.stat().st_size
                            # WAV: 48000 Hz * 2 channels * 2 bytes = 192000 bytes/sec
                            duration_sec = (concat_size - 44) / 192000
                            tee_print(log_f, "")
                            tee_print(log_f, "✓ Concatenated audio created:")
                            tee_print(log_f, f"  File       : {concat_wav.name}")
                            tee_print(log_f, f"  Size       : {format_size(concat_size)}")
                            tee_print(log_f, f"  Duration   : ~{format_duration(duration_sec)}")
                    finally:
                        concat_list_path.unlink(missing_ok=True)

        # ============================================================
        # Summary
        # ============================================================
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "RESULT")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "")
        tee_print(log_f, f"Individual audio: {out_dir}/per_clip/*/")
        tee_print(log_f, f"  {len(wav_files)} files: "
                         f"per_clip/<clip>/<clip>_AUDIO.wav")
        
        if not args.skip_concat and wav_files:
            tee_print(log_f, "")
            tee_print(log_f, f"Full audio (for transcription):")
            tee_print(log_f, f"  {concat_wav}")
        
        tee_print(log_f, "")
        tee_print(log_f, f"Log: {log_path}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")


if __name__ == "__main__":
    main()
