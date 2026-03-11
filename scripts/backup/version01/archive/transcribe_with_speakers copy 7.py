#!/usr/bin/env python3
"""
Transcribe audio files with speaker diarization.

v6 - Two-pass transcription for EN+AR mixed content

Usage:
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG38_Coffee"
    python transcribe_with_speakers.py --project "/Volumes/RYA Blue/YTCG38_Coffee" --num-speakers 2

Requirements:
    pip install openai-whisper pyannote.audio soundfile
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Check imports
try:
    import whisper
    HAS_WHISPER = True
except ImportError:
    HAS_WHISPER = False

try:
    from pyannote.audio import Pipeline as PyannotePipeline
    HAS_PYANNOTE = True
except ImportError:
    HAS_PYANNOTE = False


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
        size = wav_path.stat().st_size
        return (size - 44) / 192000


def run_speaker_diarization(
    audio_path: Path,
    log_f,
    num_speakers: Optional[int] = None
) -> list[dict]:
    """Run speaker diarization using PyAnnote."""
    if not HAS_PYANNOTE:
        tee_print(log_f, "WARNING: pyannote.audio not installed")
        return []
    
    tee_print(log_f, "Loading pyannote speaker diarization model...")
    tee_print(log_f, "Model: pyannote/speaker-diarization-3.1")
    
    try:
        import torch
        import torchaudio
        
        # Load audio manually to avoid AudioDecoder issues
        tee_print(log_f, f"Loading audio: {audio_path.name}")
        waveform, sample_rate = torchaudio.load(str(audio_path))
        
        # Resample to 16kHz if needed (PyAnnote expects 16kHz)
        if sample_rate != 16000:
            tee_print(log_f, f"Resampling from {sample_rate}Hz to 16000Hz...")
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
            sample_rate = 16000
        
        # Convert to mono if stereo
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        
        # Load pipeline
        pipeline = PyannotePipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1"
        )
        
        # Use MPS (Apple Silicon GPU) if available
        if torch.backends.mps.is_available():
            pipeline = pipeline.to(torch.device("mps"))
            tee_print(log_f, "Using Apple Silicon GPU (MPS)")
        else:
            tee_print(log_f, "Using CPU")
        
        tee_print(log_f, "Running diarization...")
        tee_print(log_f, "This may take 10-20 minutes for long audio...")
        
        # Run diarization with pre-loaded audio
        audio_dict = {"waveform": waveform, "sample_rate": sample_rate}
        
        if num_speakers:
            tee_print(log_f, f"Expected speakers: {num_speakers}")
            diarization = pipeline(audio_dict, num_speakers=num_speakers)
        else:
            diarization = pipeline(audio_dict)
        
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
        tee_print(log_f, "")
        tee_print(log_f, "TROUBLESHOOTING:")
        tee_print(log_f, "  1. pip install soundfile torchaudio")
        tee_print(log_f, "  2. Accept license: https://huggingface.co/pyannote/speaker-diarization-3.1")
        tee_print(log_f, "  3. Accept license: https://huggingface.co/pyannote/segmentation-3.0")
        return []


def get_text_score(text: str, language: str) -> float:
    """Score how likely text is in the given language."""
    if not text.strip():
        return 0.0
    
    # Count characters
    arabic_chars = len(re.findall(r'[\u0600-\u06FF]', text))
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    total_chars = len(text.replace(" ", ""))
    
    if total_chars == 0:
        return 0.0
    
    if language == "ar":
        return arabic_chars / total_chars
    elif language == "en":
        return latin_chars / total_chars
    else:
        return 0.5


def transcribe_two_pass(audio_path: Path, model, log_f) -> dict:
    """Transcribe with both EN and AR, pick best result."""
    
    results = {}
    
    # Pass 1: English
    try:
        result_en = model.transcribe(
            str(audio_path),
            language="en",
            word_timestamps=True,
            verbose=False
        )
        results["en"] = result_en
    except Exception as e:
        tee_print(log_f, f"    EN error: {e}")
        results["en"] = {"segments": [], "text": ""}
    
    # Pass 2: Arabic
    try:
        result_ar = model.transcribe(
            str(audio_path),
            language="ar",
            word_timestamps=True,
            verbose=False
        )
        results["ar"] = result_ar
    except Exception as e:
        tee_print(log_f, f"    AR error: {e}")
        results["ar"] = {"segments": [], "text": ""}
    
    # Score both results
    en_text = results["en"].get("text", "")
    ar_text = results["ar"].get("text", "")
    
    en_score = get_text_score(en_text, "en")
    ar_score = get_text_score(ar_text, "ar")
    
    # Pick winner based on character match
    if ar_score > 0.5:
        winner = "ar"
    elif en_score > 0.5:
        winner = "en"
    elif len(ar_text) > len(en_text) * 1.2:
        winner = "ar"  # Arabic text is significantly longer
    else:
        winner = "en"  # Default to English
    
    tee_print(log_f, f"    EN: {len(en_text):4d} chars, score={en_score:.2f}")
    tee_print(log_f, f"    AR: {len(ar_text):4d} chars, score={ar_score:.2f}")
    tee_print(log_f, f"    Winner: {winner.upper()}")
    
    result = results[winner]
    result["detected_language"] = winner
    return result


def assign_speakers_to_segments(
    transcription_segments: list[dict],
    diarization_segments: list[dict],
    clip_offset: float = 0.0
) -> list[dict]:
    """Assign speaker labels to transcription segments."""
    if not diarization_segments:
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
        
        best_speaker = "SPEAKER_UNKNOWN"
        best_overlap = 0
        
        for diar_seg in diarization_segments:
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


def analyze_speakers(all_segments: list[dict]) -> list[dict]:
    """Analyze speaker statistics."""
    speaker_stats = {}
    
    for seg in all_segments:
        speaker = seg.get("speaker", "UNKNOWN")
        if speaker not in speaker_stats:
            speaker_stats[speaker] = {
                "total_duration": 0,
                "segment_count": 0,
                "sample_texts": []
            }
        
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
        
        text = seg.get("text", "").strip()
        if len(text) > 20 and len(speaker_stats[speaker]["sample_texts"]) < 5:
            if re.search(r'[a-zA-Z\u0600-\u06FF]', text):
                speaker_stats[speaker]["sample_texts"].append(text[:150])
    
    speakers = []
    for speaker_id, stats in sorted(speaker_stats.items()):
        speakers.append({
            "id": speaker_id,
            "total_speaking_time": format_duration(stats["total_duration"]),
            "segment_count": stats["segment_count"],
            "description": f"Speaker with {stats['segment_count']} segments, {format_duration(stats['total_duration'])} total",
            "sample_texts": stats["sample_texts"]
        })
    
    return speakers


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Transcribe audio with speaker diarization (EN+AR two-pass).",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--project", required=True, help="Project folder path")
    ap.add_argument("--audio-dir", default=DEFAULT_AUDIO_SUBDIR)
    ap.add_argument("--out-dir", default=DEFAULT_TRANSCRIPT_SUBDIR)
    ap.add_argument("--whisper-model", default="large-v3",
                   help="Whisper model: tiny, base, small, medium, large, large-v3")
    ap.add_argument("--num-speakers", type=int, default=None,
                   help="Number of speakers (improves diarization)")
    ap.add_argument("--skip-diarization", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists():
        print(f"ERROR: Project not found: {project_dir}", file=sys.stderr)
        sys.exit(1)

    audio_dir = (project_dir / args.audio_dir).resolve()
    if not audio_dir.exists():
        print(f"ERROR: Audio folder not found: {audio_dir}", file=sys.stderr)
        sys.exit(1)

    if not HAS_WHISPER:
        print("ERROR: openai-whisper not installed. Run: pip install openai-whisper", file=sys.stderr)
        sys.exit(1)

    out_dir = (project_dir / args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = (project_dir / DEFAULT_LOGS_SUBDIR).resolve()
    logs_dir.mkdir(parents=True, exist_ok=True)

    project_name = project_dir.name
    full_audio = audio_dir / f"{project_name}_FULL_AUDIO.wav"
    
    # Get audio clips (exclude macOS hidden files)
    clip_wavs = [
        p for p in audio_dir.iterdir()
        if p.is_file() and p.suffix == ".wav" 
        and p.name.endswith("_AUDIO.wav")
        and not p.name.endswith("_FULL_AUDIO.wav")
        and not p.name.startswith("._")
    ]
    clip_wavs.sort(key=lambda p: natural_key(p.name))

    if not clip_wavs:
        print(f"ERROR: No audio clips found", file=sys.stderr)
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"transcribe_{ts}.log"
    output_json = out_dir / "transcript_with_speakers.json"
    
    if output_json.exists() and not args.overwrite:
        print(f"Output exists: {output_json}", file=sys.stderr)
        print("Use --overwrite to replace", file=sys.stderr)
        sys.exit(1)

    with log_path.open("w", encoding="utf-8") as log_f:
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "TRANSCRIBE WITH SPEAKERS v6 (EN+AR two-pass)")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, f"Timestamp   : {ts}")
        tee_print(log_f, f"Project     : {project_dir}")
        tee_print(log_f, f"Clip count  : {len(clip_wavs)}")
        tee_print(log_f, f"Whisper     : {args.whisper_model}")
        tee_print(log_f, f"Full audio  : {full_audio.name if full_audio.exists() else 'NOT FOUND'}")
        tee_print(log_f, "")
        tee_print(log_f, f"OpenAI Whisper : {'✓' if HAS_WHISPER else '✗'}")
        tee_print(log_f, f"PyAnnote       : {'✓' if HAS_PYANNOTE else '✗'}")
        tee_print(log_f, "")

        if args.dry_run:
            tee_print(log_f, "DRY RUN - would process:")
            for i, wav in enumerate(clip_wavs, 1):
                tee_print(log_f, f"  {i}. {wav.name}")
            return

        # PHASE 1: Speaker Diarization
        diarization_segments = []
        
        if args.skip_diarization:
            tee_print(log_f, "PHASE 1: Diarization SKIPPED (--skip-diarization)")
        elif not full_audio.exists():
            tee_print(log_f, "PHASE 1: Diarization SKIPPED (no full audio)")
        elif not HAS_PYANNOTE:
            tee_print(log_f, "PHASE 1: Diarization SKIPPED (pyannote not installed)")
        else:
            tee_print(log_f, "PHASE 1: Speaker Diarization")
            tee_print(log_f, "-" * 40)
            
            duration = get_audio_duration(full_audio)
            tee_print(log_f, f"Duration: {format_duration(duration)}")
            
            diarization_segments = run_speaker_diarization(
                full_audio, log_f, args.num_speakers
            )
            
            tee_print(log_f, f"Segments: {len(diarization_segments)}")
        
        tee_print(log_f, "")

        # PHASE 2: Load Whisper
        tee_print(log_f, "PHASE 2: Loading Whisper model")
        tee_print(log_f, "-" * 40)
        tee_print(log_f, f"Model: {args.whisper_model}")
        
        whisper_model = whisper.load_model(args.whisper_model)
        tee_print(log_f, "Model loaded!")
        tee_print(log_f, "")

        # PHASE 3: Transcription (two-pass EN+AR)
        tee_print(log_f, "PHASE 3: Transcription (EN+AR two-pass)")
        tee_print(log_f, "-" * 40)
        
        all_clips_data = []
        cumulative_offset = 0.0
        
        for i, wav_path in enumerate(clip_wavs, 1):
            source_video = wav_path.stem.replace("_AUDIO", "") + ".MP4"
            
            tee_print(log_f, f"[{i:3d}/{len(clip_wavs)}] {wav_path.name}")
            
            clip_duration = get_audio_duration(wav_path)
            tee_print(log_f, f"  Duration: {format_duration(clip_duration)}")
            
            # Two-pass transcription
            result = transcribe_two_pass(wav_path, whisper_model, log_f)
            segments = result.get("segments", [])
            detected_lang = result.get("detected_language", "unknown")
            
            tee_print(log_f, f"  Segments: {len(segments)}")
            
            segments_with_speakers = assign_speakers_to_segments(
                segments, diarization_segments, cumulative_offset
            )
            
            clip_data = {
                "source_file": source_video,
                "audio_file": wav_path.name,
                "duration": format_duration(clip_duration),
                "duration_seconds": round(clip_duration, 3),
                "detected_language": detected_lang,
                "offset_in_full": format_timestamp(cumulative_offset),
                "offset_seconds": round(cumulative_offset, 3),
                "segment_count": len(segments_with_speakers),
                "segments": segments_with_speakers
            }
            
            all_clips_data.append(clip_data)
            cumulative_offset += clip_duration
            tee_print(log_f, "  OK")

        tee_print(log_f, "")

        # PHASE 4: Output
        tee_print(log_f, "PHASE 4: Generating output")
        tee_print(log_f, "-" * 40)
        
        all_segments = []
        for clip in all_clips_data:
            all_segments.extend(clip["segments"])
        
        speakers_info = analyze_speakers(all_segments)
        
        output_data = {
            "project": project_name,
            "generated_at": datetime.now().isoformat(),
            "whisper_model": args.whisper_model,
            "total_clips": len(clip_wavs),
            "total_duration": format_duration(cumulative_offset),
            "total_segments": len(all_segments),
            "diarization_enabled": len(diarization_segments) > 0,
            "speakers": speakers_info,
            "clips": all_clips_data
        }
        
        with output_json.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        tee_print(log_f, f"Speakers: {len(speakers_info)}")
        for sp in speakers_info:
            tee_print(log_f, f"  - {sp['id']}: {sp['total_speaking_time']}")
        
        tee_print(log_f, "")
        tee_print(log_f, f"Output: {output_json}")
        tee_print(log_f, "")
        tee_print(log_f, "=" * 60)
        tee_print(log_f, "DONE")
        tee_print(log_f, "=" * 60)

    print(f"\nLog: {log_path}")
    print(f"Transcript: {output_json}")


if __name__ == "__main__":
    main()
