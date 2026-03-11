#!/usr/bin/env python3
"""
Transcribe audio with speaker diarization.

Based on working script: whisper + pyannote.audio

Usage:
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG38_Coffee"

Requirements:
    pip install openai-whisper pyannote.audio
    
PyAnnote Setup:
    1. Accept: https://huggingface.co/pyannote/speaker-diarization-3.1
    2. Accept: https://huggingface.co/pyannote/segmentation-3.0
    3. python -c "from huggingface_hub import login; login()"
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import whisper
from pyannote.audio import Pipeline


# Paths
DEFAULT_AUDIO_SUBDIR = "01_Raw/01_02_Audio"
DEFAULT_TRANSCRIPT_SUBDIR = "02_Transcripts/02_01_Runs"
DEFAULT_LOGS_SUBDIR = "08_Logs"


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def tee_print(log_f, msg: str) -> None:
    print(msg)
    if log_f:
        log_f.write(msg + "\n")
        log_f.flush()


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_audio_duration(wav_path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(wav_path)],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe audio with speaker diarization.")
    ap.add_argument("--project", required=True, help="Project folder path")
    ap.add_argument("--audio-dir", default=DEFAULT_AUDIO_SUBDIR)
    ap.add_argument("--out-dir", default=DEFAULT_TRANSCRIPT_SUBDIR)
    ap.add_argument("--whisper-model", default="large-v3")
    ap.add_argument("--skip-diarization", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    audio_dir = (project_dir / args.audio_dir).resolve()
    if not audio_dir.exists():
        print(f"ERROR: Audio folder not found: {audio_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = (project_dir / DEFAULT_LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    project_name = project_dir.name
    full_audio = audio_dir / f"{project_name}_FULL_AUDIO.wav"
    
    if not full_audio.exists():
        print(f"ERROR: Full audio not found: {full_audio}", file=sys.stderr)
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"transcribe_{ts}.log"
    output_json = out_dir / "transcript_with_speakers.json"
    output_txt = out_dir / "transcript_with_speakers.txt"
    
    if output_json.exists() and not args.overwrite:
        print(f"Output exists: {output_json}", file=sys.stderr)
        print("Use --overwrite to replace", file=sys.stderr)
        sys.exit(1)

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "TRANSCRIBE WITH SPEAKERS v7")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp : {ts}")
        tee_print(log_f, f"Project   : {project_dir}")
        tee_print(log_f, f"Audio     : {full_audio.name}")
        tee_print(log_f, f"Whisper   : {args.whisper_model}")
        tee_print(log_f, "")

        duration = get_audio_duration(full_audio)
        tee_print(log_f, f"Duration  : {format_duration(duration)}")
        tee_print(log_f, "")

        # PHASE 1: Load Whisper
        tee_print(log_f, "PHASE 1: Loading Whisper model...")
        tee_print(log_f, "-" * 40)
        model = whisper.load_model(args.whisper_model)
        tee_print(log_f, "Model loaded!")
        tee_print(log_f, "")

        # PHASE 2: Transcribe
        tee_print(log_f, "PHASE 2: Transcribing...")
        tee_print(log_f, "-" * 40)
        tee_print(log_f, "This may take a while for long audio...")
        
        result = model.transcribe(
            str(full_audio),
            language=None,  # Auto-detect
            word_timestamps=True
        )
        
        detected_lang = result.get("language", "unknown")
        segments = result.get("segments", [])
        tee_print(log_f, f"Language: {detected_lang}")
        tee_print(log_f, f"Segments: {len(segments)}")
        tee_print(log_f, "")

        # PHASE 3: Speaker Diarization
        diarization = None
        if args.skip_diarization:
            tee_print(log_f, "PHASE 3: Diarization SKIPPED")
        else:
            tee_print(log_f, "PHASE 3: Loading speaker diarization...")
            tee_print(log_f, "-" * 40)
            
            try:
                pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
                tee_print(log_f, "Model loaded!")
                
                tee_print(log_f, "Detecting speakers...")
                tee_print(log_f, "This may take 10-20 minutes...")
                diarization = pipeline(str(full_audio))
                
                speakers = set()
                for turn, _, spk in diarization.itertracks(yield_label=True):
                    speakers.add(spk)
                tee_print(log_f, f"Detected {len(speakers)} speakers: {', '.join(sorted(speakers))}")
                
            except Exception as e:
                tee_print(log_f, f"ERROR: {e}")
                tee_print(log_f, "Continuing without diarization...")
                diarization = None
        
        tee_print(log_f, "")

        # PHASE 4: Match speakers to segments
        tee_print(log_f, "PHASE 4: Matching speakers to text...")
        tee_print(log_f, "-" * 40)
        
        segments_with_speakers = []
        speaker_stats = {}
        
        for segment in segments:
            seg_start = segment["start"]
            seg_end = segment["end"]
            seg_text = segment["text"].strip()
            
            # Find speaker
            speaker = "UNKNOWN"
            if diarization:
                for turn, _, spk in diarization.itertracks(yield_label=True):
                    if turn.start <= seg_start < turn.end:
                        speaker = spk
                        break
            
            # Track stats
            if speaker not in speaker_stats:
                speaker_stats[speaker] = {"duration": 0, "count": 0, "samples": []}
            speaker_stats[speaker]["duration"] += seg_end - seg_start
            speaker_stats[speaker]["count"] += 1
            if len(speaker_stats[speaker]["samples"]) < 3 and len(seg_text) > 20:
                speaker_stats[speaker]["samples"].append(seg_text[:100])
            
            segments_with_speakers.append({
                "start": seg_start,
                "end": seg_end,
                "start_fmt": format_timestamp(seg_start),
                "end_fmt": format_timestamp(seg_end),
                "speaker": speaker,
                "text": seg_text
            })
        
        tee_print(log_f, f"Processed {len(segments_with_speakers)} segments")
        tee_print(log_f, "")

        # PHASE 5: Save output
        tee_print(log_f, "PHASE 5: Saving output...")
        tee_print(log_f, "-" * 40)
        
        # Build speakers info
        speakers_info = []
        for spk, stats in sorted(speaker_stats.items()):
            speakers_info.append({
                "id": spk,
                "total_speaking_time": format_duration(stats["duration"]),
                "segment_count": stats["count"],
                "sample_texts": stats["samples"]
            })
        
        # JSON output
        output_data = {
            "project": project_name,
            "generated_at": datetime.now().isoformat(),
            "audio_file": full_audio.name,
            "whisper_model": args.whisper_model,
            "detected_language": detected_lang,
            "total_duration": format_duration(duration),
            "total_segments": len(segments_with_speakers),
            "diarization_enabled": diarization is not None,
            "speakers": speakers_info,
            "segments": segments_with_speakers
        }
        
        with output_json.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        # TXT output (like the working example)
        with output_txt.open("w", encoding="utf-8") as f:
            for seg in segments_with_speakers:
                start = f"{int(seg['start']//60):02d}:{seg['start']%60:05.2f}"
                end = f"{int(seg['end']//60):02d}:{seg['end']%60:05.2f}"
                f.write(f"[{start} - {end}] {seg['speaker']}\n{seg['text']}\n\n")
        
        tee_print(log_f, f"Speakers: {len(speakers_info)}")
        for sp in speakers_info:
            tee_print(log_f, f"  - {sp['id']}: {sp['total_speaking_time']} ({sp['segment_count']} segments)")
        
        tee_print(log_f, "")
        tee_print(log_f, f"JSON: {output_json}")
        tee_print(log_f, f"TXT:  {output_txt}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog: {log_path}")


if __name__ == "__main__":
    main()
