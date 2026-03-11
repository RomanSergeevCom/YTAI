#!/usr/bin/env python3
"""
Audio Transcription Script with Speaker Diarization
Transcribes audio files and identifies different speakers.

Requirements:
    pip install openai-whisper pyannote.audio torch torchaudio

For pyannote.audio, you need a Hugging Face token:
    1. Create account at huggingface.co
    2. Accept terms at: https://huggingface.co/pyannote/speaker-diarization-3.1
    3. Accept terms at: https://huggingface.co/pyannote/segmentation-3.0
    4. Create token at: https://huggingface.co/settings/tokens
    5. Put token in /Users/romansergeev/YTAI/config/.env

Usage:
    python transcribe_with_speakers.py <audio_file> [--model large]
"""

import argparse
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Load config file
def load_env():
    config_file = Path("/Users/romansergeev/YTAI/config/HuggingFace-yt-prod.conf")
    
    if not config_file.exists():
        print(f"WARNING: Config file not found: {config_file}")
        print("Create it with:")
        print("  mkdir -p /Users/romansergeev/YTAI/config")
        print("  echo '# HuggingFace token' > /Users/romansergeev/YTAI/config/yt-prod.conf")
        print("  echo 'HF_TOKEN=hf_your_token' >> /Users/romansergeev/YTAI/config/yt-prod.conf")
        return
    
    with open(config_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()
    
    # Verify token loaded
    if os.environ.get("HF_TOKEN"):
        print(f"✓ HF_TOKEN loaded from {config_file}")
    else:
        print(f"WARNING: HF_TOKEN not found in {config_file}")

load_env()


def get_project_paths(audio_path: str) -> dict:
    """
    Extract project root from audio path and return output directories.
    Expected structure: /Volumes/RYA Blue/YTCG38_Coffee/01_Raw/01_02_Audio/file.wav
    Project root: /Volumes/RYA Blue/YTCG38_Coffee/
    """
    audio_path = Path(audio_path)
    
    # Navigate up to find project root (parent of 01_Raw)
    current = audio_path.parent
    while current.name != "01_Raw" and current != current.parent:
        current = current.parent
    
    if current.name == "01_Raw":
        project_root = current.parent
    else:
        # Fallback: use audio file's grandparent directory
        project_root = audio_path.parent.parent.parent
    
    return {
        "project_root": project_root,
        "project_name": project_root.name,
        "logs_dir": project_root / "08_Logs",
        "transcripts_dir": project_root / "02_Transcripts" / "02_01_Runs"
    }


def setup_logging(logs_dir: Path, project_name: str) -> logging.Logger:
    """Setup logging to both file and console."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{project_name}_transcribe_{timestamp}.log"
    
    # Create logger
    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.DEBUG)
    
    # File handler (detailed)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(file_format)
    
    # Console handler (info only)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("%(message)s")
    console_handler.setFormatter(console_format)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logger.info(f"Log file: {log_file}")
    
    return logger


def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS.mmm format."""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    milliseconds = int((seconds - total_seconds) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def transcribe_audio(audio_path: str, model_size: str, logger: logging.Logger) -> dict:
    """Transcribe audio using Whisper."""
    import whisper
    
    try:
        logger.info(f"Loading Whisper model ({model_size})...")
        model = whisper.load_model(model_size)
        
        logger.info("Transcribing audio...")
        result = model.transcribe(
            audio_path,
            language="en",
            word_timestamps=True,
            verbose=False
        )
        
        return result
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)


def perform_diarization(audio_path: str, num_speakers: int, logger: logging.Logger) -> list:
    """Perform speaker diarization using pyannote.audio."""
    from pyannote.audio import Pipeline
    import torch
    import soundfile as sf
    
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.error("HF_TOKEN not set. Pyannote requires a Hugging Face token.")
        logger.error("Put token in /Users/romansergeev/YTAI/config/HuggingFace-yt-prod.conf")
        sys.exit(1)
    
    logger.info("Loading diarization pipeline...")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=hf_token
        )
    except Exception as e:
        logger.error(f"Failed to load diarization pipeline: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
    
    # Use GPU if available
    if torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        logger.info("Using GPU for diarization")
    else:
        logger.info("Using CPU for diarization")
    
    # Load audio with soundfile to bypass torchcodec issue
    logger.info("Loading audio file...")
    try:
        waveform, sample_rate = sf.read(audio_path, dtype='float32')
        waveform = torch.from_numpy(waveform)
        if waveform.ndim == 1:
            waveform = waveform.unsqueeze(0)  # mono -> (1, time)
        else:
            waveform = waveform.T  # (time, channels) -> (channels, time)
        
        audio_input = {"waveform": waveform, "sample_rate": sample_rate}
        logger.debug(f"Audio loaded: shape={waveform.shape}, sample_rate={sample_rate}")
    except Exception as e:
        logger.error(f"Failed to load audio: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
    
    logger.info("Performing speaker diarization...")
    try:
        if num_speakers:
            diarization = pipeline(audio_input, num_speakers=num_speakers)
        else:
            diarization = pipeline(audio_input)
    except Exception as e:
        logger.error(f"Diarization failed: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)
    
    # Convert to list of segments
    # Handle both pyannote.audio 3.x and 4.x API
    segments = []
    
    # Check if it's the new DiarizeOutput format (pyannote 4.x)
    if hasattr(diarization, 'itertracks'):
        # pyannote.audio 3.x format
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })
    elif hasattr(diarization, 'speakers') and hasattr(diarization, 'chunks'):
        # pyannote.audio 4.x DiarizeOutput format
        logger.debug(f"DiarizeOutput speakers: {diarization.speakers}")
        logger.debug(f"DiarizeOutput chunks: {len(diarization.chunks)} chunks")
        
        # diarization.chunks is a list of Chunk objects with start, end, speaker
        for chunk in diarization.chunks:
            segments.append({
                "start": chunk.start,
                "end": chunk.end,
                "speaker": chunk.speaker
            })
    else:
        # Try to iterate directly (some versions return iterable)
        logger.warning(f"Unknown diarization output type: {type(diarization)}")
        logger.debug(f"Diarization attributes: {dir(diarization)}")
        
        # Attempt fallback: check if it's directly iterable
        try:
            for item in diarization:
                if hasattr(item, 'start') and hasattr(item, 'end') and hasattr(item, 'speaker'):
                    segments.append({
                        "start": item.start,
                        "end": item.end,
                        "speaker": item.speaker
                    })
                elif isinstance(item, dict):
                    segments.append({
                        "start": item.get('start', 0),
                        "end": item.get('end', 0),
                        "speaker": item.get('speaker', 'UNKNOWN')
                    })
        except TypeError:
            logger.error(f"Cannot iterate over diarization output: {type(diarization)}")
            logger.error(f"Available attributes: {dir(diarization)}")
            sys.exit(1)
    
    logger.info(f"Extracted {len(segments)} diarization segments")
    return segments


def assign_speakers_to_words(transcription: dict, diarization: list) -> list:
    """Assign speakers to transcribed segments based on diarization."""
    result = []
    
    for segment in transcription.get("segments", []):
        seg_start = segment["start"]
        seg_end = segment["end"]
        seg_mid = (seg_start + seg_end) / 2
        
        # Find the speaker for this segment
        speaker = "UNKNOWN"
        for diar_seg in diarization:
            if diar_seg["start"] <= seg_mid <= diar_seg["end"]:
                speaker = diar_seg["speaker"]
                break
        
        result.append({
            "start": seg_start,
            "end": seg_end,
            "speaker": speaker,
            "text": segment["text"].strip()
        })
    
    return result


def merge_consecutive_segments(segments: list) -> list:
    """Merge consecutive segments from the same speaker."""
    if not segments:
        return []
    
    merged = [segments[0].copy()]
    
    for segment in segments[1:]:
        if segment["speaker"] == merged[-1]["speaker"]:
            # Same speaker, merge
            merged[-1]["end"] = segment["end"]
            merged[-1]["text"] += " " + segment["text"]
        else:
            merged.append(segment.copy())
    
    return merged


def format_transcript(segments: list, speakers: set, audio_path: str) -> str:
    """Format the transcript for output."""
    lines = []
    lines.append("=" * 60)
    lines.append("AUDIO TRANSCRIPTION WITH SPEAKER DIARIZATION")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Source: {audio_path}")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Number of speakers detected: {len(speakers)}")
    lines.append(f"Speakers: {', '.join(sorted(speakers))}")
    lines.append("")
    lines.append("-" * 60)
    lines.append("TRANSCRIPT")
    lines.append("-" * 60)
    lines.append("")
    
    for segment in segments:
        timestamp = format_timestamp(segment["start"])
        speaker = segment["speaker"]
        text = segment["text"]
        lines.append(f"[{timestamp}] {speaker}:")
        lines.append(f"  {text}")
        lines.append("")
    
    return "\n".join(lines)


def save_json(segments: list, speakers: set, output_path: Path, audio_path: str):
    """Save transcript as JSON."""
    data = {
        "source": str(audio_path),
        "generated": datetime.now().isoformat(),
        "num_speakers": len(speakers),
        "speakers": sorted(list(speakers)),
        "segments": segments
    }
    
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return json_path


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe audio with speaker diarization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "audio_file",
        nargs="?",
        help="Path to the audio file"
    )
    parser.add_argument(
        "--project", "-p",
        help="Path to the audio file (alternative to positional argument)"
    )
    parser.add_argument(
        "--model", "-m",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper model size (default: medium)"
    )
    parser.add_argument(
        "--num-speakers", "-n",
        type=int,
        help="Number of speakers (auto-detected if not specified)"
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Don't merge consecutive segments from the same speaker"
    )
    
    args = parser.parse_args()
    
    # Get audio path from either --project or positional argument
    audio_path = args.project or args.audio_file
    
    if not audio_path:
        print("Error: Please provide an audio file path")
        print("Usage: python transcribe_with_speakers.py <audio_file>")
        print("   or: python transcribe_with_speakers.py --project <audio_file>")
        sys.exit(1)
    
    # Validate input file
    if not os.path.exists(audio_path):
        print(f"Error: File not found: {audio_path}")
        sys.exit(1)
    
    # Get project paths
    paths = get_project_paths(audio_path)
    
    # Create output directories
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)
    paths["transcripts_dir"].mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    logger = setup_logging(paths["logs_dir"], paths["project_name"])
    
    # Set output path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(audio_path).stem
    output_path = paths["transcripts_dir"] / f"{base_name}_{timestamp}.txt"
    
    logger.info("=" * 60)
    logger.info("TRANSCRIPTION STARTED")
    logger.info("=" * 60)
    logger.info(f"Project: {paths['project_name']}")
    logger.info(f"Input: {audio_path}")
    logger.info(f"Output: {output_path}")
    logger.info(f"Model: {args.model}")
    
    # Log system info
    import platform
    logger.debug(f"Python: {platform.python_version()}")
    logger.debug(f"Platform: {platform.platform()}")
    try:
        import torch
        logger.debug(f"PyTorch: {torch.__version__}")
        logger.debug(f"CUDA available: {torch.cuda.is_available()}")
    except:
        pass
    try:
        import whisper
        logger.debug(f"Whisper version: {whisper.__version__}")
    except:
        pass
    
    logger.info("")
    
    # Step 1: Transcribe audio
    transcription = transcribe_audio(audio_path, args.model, logger)
    num_segments = len(transcription.get('segments', []))
    logger.info(f"Transcription complete. {num_segments} segments found.")
    logger.info("")
    
    # Step 2: Perform diarization
    diarization = perform_diarization(audio_path, args.num_speakers, logger)
    speakers = set(seg["speaker"] for seg in diarization)
    logger.info(f"Diarization complete. {len(speakers)} speakers detected.")
    logger.info("")
    
    # Step 3: Assign speakers to transcribed segments
    segments = assign_speakers_to_words(transcription, diarization)
    
    # Step 4: Optionally merge consecutive segments
    if not args.no_merge:
        segments = merge_consecutive_segments(segments)
        logger.debug(f"Merged to {len(segments)} segments")
    
    # Step 5: Format and save output
    transcript = format_transcript(segments, speakers, audio_path)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)
    
    logger.info(f"Transcript saved to: {output_path}")
    
    # Also save as JSON
    json_path = save_json(segments, speakers, output_path, audio_path)
    logger.info(f"JSON saved to: {json_path}")
    
    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Number of speakers: {len(speakers)}")
    logger.info(f"Speakers: {', '.join(sorted(speakers))}")
    logger.info(f"Total segments: {len(segments)}")
    logger.info("")
    
    # Print first few segments as preview
    logger.info("Preview (first 3 segments):")
    logger.info("-" * 40)
    for segment in segments[:3]:
        logger.info(f"[{format_timestamp(segment['start'])}] {segment['speaker']}:")
        text_preview = segment['text'][:100] + "..." if len(segment['text']) > 100 else segment['text']
        logger.info(f"  {text_preview}")
        logger.info("")
    
    logger.info("=" * 60)
    logger.info("TRANSCRIPTION COMPLETE")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
