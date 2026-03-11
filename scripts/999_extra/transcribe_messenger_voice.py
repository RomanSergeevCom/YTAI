#!/usr/bin/env python3
"""
transcribe_messenger_voice.py — Транскрибация голосовых WhatsApp/Telegram

Простой скрипт для транскрибации голосовых сообщений из мессенджеров.
Поддерживает OGG (Telegram), OPUS (WhatsApp), MP3, M4A, WAV и другие форматы.
Без диаризации спикеров — только чистый текст.

Usage:
    python transcribe_messenger_voice.py message.ogg
    python transcribe_messenger_voice.py message.ogg -m medium -l ru
    python transcribe_messenger_voice.py *.ogg -o ./transcripts/

Requirements:
    pip install openai-whisper
    brew install ffmpeg
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List

VERSION = "1.0.0"

# Форматы голосовых сообщений
AUDIO_EXTS = {
    ".ogg",   # Telegram voice
    ".oga",   # Telegram voice (alt)
    ".opus",  # WhatsApp voice
    ".mp3",   # Common audio
    ".m4a",   # iPhone voice memo
    ".wav",   # Standard audio
    ".flac",  # Lossless
    ".aac",   # Common audio
    ".wma",   # Windows audio
}

DEFAULT_MODEL = "large-v3"

# Кэш модели Whisper
_whisper_model = None
_whisper_model_name = None


def get_whisper_model(model_size: str):
    """Load Whisper model with caching."""
    global _whisper_model, _whisper_model_name
    
    if _whisper_model is not None and _whisper_model_name == model_size:
        return _whisper_model
    
    import whisper
    
    print(f"  Loading Whisper model ({model_size})...")
    _whisper_model = whisper.load_model(model_size)
    _whisper_model_name = model_size
    
    return _whisper_model


def format_duration(seconds: float) -> str:
    """Human-readable duration."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def get_media_duration(path: Path) -> float:
    """Get audio duration in seconds."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def convert_to_wav(input_path: Path, output_path: Path) -> bool:
    """Convert audio to WAV format for Whisper."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(input_path),
        "-vn", "-sn", "-dn",
        "-ar", "16000",  # Whisper optimal sample rate
        "-ac", "1",      # Mono
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def transcribe_audio(
    audio_path: Path,
    model_size: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    initial_prompt: Optional[str] = None,
) -> dict:
    """Transcribe audio using Whisper."""
    model = get_whisper_model(model_size)
    
    opts = {
        "word_timestamps": False,
        "verbose": False,
        "fp16": False,  # Better compatibility on CPU/MPS
    }
    
    if language and language.lower() not in ("auto", ""):
        opts["language"] = language
    
    if initial_prompt:
        opts["initial_prompt"] = initial_prompt
    
    print(f"  Transcribing...")
    result = model.transcribe(str(audio_path), **opts)
    
    return result


def save_transcript(text: str, output_path: Path) -> None:
    """Save transcript to text file."""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)


def process_file(
    audio_path: Path,
    model_size: str,
    language: Optional[str],
    output_dir: Optional[Path] = None,
    initial_prompt: Optional[str] = None,
) -> Optional[str]:
    """Process a single audio file."""
    if not audio_path.exists():
        print(f"ERROR: File not found: {audio_path}")
        return None
    
    duration = get_media_duration(audio_path)
    print(f"\n{'='*60}")
    print(f"File: {audio_path.name}")
    print(f"Duration: {format_duration(duration)}")
    print(f"{'='*60}")
    
    start_time = datetime.now()
    
    # Convert to WAV if needed (OGG/OPUS require conversion)
    needs_conversion = audio_path.suffix.lower() in {".ogg", ".oga", ".opus"}
    
    if needs_conversion:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = Path(tmp.name)
        
        print(f"  Converting to WAV...")
        if not convert_to_wav(audio_path, wav_path):
            print(f"ERROR: Failed to convert audio")
            return None
        
        transcribe_path = wav_path
    else:
        transcribe_path = audio_path
        wav_path = None
    
    try:
        # Transcribe
        result = transcribe_audio(transcribe_path, model_size, language, initial_prompt)
        
        # Extract text
        text = result.get("text", "").strip()
        detected_lang = result.get("language", "unknown")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        speed = duration / elapsed if elapsed > 0 else 0
        
        print(f"  Language: {detected_lang}")
        print(f"  Time: {elapsed:.1f}s ({speed:.1f}x realtime)")
        print(f"\n{'-'*60}")
        print(f"TRANSCRIPT:")
        print(f"{'-'*60}")
        print(text)
        print(f"{'-'*60}\n")
        
        # Save to file
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            txt_path = output_dir / f"{audio_path.stem}.txt"
        else:
            txt_path = audio_path.with_suffix(".txt")
        
        save_transcript(text, txt_path)
        print(f"Saved: {txt_path}")
        
        return text
        
    finally:
        # Cleanup temp file
        if wav_path and wav_path.exists():
            wav_path.unlink()


def check_dependencies() -> bool:
    """Check if required dependencies are installed."""
    errors = []
    
    # Check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=10)
    except Exception:
        errors.append("ffmpeg not found. Install: brew install ffmpeg")
    
    # Check whisper
    try:
        import whisper
    except ImportError:
        errors.append("openai-whisper not found. Install: pip install openai-whisper")
    
    if errors:
        print("ERROR: Missing dependencies:")
        for e in errors:
            print(f"  - {e}")
        return False
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Транскрибация голосовых сообщений WhatsApp/Telegram",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s message.ogg                    # Telegram voice
    %(prog)s voice.opus                     # WhatsApp voice  
    %(prog)s message.ogg -m medium -l ru    # Быстрее, русский язык
    %(prog)s *.ogg -o ./transcripts/        # Все файлы в папку
    %(prog)s voice.ogg --prompt "Бизнес"    # С контекстной подсказкой

Supported formats:
    Telegram: .ogg, .oga
    WhatsApp: .opus
    Other: .mp3, .m4a, .wav, .flac, .aac
        """
    )
    
    parser.add_argument("input", nargs="+", help="Audio file(s) to transcribe")
    
    parser.add_argument("-m", "--model", default=DEFAULT_MODEL,
                        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
                        help=f"Whisper model (default: {DEFAULT_MODEL})")
    
    parser.add_argument("-l", "--language", default=None,
                        help="Language code (ru, en, ar) — speeds up processing")
    
    parser.add_argument("-o", "--output", type=Path, default=None,
                        help="Output directory for transcripts")
    
    parser.add_argument("--prompt", type=str, default=None,
                        help="Initial prompt to guide Whisper (context hint)")
    
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    
    args = parser.parse_args()
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Collect files
    files: List[Path] = []
    for p in args.input:
        path = Path(p).resolve()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
            files.append(path)
        elif path.is_file():
            print(f"WARNING: Skipping unsupported format: {path.name}")
        else:
            print(f"WARNING: File not found: {p}")
    
    if not files:
        print("ERROR: No audio files to process")
        print(f"Supported formats: {', '.join(sorted(AUDIO_EXTS))}")
        sys.exit(1)
    
    # Header
    print("")
    print("╔" + "═" * 58 + "╗")
    print("║" + f"  TRANSCRIBE VOICE v{VERSION}".center(58) + "║")
    print("║" + "  WhatsApp / Telegram Voice Messages".center(58) + "║")
    print("╚" + "═" * 58 + "╝")
    print("")
    print(f"Files: {len(files)}")
    print(f"Model: {args.model}")
    print(f"Language: {args.language or 'auto-detect'}")
    
    # Calculate total duration
    total_duration = sum(get_media_duration(f) for f in files)
    if total_duration > 0:
        print(f"Total duration: {format_duration(total_duration)}")
    
    # Process each file
    start_time = datetime.now()
    success = 0
    
    for i, audio_file in enumerate(files, 1):
        if len(files) > 1:
            print(f"\n[{i}/{len(files)}]", end="")
        
        text = process_file(
            audio_file,
            args.model,
            args.language,
            args.output,
            args.prompt,
        )
        if text:
            success += 1
    
    # Summary
    total_time = (datetime.now() - start_time).total_seconds()
    
    print("")
    print("=" * 60)
    print(f"Done: {success}/{len(files)} files transcribed")
    print(f"Total time: {format_duration(total_time)}")
    print("=" * 60)
    
    sys.exit(0 if success == len(files) else 1)


if __name__ == "__main__":
    main()
