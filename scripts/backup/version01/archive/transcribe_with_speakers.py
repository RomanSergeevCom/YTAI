#!/usr/bin/env python3
"""
Transcribe audio files with speaker diarization.

Pipeline:
1. Analyze FULL_AUDIO.wav → detect speakers (pyannote)
2. Transcribe each clip with Whisper → word-level timestamps
3. Merge speaker info + transcription
4. Output single JSON with all data

Usage:
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --language en
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --skip-diarization

Requirements:
    pip install mlx-whisper pyannote.audio

Output:
    02_Transcripts/02_01_Runs/transcript_with_speakers.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Check imports
try:
    import mlx_whisper
    HAS_MLX_WHISPER = True
except ImportError:
    HAS_MLX_WHISPER = False

try:
    from pyannote.audio import Pipeline as PyannotePipeline
    HAS_PYANNOTE = True
except ImportError:
    HAS_PYANNOTE = False


# Paths
DEFAULT_AUDIO_SUBDIR = "01_Raw/01_02_Audio"
DEFAULT_TRANSCRIPT_SUBDIR = "02_Transcripts/02_01_Runs"
DEFAULT_LOGS_SUBDIR = "08_Logs"

# Whisper models optimized for M3
WHISPER_MODELS = {
    "en": "mlx-community/whisper-large-v3-turbo",      # Fast, good for English
    "ar": "mlx-community/whisper-large-v3",            # Better for Arabic
    "auto": "mlx-community/whisper-large-v3-turbo",    # Auto-detect language
}


def natural_key(s: str):
    """Sort strings with embedded numbers naturally."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def tee_print(log_f, msg: str) -> None:
    """Print to console and log file."""
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS.mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def format_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_audio_duration(wav_path: Path) -> float:
    """Get audio duration using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(wav_path)
            ],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: calculate from file size (WAV 48kHz stereo 16-bit)
        size = wav_path.stat().st_size
        return (size - 44) / 192000


def run_speaker_diarization(
    audio_path: Path,
    hf_token: str,
    log_f,
    num_speakers: Optional[int] = None
) -> list[dict]:
    """
    Run speaker diarization on audio file.
    Returns list of segments with speaker labels.
    """
    if not HAS_PYANNOTE:
        tee_print(log_f, "WARNING: pyannote.audio not installed, skipping diarization")
        return []
    
    tee_print(log_f, "Loading pyannote speaker diarization model...")
    
    try:
        pipeline = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token
        )
        
        # Run on MPS (Apple Silicon) if available
        import torch
        if torch.backends.mps.is_available():
            pipeline = pipeline.to(torch.device("mps"))
            tee_print(log_f, "Using Apple Silicon GPU (MPS)")
        
        tee_print(log_f, f"Processing: {audio_path.name}")
        
        # Run diarization
        if num_speakers:
            diarization = pipeline(str(audio_path), num_speakers=num_speakers)
        else:
            diarization = pipeline(str(audio_path))
        
        # Convert to list of segments
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })
        
        # Get unique speakers
        speakers = sorted(set(s["speaker"] for s in segments))
        tee_print(log_f, f"Detected {len(speakers)} speakers: {', '.join(speakers)}")
        
        return segments
        
    except Exception as e:
        tee_print(log_f, f"ERROR in diarization: {e}")
        return []


def transcribe_audio(
    audio_path: Path,
    language: str,
    log_f,
    word_timestamps: bool = True
) -> dict:
    """
    Transcribe audio file using MLX Whisper.
    Returns transcription with word-level timestamps.
    """
    if not HAS_MLX_WHISPER:
        tee_print(log_f, "ERROR: mlx-whisper not installed")
        return {"segments": [], "text": ""}
    
    model_name = WHISPER_MODELS.get(language, WHISPER_MODELS["auto"])
    
    tee_print(log_f, f"  Model: {model_name}")
    tee_print(log_f, f"  Language: {language}")
    
    try:
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=model_name,
            language=None if language == "auto" else language,
            word_timestamps=word_timestamps,
            verbose=False
        )
        
        return result
        
    except Exception as e:
        tee_print(log_f, f"  ERROR: {e}")
        return {"segments": [], "text": ""}


def assign_speakers_to_segments(
    transcription_segments: list[dict],
    diarization_segments: list[dict],
    clip_offset: float = 0.0
) -> list[dict]:
    """
    Assign speaker labels to transcription segments based on diarization.
    """
    if not diarization_segments:
        # No diarization, return segments with unknown speaker
        result = []
        for seg in transcription_segments:
            result.append({
                "speaker": "SPEAKER_UNKNOWN",
                "start": format_timestamp(seg["start"]),
                "end": format_timestamp(seg["end"]),
                "text": seg["text"].strip()
            })
        return result
    
    result = []
    for seg in transcription_segments:
        seg_start = seg["start"] + clip_offset
        seg_end = seg["end"] + clip_offset
        seg_mid = (seg_start + seg_end) / 2
        
        # Find best matching speaker
        best_speaker = "SPEAKER_UNKNOWN"
        best_overlap = 0
        
        for diar_seg in diarization_segments:
            # Calculate overlap
            overlap_start = max(seg_start, diar_seg["start"])
            overlap_end = min(seg_end, diar_seg["end"])
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = diar_seg["speaker"]
        
        result.append({
            "speaker": best_speaker,
            "start": format_timestamp(seg["start"]),
            "end": format_timestamp(seg["end"]),
            "text": seg["text"].strip()
        })
    
    return result


def analyze_speakers(segments: list[dict]) -> list[dict]:
    """
    Analyze speakers and generate descriptions.
    """
    speaker_stats = {}
    
    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {
                "total_duration": 0,
                "segment_count": 0,
                "sample_texts": []
            }
        
        # Parse timestamps
        try:
            start_parts = seg["start"].split(":")
            end_parts = seg["end"].split(":")
            start_sec = float(start_parts[0]) * 3600 + float(start_parts[1]) * 60 + float(start_parts[2])
            end_sec = float(end_parts[0]) * 3600 + float(end_parts[1]) * 60 + float(end_parts[2])
            duration = end_sec - start_sec
        except:
            duration = 0
        
        speaker_stats[speaker]["total_duration"] += duration
        speaker_stats[speaker]["segment_count"] += 1
        
        if len(speaker_stats[speaker]["sample_texts"]) < 3:
            speaker_stats[speaker]["sample_texts"].append(seg["text"][:100])
    
    # Generate speaker info
    speakers = []
    for speaker_id, stats in sorted(speaker_stats.items()):
        speakers.append({
            "id": speaker_id,
            "total_speaking_time": format_duration(stats["total_duration"]),
            "segment_count": stats["segment_count"],
            "description": f"Speaker with {stats['segment_count']} segments, {format_duration(stats['total_duration'])} total speaking time",
            "sample_texts": stats["sample_texts"]
        })
    
    return speakers


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe audio with speaker diarization.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --language en
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --language ar
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" --skip-diarization
        """
    )
    ap.add_argument("--project", required=True, help="Project folder path")
    ap.add_argument("--audio-dir", default=DEFAULT_AUDIO_SUBDIR,
                   help=f'Audio folder relative to project (default: "{DEFAULT_AUDIO_SUBDIR}")')
    ap.add_argument("--out-dir", default=DEFAULT_TRANSCRIPT_SUBDIR,
                   help=f'Output folder relative to project (default: "{DEFAULT_TRANSCRIPT_SUBDIR}")')
    ap.add_argument("--language", choices=["en", "ar", "auto"], default="auto",
                   help="Audio language: en (English), ar (Arabic), auto (detect)")
    ap.add_argument("--hf-token", default=None,
                   help="HuggingFace token for pyannote (or set HF_TOKEN env var)")
    ap.add_argument("--num-speakers", type=int, default=None,
                   help="Number of speakers (if known, helps diarization)")
    ap.add_argument("--skip-diarization", action="store_true",
                   help="Skip speaker diarization (transcribe only)")
    ap.add_argument("--dry-run", action="store_true",
                   help="Print actions without processing")
    args = ap.parse_args()

    # Validate paths
    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project folder not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    audio_dir = (project_dir / args.audio_dir).resolve()
    if not audio_dir.exists():
        print(f"ERROR: Audio folder not found: {audio_dir}", file=sys.stderr)
        sys.exit(1)

    # Check dependencies
    if not HAS_MLX_WHISPER:
        print("ERROR: mlx-whisper not installed. Run: pip install mlx-whisper", file=sys.stderr)
        sys.exit(1)

    # Setup directories
    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = (project_dir / DEFAULT_LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Find audio files
    project_name = project_dir.name
    full_audio = audio_dir / f"{project_name}_FULL_AUDIO.wav"
    
    clip_wavs = [
        p for p in audio_dir.iterdir()
        if p.is_file() and p.suffix == ".wav" 
        and p.name.endswith("_AUDIO.wav")
        and not p.name.endswith("_FULL_AUDIO.wav")
    ]
    clip_wavs.sort(key=lambda p: natural_key(p.name))

    if not clip_wavs:
        print(f"ERROR: No audio clips found in: {audio_dir}", file=sys.stderr)
        sys.exit(1)

    # HuggingFace token
    import os
    hf_token = args.hf_token or os.environ.get("HF_TOKEN")

    # Generate paths
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"transcribe_{ts}.log"
    output_json = out_dir / "transcript_with_speakers.json"

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "TRANSCRIBE WITH SPEAKERS")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp   : {ts}")
        tee_print(log_f, f"Project     : {project_dir}")
        tee_print(log_f, f"Audio dir   : {audio_dir}")
        tee_print(log_f, f"Clip count  : {len(clip_wavs)}")
        tee_print(log_f, f"Language    : {args.language}")
        tee_print(log_f, f"Full audio  : {full_audio.name if full_audio.exists() else 'NOT FOUND'}")
        tee_print(log_f, f"Output      : {output_json}")
        tee_print(log_f, "")
        tee_print(log_f, f"MLX Whisper : {'✓' if HAS_MLX_WHISPER else '✗'}")
        tee_print(log_f, f"PyAnnote    : {'✓' if HAS_PYANNOTE else '✗'}")
        tee_print(log_f, f"HF Token    : {'✓' if hf_token else '✗ (diarization may fail)'}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN MODE")
            tee_print(log_f, "")
            tee_print(log_f, "Would process:")
            for i, wav in enumerate(clip_wavs, 1):
                tee_print(log_f, f"  {i}. {wav.name}")
            return

        # ============================================================
        # PHASE 1: Speaker Diarization (on full audio)
        # ============================================================
        diarization_segments = []
        
        if args.skip_diarization:
            tee_print(log_f, "PHASE 1: Speaker diarization SKIPPED")
        elif not full_audio.exists():
            tee_print(log_f, "PHASE 1: Speaker diarization SKIPPED (no full audio)")
        elif not HAS_PYANNOTE:
            tee_print(log_f, "PHASE 1: Speaker diarization SKIPPED (pyannote not installed)")
        elif not hf_token:
            tee_print(log_f, "PHASE 1: Speaker diarization SKIPPED (no HF token)")
        else:
            tee_print(log_f, "PHASE 1: Speaker Diarization")
            tee_print(log_f, "-" * 40)
            
            duration = get_audio_duration(full_audio)
            tee_print(log_f, f"Full audio duration: {format_duration(duration)}")
            
            diarization_segments = run_speaker_diarization(
                full_audio,
                hf_token,
                log_f,
                num_speakers=args.num_speakers
            )
            
            tee_print(log_f, f"Diarization segments: {len(diarization_segments)}")
            tee_print(log_f, "")

        # ============================================================
        # PHASE 2: Transcribe each clip
        # ============================================================
        tee_print(log_f, "PHASE 2: Transcription")
        tee_print(log_f, "-" * 40)
        
        all_clips_data = []
        cumulative_offset = 0.0  # Track position in full audio
        
        for i, wav_path in enumerate(clip_wavs, 1):
            # Get source video name
            source_video = wav_path.stem.replace("_AUDIO", "") + ".MP4"
            
            tee_print(log_f, f"[{i:3d}/{len(clip_wavs)}] {wav_path.name}")
            
            # Get clip duration
            clip_duration = get_audio_duration(wav_path)
            tee_print(log_f, f"  Duration: {format_duration(clip_duration)}")
            
            # Transcribe
            result = transcribe_audio(wav_path, args.language, log_f)
            
            segments = result.get("segments", [])
            tee_print(log_f, f"  Segments: {len(segments)}")
            
            # Assign speakers
            segments_with_speakers = assign_speakers_to_segments(
                segments,
                diarization_segments,
                clip_offset=cumulative_offset
            )
            
            # Build clip data
            clip_data = {
                "source_file": source_video,
                "audio_file": wav_path.name,
                "duration": format_duration(clip_duration),
                "offset_in_full": format_timestamp(cumulative_offset),
                "segments": segments_with_speakers
            }
            
            all_clips_data.append(clip_data)
            cumulative_offset += clip_duration
            
            tee_print(log_f, f"  OK")

        tee_print(log_f, "")

        # ============================================================
        # PHASE 3: Analyze speakers and save
        # ============================================================
        tee_print(log_f, "PHASE 3: Generating output")
        tee_print(log_f, "-" * 40)
        
        # Collect all segments for speaker analysis
        all_segments = []
        for clip in all_clips_data:
            all_segments.extend(clip["segments"])
        
        speakers_info = analyze_speakers(all_segments)
        
        # Build final output
        output_data = {
            "project": project_name,
            "generated_at": datetime.now().isoformat(),
            "language": args.language,
            "total_clips": len(clip_wavs),
            "total_duration": format_duration(cumulative_offset),
            "speakers": speakers_info,
            "clips": all_clips_data
        }
        
        # Save JSON
        with output_json.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        tee_print(log_f, f"Speakers detected: {len(speakers_info)}")
        for sp in speakers_info:
            tee_print(log_f, f"  - {sp['id']}: {sp['total_speaking_time']} ({sp['segment_count']} segments)")
        
        tee_print(log_f, "")
        tee_print(log_f, f"Output saved: {output_json}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog saved: {log_path}")
    print(f"Transcript: {output_json}")


if __name__ == "__main__":
    main()
