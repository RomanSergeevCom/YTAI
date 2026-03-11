#!/usr/bin/env python3
"""
YTAI Transcription with Speaker Naming v2.2
Transcription + Diarization + Smart Speaker Naming

Features:
    - Whisper transcription (default: large-v3)
    - pyannote.audio speaker diarization (community-1)
    - Smart speaker naming via Ollama (llama3.3:70b)
    - Role-based naming when name unknown
    - Name validation (filters hallucinations)
    - Manual speaker mapping via JSON config
    - Output: TXT, JSON, SRT

Requirements:
    pip install openai-whisper pyannote.audio torch torchaudio soundfile requests

    # For speaker naming (70B model):
    export OLLAMA_MODELS=~/YTAI/models/ollama
    OLLAMA_MAX_VRAM=20g ollama serve  # IMPORTANT: prevents Mac freeze!
    
    # Model should already be downloaded to ~/YTAI/models/ollama

Usage:
    python transcribe_with_speakers_named.py audio.wav --name-speakers
    python transcribe_with_speakers_named.py audio.wav -n 3 --name-speakers
"""

import argparse
import os
import sys
import json
import logging
import requests
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Set

# ============================================================================
# Configuration
# ============================================================================

CONFIG_FILE = Path("/Users/romansergeev/YTAI/config/HuggingFace-yt-prod.conf")

# Ollama settings
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.3:70b-instruct-q4_K_M"
OLLAMA_TIMEOUT = 600  # seconds - 10 min for 70B model


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
# Ollama API (for 70B model)
# ============================================================================

def check_ollama_server(logger: logging.Logger) -> bool:
    """Check if Ollama server is running."""
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code == 200:
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            logger.debug(f"Available models: {model_names}")
            return True
        return False
    except requests.exceptions.ConnectionError:
        return False
    except Exception as e:
        logger.debug(f"Ollama check error: {e}")
        return False


def call_ollama_api(prompt: str, logger: logging.Logger) -> Optional[str]:
    """
    Call Ollama API with the 70B model.
    
    Uses API instead of CLI for better control and error handling.
    """
    try:
        logger.debug(f"Calling Ollama API with {OLLAMA_MODEL}...")
        
        response = requests.post(
            OLLAMA_API_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,  # Lower for more consistent output
                    "num_predict": 500,  # Limit output length
                }
            },
            timeout=OLLAMA_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            return result.get("response", "")
        else:
            logger.warning(f"Ollama API error: {response.status_code}")
            logger.debug(f"Response: {response.text[:500]}")
            return None
            
    except requests.exceptions.Timeout:
        logger.warning(f"Ollama timeout ({OLLAMA_TIMEOUT}s)")
        return None
    except requests.exceptions.ConnectionError:
        logger.warning("Ollama server not running")
        return None
    except Exception as e:
        logger.warning(f"Ollama API error: {e}")
        return None


# ============================================================================
# Speaker Naming via LLM
# ============================================================================

def extract_speaker_names_llm(segments: List[dict], speakers: Set[str], logger: logging.Logger) -> Dict[str, str]:
    """
    Use Ollama 70B model to identify speaker names/roles from context.
    """
    if not check_ollama_server(logger):
        logger.warning("Ollama server not running!")
        logger.warning("Start with: OLLAMA_MAX_VRAM=20g ollama serve")
        logger.warning("(OLLAMA_MAX_VRAM=20g prevents Mac freeze with 70B model)")
        return {}
    
    # Build transcript with speaker samples
    speaker_lines = {s: [] for s in speakers}
    
    for seg in segments:
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "").strip()
        if text and speaker in speakers:
            speaker_lines[speaker].append(text)
    
    # Build sample for each speaker (first 5 lines, max 100 chars each)
    transcript_parts = []
    for speaker in sorted(speakers):
        lines = speaker_lines.get(speaker, [])[:5]
        if lines:
            transcript_parts.append(f"\n{speaker} says:")
            for line in lines:
                transcript_parts.append(f'  "{line[:100]}"')
    
    transcript = "\n".join(transcript_parts)
    speakers_list = ", ".join(sorted(speakers))
    
    prompt = f"""Analyze this interview transcript and identify WHO each speaker is.

SPEAKERS TO IDENTIFY: {speakers_list}

TRANSCRIPT SAMPLES:
{transcript}

RULES:
1. Look for self-introductions: "My name is...", "I am...", "I'm..."
2. Look for how others address them: "Thank you Ahmed", "As Roman mentioned"
3. If a name is found, verify it sounds like a real name (not a transcription error)
4. If NO name is found, assign a DESCRIPTIVE ROLE based on context:
   - "Interviewer" - person asking questions
   - "Host" - person guiding conversation  
   - "Guest" - person being interviewed
   - "Barista" - coffee shop worker
   - "Shop Owner" - business owner
   - "Expert" - subject matter expert

IMPORTANT: 
- Provide a mapping for EVERY speaker: {speakers_list}
- Use short labels (1-2 words max)
- If truly unknown, use "Speaker 1", "Speaker 2" etc.

OUTPUT FORMAT - JSON only, no explanation:
{{"SPEAKER_00": "Name or Role", "SPEAKER_01": "Name or Role"}}

Provide mapping for ALL {len(speakers)} speakers."""

    logger.info(f"Asking {OLLAMA_MODEL} to identify {len(speakers)} speakers...")
    
    response = call_ollama_api(prompt, logger)
    
    if not response:
        return {}
    
    logger.debug(f"LLM response: {response[:500]}")
    
    # Extract JSON from response
    try:
        json_match = re.search(r'\{[^{}]+\}', response, re.DOTALL)
        if json_match:
            raw_names = json.loads(json_match.group())
            
            # Validate and clean names
            names = validate_speaker_names(raw_names, speakers, logger)
            
            logger.info(f"Speaker names: {names}")
            return names
        
        logger.warning("Could not parse LLM response as JSON")
        logger.debug(f"Full response: {response}")
        return {}
        
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON: {e}")
        return {}


def validate_speaker_names(raw_names: Dict[str, str], speakers: Set[str], logger: logging.Logger) -> Dict[str, str]:
    """
    Validate and clean speaker names from LLM.
    
    Filters:
    - Too long names (hallucinations)
    - "Unknown", "N/A" etc.
    - Strange characters
    """
    validated = {}
    
    # Patterns that indicate no real name found
    invalid_patterns = [
        r'^unknown$',
        r'^speaker\s*\d*$',
        r'^person\s*\d*$',
        r'^\?+$',
        r'^n/?a$',
        r'^not\s+(specified|identified|known)$',
        r'^unidentified$',
    ]
    
    for speaker in speakers:
        name = raw_names.get(speaker, "").strip()
        
        is_valid = True
        
        # Empty or too short
        if len(name) < 2:
            is_valid = False
        
        # Too long (probably hallucination)
        if len(name) > 25:
            is_valid = False
            logger.debug(f"Name too long for {speaker}: '{name}'")
        
        # Matches invalid pattern
        for pattern in invalid_patterns:
            if re.match(pattern, name.lower()):
                is_valid = False
                break
        
        # Contains weird characters (allow unicode letters, spaces, hyphens, apostrophes)
        if is_valid and not re.match(r'^[\w\s\-\'\.]+$', name, re.UNICODE):
            is_valid = False
            logger.debug(f"Invalid chars in name for {speaker}: '{name}'")
        
        if is_valid:
            # Normalize: Title Case
            validated[speaker] = name.title().strip()
        else:
            # Keep original speaker ID
            validated[speaker] = speaker
    
    return validated


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
        if speaker in names and names[speaker] != speaker:
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
    if with_speaker:
        srt_path = output_path.with_suffix(".srt")
    else:
        srt_path = Path(str(output_path.with_suffix("")) + "_clean.srt")
    
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


def save_speaker_template(speakers: Set[str], output_dir: Path, existing_map: Dict[str, str]) -> Path:
    """Create/update speaker_names.json with LLM results."""
    template_path = output_dir / "speaker_names.json"
    
    # Build template with existing names or speaker IDs
    template = {}
    for s in sorted(speakers):
        if s != "UNKNOWN":
            template[s] = existing_map.get(s, s)
    
    with open(template_path, "w") as f:
        json.dump(template, f, indent=2)
    
    return template_path


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Transcription with Speaker Naming v2.2",
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
    logger.info("TRANSCRIPTION WITH SPEAKER NAMING v2.2")
    logger.info("=" * 60)
    logger.info(f"Project: {paths['project_name']}")
    logger.info(f"Input: {args.audio_file}")
    logger.info(f"Model: {args.model}")
    logger.info(f"Language: {args.language}")
    if args.num_speakers:
        logger.info(f"Speakers: {args.num_speakers}")
    if args.name_speakers:
        logger.info(f"LLM: {OLLAMA_MODEL}")
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
    
    # Get speakers (before naming)
    speakers_original = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers_original.discard("UNKNOWN")
    logger.info(f"Speakers: {', '.join(sorted(speakers_original))}")
    logger.info("")
    
    # 5. Speaker naming
    speaker_map = {}
    
    # Try manual map first
    if args.speaker_map:
        speaker_map = load_speaker_map(args.speaker_map, logger)
    elif paths["speaker_map_file"].exists():
        speaker_map = load_speaker_map(paths["speaker_map_file"], logger)
    
    # Try LLM if requested
    if args.name_speakers:
        # Check which speakers need naming
        unmapped = speakers_original - set(speaker_map.keys())
        if unmapped or not speaker_map:
            llm_names = extract_speaker_names_llm(segments, speakers_original, logger)
            # Merge: manual map takes precedence
            for k, v in llm_names.items():
                if k not in speaker_map:
                    speaker_map[k] = v
    
    # Apply names
    if speaker_map:
        segments = apply_speaker_names(segments, speaker_map)
    
    # Get final speakers (after naming)
    speakers_final = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers_final.discard("UNKNOWN")
    
    if speaker_map:
        logger.info(f"Named speakers: {', '.join(sorted(speakers_final))}")
    
    # Metadata
    metadata = {
        "language": detected_lang,
        "model": args.model,
        "speaker_map": speaker_map
    }
    
    # 6. Save outputs
    logger.info("")
    logger.info("Saving...")
    
    save_txt(segments, speakers_final, args.audio_file, output_path, metadata)
    logger.info(f"  TXT:  {output_path}")
    
    json_path = save_json(segments, speakers_final, args.audio_file, output_path, metadata)
    logger.info(f"  JSON: {json_path}")
    
    srt_path = save_srt(segments, output_path, with_speaker=True)
    logger.info(f"  SRT:  {srt_path}")
    
    srt_clean = save_srt(segments, output_path, with_speaker=False)
    logger.info(f"  SRT (clean): {srt_clean}")
    
    # Save/update speaker template
    template = save_speaker_template(speakers_original, paths["project_root"], speaker_map)
    logger.info(f"  Speaker map: {template}")
    
    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Language: {detected_lang}")
    logger.info(f"Speakers: {', '.join(sorted(speakers_final))}")
    logger.info(f"Segments: {len(segments)}")
    
    if segments:
        duration = segments[-1].get("end", 0)
        logger.info(f"Duration: {format_timestamp(duration)}")
    
    logger.info("")
    logger.info("Preview:")
    for seg in segments[:5]:
        ts = format_timestamp(seg["start"])
        spk = seg.get("speaker", "?")
        txt = seg.get("text", "")[:60]
        logger.info(f"  [{ts}] {spk}: {txt}...")


if __name__ == "__main__":
    main()
