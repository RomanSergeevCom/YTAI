#!/usr/bin/env python3
"""
YTAI Step 1: Project Transcription
Transcription + Speaker Diarization (without naming)

This script processes the FULL_AUDIO.wav file from a project folder,
performs transcription with Whisper and speaker diarization with pyannote.

Step 2 (process_transcript.py) will:
- Name speakers via LLM
- Split transcript by video clips
- Generate per-clip SRT files

Usage:
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" -n 3

Output:
    02_Transcripts/02_01_Runs/
    â”œâ”€â”€ YTCG37_Hadi_Dawani_transcript_YYYYMMDD_HHMMSS.json
    â””â”€â”€ YTCG37_Hadi_Dawani_transcript_YYYYMMDD_HHMMSS.txt
    
    Project root:
    â””â”€â”€ speaker_names.json (template for manual editing or LLM)

Requirements:
    pip install openai-whisper pyannote.audio torch torchaudio soundfile
"""

import argparse
import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Set

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = Path("/Users/romansergeev/YTAI/config/HuggingFace-yt-prod.conf")

# Project structure
VIDEO_DIR = "01_Raw/01_01_Video"
AUDIO_DIR = "01_Raw/01_02_Audio"
TRANSCRIPTS_DIR = "02_Transcripts/02_01_Runs"
TRANSCRIPTS_CLEAN_DIR = "02_Transcripts/02_02_Clean"
LOGS_DIR = "08_Logs"

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}


def load_env():
    """Load HuggingFace token from config."""
    if not CONFIG_FILE.exists():
        print(f"âš  Config not found: {CONFIG_FILE}")
        return
    
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()
    
    if os.environ.get("HF_TOKEN"):
        print("âœ“ HF_TOKEN loaded")

load_env()


# ============================================================================
# Project Paths
# ============================================================================

def get_project_paths(project_dir: str) -> dict:
    """Get all relevant paths for a project."""
    project_root = Path(project_dir).expanduser().resolve()
    
    if not project_root.exists():
        raise FileNotFoundError(f"Project folder not found: {project_root}")
    
    project_name = project_root.name
    
    # Find FULL_AUDIO.wav
    audio_dir = project_root / AUDIO_DIR
    full_audio = audio_dir / f"{project_name}_FULL_AUDIO.wav"
    
    if not full_audio.exists():
        # Try to find any *_FULL_AUDIO.wav
        candidates = list(audio_dir.glob("*_FULL_AUDIO.wav"))
        if candidates:
            full_audio = candidates[0]
        else:
            raise FileNotFoundError(f"FULL_AUDIO.wav not found in {audio_dir}")
    
    return {
        "project_root": project_root,
        "project_name": project_name,
        "video_dir": project_root / VIDEO_DIR,
        "audio_dir": audio_dir,
        "full_audio": full_audio,
        "transcripts_dir": project_root / TRANSCRIPTS_DIR,
        "transcripts_clean_dir": project_root / TRANSCRIPTS_CLEAN_DIR,
        "logs_dir": project_root / LOGS_DIR,
        "speaker_map_file": project_root / TRANSCRIPTS_CLEAN_DIR / "speaker_names.json"
    }


# ============================================================================
# Logging
# ============================================================================

def setup_logging(logs_dir: Path, project_name: str) -> logging.Logger:
    """Setup dual logging to file and console."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{project_name}_transcribe_project_{timestamp}.log"
    
    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    logger.info(f"Log: {log_file}")
    
    return logger


# ============================================================================
# Timestamp Formatting
# ============================================================================

def format_timestamp(seconds: float) -> str:
    """Format as HH:MM:SS.mmm"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# ============================================================================
# Whisper Transcription
# ============================================================================

def transcribe_audio(audio_path: str, model_size: str, language: str, logger: logging.Logger) -> dict:
    """Transcribe audio with Whisper."""
    import whisper
    
    logger.info(f"Loading Whisper ({model_size})...")
    model = whisper.load_model(model_size)
    
    logger.info("Transcribing...")
    opts = {"word_timestamps": True, "verbose": False}
    if language and language.lower() != "auto":
        opts["language"] = language
    
    result = model.transcribe(str(audio_path), **opts)
    detected = result.get("language", "unknown")
    logger.info(f"Detected language: {detected}")
    
    return result


# ============================================================================
# Pyannote Diarization
# ============================================================================

def perform_diarization(audio_path: str, num_speakers: Optional[int], logger: logging.Logger) -> List[dict]:
    """Speaker diarization with pyannote.audio."""
    from pyannote.audio import Pipeline
    import torch
    import soundfile as sf
    
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.error("HF_TOKEN not set!")
        sys.exit(1)
    
    logger.info("Loading diarization pipeline...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token
    )
    
    # Select device
    if torch.backends.mps.is_available():
        pipeline.to(torch.device("mps"))
        logger.info("Using MPS (Apple Silicon)")
    elif torch.cuda.is_available():
        pipeline.to(torch.device("cuda"))
        logger.info("Using CUDA")
    else:
        logger.info("Using CPU")
    
    # Load audio
    logger.info("Loading audio...")
    waveform, sample_rate = sf.read(str(audio_path), dtype='float32')
    waveform = torch.from_numpy(waveform)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    else:
        waveform = waveform.T
    
    audio_input = {"waveform": waveform, "sample_rate": sample_rate}
    
    # Run diarization
    logger.info("Running diarization...")
    opts = {}
    if num_speakers:
        opts["num_speakers"] = num_speakers
    
    output = pipeline(audio_input, **opts)
    
    # Extract segments (pyannote 4.x API)
    segments = []
    if hasattr(output, 'speaker_diarization'):
        for turn, speaker in output.speaker_diarization:
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": f"SPEAKER_{speaker}" if isinstance(speaker, int) else str(speaker)
            })
    elif hasattr(output, 'itertracks'):
        for turn, _, speaker in output.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })
    
    logger.info(f"Diarization complete: {len(segments)} segments")
    return segments


# ============================================================================
# Combine Transcription with Speakers
# ============================================================================

def assign_speakers(transcription: dict, diarization: List[dict]) -> List[dict]:
    """Assign speaker labels to transcription segments."""
    result = []
    
    for seg in transcription.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_mid = (seg_start + seg_end) / 2
        
        # Find speaker by maximum overlap
        speaker = "UNKNOWN"
        best_overlap = 0
        
        for d in diarization:
            overlap_start = max(seg_start, d["start"])
            overlap_end = min(seg_end, d["end"])
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                speaker = d["speaker"]
        
        # Fallback: check midpoint
        if speaker == "UNKNOWN":
            for d in diarization:
                if d["start"] <= seg_mid <= d["end"]:
                    speaker = d["speaker"]
                    break
        
        result.append({
            "start": seg_start,
            "end": seg_end,
            "speaker": speaker,
            "text": text
        })
    
    return result


def merge_consecutive(segments: List[dict], max_gap: float = 1.0) -> List[dict]:
    """Merge consecutive segments from same speaker."""
    if not segments:
        return []
    
    merged = [segments[0].copy()]
    
    for seg in segments[1:]:
        last = merged[-1]
        gap = seg["start"] - last["end"]
        
        if seg["speaker"] == last["speaker"] and gap <= max_gap:
            last["end"] = seg["end"]
            last["text"] += " " + seg["text"]
        else:
            merged.append(seg.copy())
    
    return merged


# ============================================================================
# Output Writers
# ============================================================================

def save_txt(segments: List[dict], speakers: Set[str], paths: dict, 
             output_path: Path, metadata: dict):
    """Save human-readable transcript."""
    lines = [
        "=" * 60,
        "PROJECT TRANSCRIPTION",
        "=" * 60,
        "",
        f"Project: {paths['project_name']}",
        f"Source: {paths['full_audio']}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Language: {metadata.get('language', 'unknown')}",
        f"Model: {metadata.get('model', 'unknown')}",
        f"Speakers ({len(speakers)}): {', '.join(sorted(speakers))}",
        "",
        "NOTE: Run process_transcript.py to:",
        "  - Name speakers via LLM",
        "  - Split by video clips",
        "  - Generate per-clip SRT files",
        "",
        "-" * 60,
        "TRANSCRIPT",
        "-" * 60,
        ""
    ]
    
    for seg in segments:
        ts = format_timestamp(seg["start"])
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "")
        lines.append(f"[{ts}] {speaker}:")
        lines.append(f"  {text}")
        lines.append("")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def save_json(segments: List[dict], speakers: Set[str], paths: dict,
              output_path: Path, metadata: dict) -> Path:
    """Save machine-readable JSON."""
    data = {
        "project_name": paths["project_name"],
        "source": str(paths["full_audio"]),
        "generated": datetime.now().isoformat(),
        "language": metadata.get("language"),
        "model": metadata.get("model"),
        "num_speakers": len(speakers),
        "speakers": sorted(list(speakers)),
        "total_segments": len(segments),
        "segments": segments
    }
    
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return json_path


def save_srt(segments: List[dict], output_path: Path) -> Path:
    """Save SRT subtitle file."""
    lines = []
    idx = 1
    
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        start = seg["start"]
        end = seg["end"]
        speaker = seg.get("speaker", "UNKNOWN")
        
        # Format timestamps for SRT: HH:MM:SS,mmm
        def fmt(seconds):
            h, r = divmod(int(seconds), 3600)
            m, s = divmod(r, 60)
            ms = int((seconds - int(seconds)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        
        lines.append(str(idx))
        lines.append(f"{fmt(start)} --> {fmt(end)}")
        lines.append(f"[{speaker}] {text}")
        lines.append("")
        idx += 1
    
    srt_path = output_path.with_suffix(".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return srt_path


def save_speaker_template(speakers: Set[str], output_path: Path) -> Path:
    """Create speaker_names.json template for manual editing or LLM."""
    template = {}
    for s in sorted(speakers):
        if s != "UNKNOWN":
            template[s] = s  # Default: same as ID
    
    # Don't overwrite if exists
    if output_path.exists():
        return output_path
    
    with open(output_path, "w") as f:
        json.dump(template, f, indent=2)
    
    return output_path


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI Step 1: Project Transcription",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" -n 3
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" -m medium
        """
    )
    
    parser.add_argument("--project", required=True,
                        help="Project folder path")
    parser.add_argument("-m", "--model", default="large-v3",
                        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                        help="Whisper model (default: large-v3)")
    parser.add_argument("-l", "--language", default="auto",
                        help="Language code or 'auto' (default: auto)")
    parser.add_argument("-n", "--num-speakers", type=int,
                        help="Number of speakers (improves diarization accuracy)")
    parser.add_argument("--no-merge", action="store_true",
                        help="Don't merge consecutive segments from same speaker")
    
    args = parser.parse_args()
    
    # Get project paths
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Setup directories
    paths["transcripts_dir"].mkdir(parents=True, exist_ok=True)
    paths["transcripts_clean_dir"].mkdir(parents=True, exist_ok=True)
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    logger = setup_logging(paths["logs_dir"], paths["project_name"])
    
    # Generate output filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = paths["transcripts_dir"] / f"{paths['project_name']}_transcript_{timestamp}"
    
    # Header
    logger.info("=" * 60)
    logger.info("YTAI STEP 1: PROJECT TRANSCRIPTION")
    logger.info("=" * 60)
    logger.info(f"Project: {paths['project_name']}")
    logger.info(f"Audio: {paths['full_audio']}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Language: {args.language}")
    if args.num_speakers:
        logger.info(f"Expected speakers: {args.num_speakers}")
    logger.info("")
    
    # Step 1: Transcribe
    logger.info("PHASE 1: Transcription")
    logger.info("-" * 40)
    transcription = transcribe_audio(
        paths["full_audio"], 
        args.model, 
        args.language, 
        logger
    )
    detected_lang = transcription.get("language", "unknown")
    logger.info(f"Transcription complete: {len(transcription.get('segments', []))} segments")
    logger.info("")
    
    # Step 2: Diarization
    logger.info("PHASE 2: Speaker Diarization")
    logger.info("-" * 40)
    diarization = perform_diarization(
        paths["full_audio"],
        args.num_speakers,
        logger
    )
    logger.info("")
    
    # Step 3: Combine
    logger.info("PHASE 3: Combining Results")
    logger.info("-" * 40)
    segments = assign_speakers(transcription, diarization)
    logger.info(f"Combined: {len(segments)} segments")
    
    # Merge consecutive
    if not args.no_merge:
        segments = merge_consecutive(segments)
        logger.info(f"After merge: {len(segments)} segments")
    
    # Get unique speakers
    speakers = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers.discard("UNKNOWN")
    logger.info(f"Speakers found: {', '.join(sorted(speakers))}")
    logger.info("")
    
    # Metadata
    metadata = {
        "language": detected_lang,
        "model": args.model
    }
    
    # Step 4: Save outputs
    logger.info("PHASE 4: Saving Results")
    logger.info("-" * 40)
    
    txt_path = output_base.with_suffix(".txt")
    save_txt(segments, speakers, paths, txt_path, metadata)
    logger.info(f"TXT: {txt_path}")
    
    json_path = save_json(segments, speakers, paths, output_base, metadata)
    logger.info(f"JSON: {json_path}")
    
    srt_path = save_srt(segments, output_base)
    logger.info(f"SRT: {srt_path}")
    
    template_path = save_speaker_template(speakers, paths["speaker_map_file"])
    logger.info(f"Speaker template: {template_path}")
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("STEP 1 COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Language: {detected_lang}")
    logger.info(f"Speakers: {len(speakers)}")
    logger.info(f"Segments: {len(segments)}")
    
    if segments:
        duration = segments[-1].get("end", 0)
        logger.info(f"Duration: {format_timestamp(duration)}")
    
    logger.info("")
    logger.info("Next step:")
    logger.info(f"  python process_transcript.py --project \"{paths['project_root']}\"")
    logger.info("")
    logger.info("Preview:")
    for seg in segments[:5]:
        ts = format_timestamp(seg["start"])
        spk = seg.get("speaker", "?")
        txt = seg.get("text", "")[:50]
        logger.info(f"  [{ts}] {spk}: {txt}...")


if __name__ == "__main__":
    main()
