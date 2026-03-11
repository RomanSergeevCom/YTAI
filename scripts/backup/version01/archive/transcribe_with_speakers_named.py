#!/usr/bin/env python3
"""
YTAI Transcription with Speaker Naming v2
Transcription + Diarization + Automatic Speaker Naming

Features:
    - Whisper transcription (default: large-v3)
    - pyannote.audio speaker diarization (community-1)
    - Automatic speaker naming via Ollama (local LLM)
    - Manual speaker mapping via JSON config
    - Output: TXT, JSON, SRT

Requirements:
    pip install openai-whisper pyannote.audio torch torchaudio soundfile

    # For speaker naming:
    brew install ollama
    ollama serve  # run in separate terminal
    ollama pull llama3.2

Usage:
    # Basic (large-v3 by default)
    python transcribe_with_speakers_named.py audio.wav

    # With auto speaker naming
    python transcribe_with_speakers_named.py audio.wav --name-speakers

    # With known speakers count
    python transcribe_with_speakers_named.py audio.wav -n 3 --name-speakers

    # Use manual names from JSON
    python transcribe_with_speakers_named.py audio.wav --speaker-map speakers.json
"""

import argparse
import os
import sys
import json
import logging
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Set

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = Path("/Users/romansergeev/YTAI/config/HuggingFace-yt-prod.conf")
OLLAMA_MODEL = "llama3.2"  # alternatives: mistral, qwen2.5


def load_env():
    """Load HuggingFace token from config."""
    if not CONFIG_FILE.exists():
        print(f"⚠ Config not found: {CONFIG_FILE}")
        return
    
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()
    
    if os.environ.get("HF_TOKEN"):
        print("✓ HF_TOKEN loaded")

load_env()


# ============================================================================
# Project Paths
# ============================================================================

def get_project_paths(audio_path: str) -> dict:
    """Extract project structure from audio path."""
    audio_path = Path(audio_path)
    
    current = audio_path.parent
    while current.name != "01_Raw" and current != current.parent:
        current = current.parent
    
    if current.name == "01_Raw":
        project_root = current.parent
    else:
        project_root = audio_path.parent
    
    return {
        "project_root": project_root,
        "project_name": project_root.name,
        "logs_dir": project_root / "08_Logs",
        "transcripts_dir": project_root / "02_Transcripts" / "02_01_Runs",
        "speaker_map_file": project_root / "speaker_names.json"
    }


# ============================================================================
# Logging
# ============================================================================

def setup_logging(logs_dir: Path, project_name: str) -> logging.Logger:
    """Setup dual logging."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{project_name}_transcribe_{timestamp}.log"
    
    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    
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
    """HH:MM:SS.mmm"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def format_srt_timestamp(seconds: float) -> str:
    """SRT format: HH:MM:SS,mmm"""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ============================================================================
# Whisper Transcription
# ============================================================================

def transcribe_audio(audio_path: str, model_size: str, language: str, logger: logging.Logger) -> dict:
    """Transcribe with Whisper."""
    import whisper
    
    logger.info(f"Loading Whisper ({model_size})...")
    model = whisper.load_model(model_size)
    
    logger.info("Transcribing...")
    opts = {"word_timestamps": True, "verbose": False}
    if language and language.lower() != "auto":
        opts["language"] = language
    
    result = model.transcribe(audio_path, **opts)
    detected = result.get("language", "unknown")
    logger.info(f"Language: {detected}")
    
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
        logger.error("HF_TOKEN not set")
        sys.exit(1)
    
    logger.info("Loading diarization (community-1)...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=hf_token
    )
    
    # Device
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
    waveform, sample_rate = sf.read(audio_path, dtype='float32')
    waveform = torch.from_numpy(waveform)
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    else:
        waveform = waveform.T
    
    audio_input = {"waveform": waveform, "sample_rate": sample_rate}
    
    # Diarize
    logger.info("Diarizing...")
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
    
    logger.info(f"Diarization: {len(segments)} segments")
    return segments


# ============================================================================
# Assign Speakers to Transcription
# ============================================================================

def assign_speakers(transcription: dict, diarization: List[dict]) -> List[dict]:
    """Combine transcription with speaker labels."""
    result = []
    
    for seg in transcription.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_mid = (seg_start + seg_end) / 2
        
        # Find speaker by overlap
        speaker = "UNKNOWN"
        best_overlap = 0
        
        for d in diarization:
            overlap_start = max(seg_start, d["start"])
            overlap_end = min(seg_end, d["end"])
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                speaker = d["speaker"]
        
        # Fallback: midpoint
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
# Speaker Naming via Ollama
# ============================================================================

def check_ollama() -> bool:
    """Check if Ollama is available."""
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, timeout=5)
        return result.returncode == 0
    except:
        return False


def extract_speaker_names_llm(segments: List[dict], logger: logging.Logger) -> Dict[str, str]:
    """Use Ollama to identify speaker names from context."""
    if not check_ollama():
        logger.warning("Ollama not available. Install: brew install ollama")
        logger.warning("Then run: ollama serve && ollama pull llama3.2")
        return {}
    
    # Build transcript sample
    transcript_lines = []
    speakers_seen = set()
    
    for seg in segments[:60]:
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "").strip()
        if text and speaker != "UNKNOWN":
            transcript_lines.append(f"{speaker}: {text}")
            speakers_seen.add(speaker)
    
    if not speakers_seen:
        return {}
    
    transcript = "\n".join(transcript_lines)
    
    prompt = f"""Analyze this interview transcript and identify speaker names.

Look for:
- Self-introductions ("My name is...", "I am...")
- How people address each other ("Thanks Ahmed", "As Roman said")
- Context clues about roles (interviewer, guest, barista, owner)

Transcript:
{transcript}

Provide speaker mapping as JSON only. If name unknown, use role (e.g., "Interviewer", "Guest", "Barista").

Output ONLY valid JSON:
{{"SPEAKER_00": "Name", "SPEAKER_01": "Name"}}"""

    logger.info(f"Asking {OLLAMA_MODEL} to identify speakers...")
    
    try:
        result = subprocess.run(
            ["ollama", "run", OLLAMA_MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=90
        )
        
        response = result.stdout.strip()
        logger.debug(f"LLM response: {response[:500]}")
        
        # Extract JSON
        json_match = re.search(r'\{[^{}]+\}', response)
        if json_match:
            names = json.loads(json_match.group())
            logger.info(f"Speaker names: {names}")
            return names
        
        logger.warning("Could not parse LLM response")
        return {}
        
    except subprocess.TimeoutExpired:
        logger.warning("LLM timeout")
        return {}
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON: {e}")
        return {}
    except Exception as e:
        logger.warning(f"LLM error: {e}")
        return {}


def load_speaker_map(path: Path, logger: logging.Logger) -> Dict[str, str]:
    """Load manual speaker mapping from JSON."""
    if not path.exists():
        return {}
    
    try:
        with open(path) as f:
            names = json.load(f)
        logger.info(f"Loaded speaker map from {path}")
        return names
    except Exception as e:
        logger.warning(f"Could not load speaker map: {e}")
        return {}


def apply_speaker_names(segments: List[dict], names: Dict[str, str]) -> List[dict]:
    """Replace SPEAKER_XX with actual names."""
    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        if speaker in names:
            seg["speaker_id"] = speaker
            seg["speaker"] = names[speaker]
    return segments


# ============================================================================
# Output Writers
# ============================================================================

def save_txt(segments: List[dict], speakers: Set[str], audio_path: str, output_path: Path, metadata: dict):
    """Human-readable transcript."""
    lines = [
        "=" * 60,
        "TRANSCRIPTION WITH SPEAKER DIARIZATION",
        "=" * 60,
        "",
        f"Source: {audio_path}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Language: {metadata.get('language', 'unknown')}",
        f"Model: {metadata.get('model', 'unknown')}",
        f"Speakers ({len(speakers)}): {', '.join(sorted(speakers))}",
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


def save_json(segments: List[dict], speakers: Set[str], audio_path: str, output_path: Path, metadata: dict) -> Path:
    """Machine-readable JSON."""
    data = {
        "source": str(audio_path),
        "generated": datetime.now().isoformat(),
        "language": metadata.get("language"),
        "model": metadata.get("model"),
        "num_speakers": len(speakers),
        "speakers": sorted(list(speakers)),
        "speaker_map": metadata.get("speaker_map", {}),
        "total_segments": len(segments),
        "segments": segments
    }
    
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return json_path


def save_srt(segments: List[dict], output_path: Path, with_speaker: bool = True) -> Path:
    """SRT subtitle file."""
    suffix = ".srt" if with_speaker else "_clean.srt"
    srt_path = output_path.with_suffix("") 
    srt_path = Path(str(srt_path) + suffix)
    
    lines = []
    idx = 1
    
    for seg in segments:
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        start = format_srt_timestamp(seg["start"])
        end = format_srt_timestamp(seg["end"])
        
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        
        if with_speaker:
            speaker = seg.get("speaker", "UNKNOWN")
            lines.append(f"[{speaker}] {text}")
        else:
            lines.append(text)
        
        lines.append("")
        idx += 1
    
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return srt_path


def save_speaker_template(speakers: Set[str], output_dir: Path) -> Optional[Path]:
    """Create speaker_names.json template."""
    template_path = output_dir / "speaker_names.json"
    
    if template_path.exists():
        return None
    
    template = {s: s for s in sorted(speakers) if s != "UNKNOWN"}
    
    with open(template_path, "w") as f:
        json.dump(template, f, indent=2)
    
    return template_path


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Transcription with Speaker Naming",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("audio_file", help="Audio file path")
    parser.add_argument("-m", "--model", default="large-v3",
                        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                        help="Whisper model (default: large-v3)")
    parser.add_argument("-l", "--language", default="auto",
                        help="Language or 'auto' (default: auto)")
    parser.add_argument("-n", "--num-speakers", type=int,
                        help="Number of speakers (auto if not set)")
    parser.add_argument("--name-speakers", action="store_true",
                        help="Auto-identify speaker names via LLM")
    parser.add_argument("--speaker-map", type=Path,
                        help="JSON file with speaker names")
    parser.add_argument("--no-merge", action="store_true",
                        help="Don't merge consecutive segments")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.audio_file):
        print(f"Error: {args.audio_file} not found")
        sys.exit(1)
    
    # Setup
    paths = get_project_paths(args.audio_file)
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)
    paths["transcripts_dir"].mkdir(parents=True, exist_ok=True)
    
    logger = setup_logging(paths["logs_dir"], paths["project_name"])
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = Path(args.audio_file).stem
    output_path = paths["transcripts_dir"] / f"{base_name}_{timestamp}.txt"
    
    # Header
    logger.info("=" * 60)
    logger.info("TRANSCRIPTION WITH SPEAKER NAMING")
    logger.info("=" * 60)
    logger.info(f"Project: {paths['project_name']}")
    logger.info(f"Input: {args.audio_file}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Language: {args.language}")
    if args.num_speakers:
        logger.info(f"Speakers: {args.num_speakers}")
    logger.info("")
    
    # 1. Transcribe
    transcription = transcribe_audio(args.audio_file, args.model, args.language, logger)
    detected_lang = transcription.get("language", "unknown")
    logger.info(f"Transcription: {len(transcription.get('segments', []))} segments")
    logger.info("")
    
    # 2. Diarize
    diarization = perform_diarization(args.audio_file, args.num_speakers, logger)
    logger.info("")
    
    # 3. Combine
    segments = assign_speakers(transcription, diarization)
    logger.info(f"Combined: {len(segments)} segments")
    
    # 4. Merge
    if not args.no_merge:
        segments = merge_consecutive(segments)
        logger.info(f"Merged: {len(segments)} segments")
    
    # Get speakers
    speakers = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers.discard("UNKNOWN")
    logger.info(f"Speakers: {', '.join(sorted(speakers))}")
    logger.info("")
    
    # 5. Speaker naming
    speaker_map = {}
    
    # Try manual map
    if args.speaker_map:
        speaker_map = load_speaker_map(args.speaker_map, logger)
    elif paths["speaker_map_file"].exists():
        speaker_map = load_speaker_map(paths["speaker_map_file"], logger)
    
    # Try LLM
    if args.name_speakers and not speaker_map:
        speaker_map = extract_speaker_names_llm(segments, logger)
    
    # Apply names
    if speaker_map:
        segments = apply_speaker_names(segments, speaker_map)
        speakers = set(seg.get("speaker", "UNKNOWN") for seg in segments)
        speakers.discard("UNKNOWN")
        logger.info(f"Named speakers: {', '.join(sorted(speakers))}")
    
    # Metadata
    metadata = {
        "language": detected_lang,
        "model": args.model,
        "speaker_map": speaker_map
    }
    
    # 6. Save outputs
    logger.info("")
    logger.info("Saving...")
    
    save_txt(segments, speakers, args.audio_file, output_path, metadata)
    logger.info(f"  TXT:  {output_path}")
    
    json_path = save_json(segments, speakers, args.audio_file, output_path, metadata)
    logger.info(f"  JSON: {json_path}")
    
    srt_path = save_srt(segments, output_path, with_speaker=True)
    logger.info(f"  SRT:  {srt_path}")
    
    srt_clean = save_srt(segments, output_path, with_speaker=False)
    logger.info(f"  SRT (clean): {srt_clean}")
    
    # Template
    if not speaker_map:
        template = save_speaker_template(speakers, paths["project_root"])
        if template:
            logger.info(f"  Speaker template: {template}")
            logger.info("  → Edit this file to set speaker names")
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Language: {detected_lang}")
    logger.info(f"Speakers: {', '.join(sorted(speakers))}")
    logger.info(f"Segments: {len(segments)}")
    
    if segments:
        duration = segments[-1].get("end", 0)
        logger.info(f"Duration: {format_timestamp(duration)}")
    
    logger.info("")
    logger.info("Preview:")
    for seg in segments[:3]:
        ts = format_timestamp(seg["start"])
        spk = seg.get("speaker", "?")
        txt = seg.get("text", "")[:70]
        logger.info(f"  [{ts}] {spk}: {txt}...")


if __name__ == "__main__":
    main()
