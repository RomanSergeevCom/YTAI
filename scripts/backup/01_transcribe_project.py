#!/usr/bin/env python3
"""
YTAI 02_transcribe: Project Transcription
Whisper + Pyannote Diarization → JSON с SPEAKER_XX

Обрабатывает FULL_AUDIO.wav и создаёт транскрипт с идентификаторами спикеров.
Следующий этап (03_speaker_id) определит реальные имена.

Usage:
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" -n 2
    python transcribe_project.py --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani" -m medium

Output:
    02_Transcripts/02_01_Runs/
    ├── ProjectName_transcript_YYYYMMDD_HHMMSS.json  (основной выход)
    ├── ProjectName_transcript_YYYYMMDD_HHMMSS.txt   (человекочитаемый)
    └── ProjectName_transcript_YYYYMMDD_HHMMSS.srt   (субтитры)

JSON format:
    {
        "segments": [
            {"start": 0.0, "end": 5.2, "speaker": "SPEAKER_00", "text": "..."},
            {"start": 5.5, "end": 12.1, "speaker": "SPEAKER_01", "text": "..."}
        ]
    }

Requirements:
    pip install openai-whisper pyannote.audio torch torchaudio soundfile

    # HuggingFace token для pyannote:
    export HF_TOKEN=hf_xxxxx
    # или в файле ~/YTAI/config/HuggingFace-yt-prod.conf:
    HF_TOKEN=hf_xxxxx
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set


# ============================================================================
# Configuration
# ============================================================================

# Возможные пути к конфигу с HF_TOKEN
CONFIG_PATHS = [
    Path.home() / "YTAI" / "config" / "HuggingFace-yt-prod.conf",
    Path.home() / ".config" / "ytai" / "hf_token.conf",
]

# Структура проекта
VIDEO_DIR = "01_Raw/01_01_Video"
AUDIO_DIR = "01_Raw/01_02_Audio"
TRANSCRIPTS_DIR = "02_Transcripts/02_01_Runs"
LOGS_DIR = "08_Logs"

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv",
              ".MP4", ".MOV", ".M4V", ".MTS", ".AVI", ".MKV"}

# Модели
DEFAULT_WHISPER_MODEL = "large-v3"
PYANNOTE_MODEL = "pyannote/speaker-diarization-3.1"


# ============================================================================
# Environment Setup
# ============================================================================

def load_env_config() -> bool:
    """Load HuggingFace token from config file."""
    for config_path in CONFIG_PATHS:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key and value:
                                os.environ[key] = value
                
                if os.environ.get("HF_TOKEN"):
                    return True
            except Exception:
                continue
    
    return False


def check_dependencies() -> List[str]:
    """Check if required packages are installed."""
    missing = []
    
    try:
        import whisper
    except ImportError:
        missing.append("openai-whisper")
    
    try:
        import pyannote.audio
    except ImportError:
        missing.append("pyannote.audio")
    
    try:
        import torch
    except ImportError:
        missing.append("torch")
    
    try:
        import soundfile
    except ImportError:
        missing.append("soundfile")
    
    return missing


# ============================================================================
# Project Paths
# ============================================================================

def get_project_paths(project_dir: str) -> dict:
    """Get all relevant paths for a project."""
    project_root = Path(project_dir).expanduser().resolve()
    
    if not project_root.exists():
        raise FileNotFoundError(f"Project folder not found: {project_root}")
    
    project_name = project_root.name
    audio_dir = project_root / AUDIO_DIR
    
    # Ищем FULL_AUDIO.wav
    full_audio = None
    
    # Вариант 1: ProjectName_FULL_AUDIO.wav
    candidate = audio_dir / f"{project_name}_FULL_AUDIO.wav"
    if candidate.exists():
        full_audio = candidate
    
    # Вариант 2: любой *_FULL_AUDIO.wav
    if not full_audio:
        candidates = list(audio_dir.glob("*_FULL_AUDIO.wav"))
        if candidates:
            full_audio = candidates[0]
    
    # Вариант 3: любой *.wav
    if not full_audio:
        candidates = list(audio_dir.glob("*.wav"))
        if candidates:
            # Берём самый большой файл
            candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
            full_audio = candidates[0]
    
    if not full_audio:
        raise FileNotFoundError(
            f"Audio file not found in {audio_dir}\n"
            f"Run 01_prepare/extract_audio.py first"
        )
    
    return {
        "project_root": project_root,
        "project_name": project_name,
        "video_dir": project_root / VIDEO_DIR,
        "audio_dir": audio_dir,
        "full_audio": full_audio,
        "transcripts_dir": project_root / TRANSCRIPTS_DIR,
        "logs_dir": project_root / LOGS_DIR,
    }


# ============================================================================
# Logging
# ============================================================================

def setup_logging(logs_dir: Path, project_name: str) -> logging.Logger:
    """Setup dual logging to file and console."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"{project_name}_transcribe_{timestamp}.log"
    
    logger = logging.getLogger("transcribe")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    
    # File handler - все сообщения
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    
    # Console handler - только INFO+
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(message)s"))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


# ============================================================================
# Timestamp Formatting
# ============================================================================

def format_timestamp(seconds: float) -> str:
    """Format as HH:MM:SS"""
    total_ms = int(round(seconds * 1000))
    total_secs = total_ms // 1000
    
    h = total_secs // 3600
    m = (total_secs % 3600) // 60
    s = total_secs % 60
    
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """Format for SRT: HH:MM:SS,mmm"""
    total_ms = int(round(seconds * 1000))
    
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    
    h = total_secs // 3600
    m = (total_secs % 3600) // 60
    s = total_secs % 60
    
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


# ============================================================================
# Audio Info
# ============================================================================

def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    
    return 0.0


# ============================================================================
# Whisper Transcription
# ============================================================================

def transcribe_audio(
    audio_path: Path,
    model_size: str,
    language: Optional[str],
    logger: logging.Logger
) -> dict:
    """Transcribe audio with OpenAI Whisper."""
    import whisper
    
    logger.info(f"Loading Whisper model ({model_size})...")
    model = whisper.load_model(model_size)
    
    logger.info("Starting transcription (this may take 10-20 minutes)...")
    
    opts = {
        "word_timestamps": True,
        "verbose": False,
    }
    
    if language and language.lower() not in ("auto", ""):
        opts["language"] = language
        logger.info(f"Using language: {language}")
    
    result = model.transcribe(str(audio_path), **opts)
    
    detected_lang = result.get("language", "unknown")
    num_segments = len(result.get("segments", []))
    
    logger.info(f"Transcription complete")
    logger.info(f"  Detected language: {detected_lang}")
    logger.info(f"  Raw segments: {num_segments}")
    
    return result


# ============================================================================
# Pyannote Diarization
# ============================================================================

def perform_diarization(
    audio_path: Path,
    num_speakers: Optional[int],
    logger: logging.Logger
) -> List[dict]:
    """Speaker diarization with pyannote.audio."""
    from pyannote.audio import Pipeline
    import torch
    import soundfile as sf
    
    # Проверяем HF_TOKEN
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        logger.error("HF_TOKEN not set!")
        logger.error("Set it via:")
        logger.error("  export HF_TOKEN=hf_xxxxx")
        logger.error("  or in ~/YTAI/config/HuggingFace-yt-prod.conf")
        sys.exit(1)
    
    logger.info(f"Loading diarization pipeline ({PYANNOTE_MODEL})...")
    
    try:
        pipeline = Pipeline.from_pretrained(PYANNOTE_MODEL, use_auth_token=hf_token)
    except Exception as e:
        # Fallback на старую модель
        logger.warning(f"Could not load {PYANNOTE_MODEL}: {e}")
        logger.info("Trying fallback model...")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization@2.1",
            use_auth_token=hf_token
        )
    
    # Выбираем устройство
    device = None
    if torch.backends.mps.is_available():
        device = torch.device("mps")
        logger.info("Using MPS (Apple Silicon)")
    elif torch.cuda.is_available():
        device = torch.device("cuda")
        logger.info("Using CUDA")
    else:
        device = torch.device("cpu")
        logger.info("Using CPU (this will be slow)")
    
    pipeline.to(device)
    
    # Загружаем аудио
    logger.info("Loading audio file...")
    waveform, sample_rate = sf.read(str(audio_path), dtype='float32')
    waveform = torch.from_numpy(waveform)
    
    if waveform.ndim == 1:
        waveform = waveform.unsqueeze(0)
    else:
        waveform = waveform.T
    
    audio_input = {"waveform": waveform, "sample_rate": sample_rate}
    
    # Запускаем diarization
    logger.info("Running speaker diarization (this may take 5-15 minutes)...")
    
    diarization_opts = {}
    if num_speakers:
        diarization_opts["num_speakers"] = num_speakers
        logger.info(f"  Expected speakers: {num_speakers}")
    
    output = pipeline(audio_input, **diarization_opts)
    
    # Извлекаем сегменты
    segments = []
    
    # Pyannote 3.x API
    if hasattr(output, 'itertracks'):
        for turn, _, speaker in output.itertracks(yield_label=True):
            segments.append({
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker
            })
    
    # Нормализуем имена спикеров
    speaker_mapping = {}
    speaker_counter = 0
    
    for seg in segments:
        old_speaker = seg["speaker"]
        if old_speaker not in speaker_mapping:
            speaker_mapping[old_speaker] = f"SPEAKER_{speaker_counter:02d}"
            speaker_counter += 1
        seg["speaker"] = speaker_mapping[old_speaker]
    
    unique_speakers = set(seg["speaker"] for seg in segments)
    logger.info(f"Diarization complete")
    logger.info(f"  Segments: {len(segments)}")
    logger.info(f"  Speakers: {len(unique_speakers)} ({', '.join(sorted(unique_speakers))})")
    
    return segments


# ============================================================================
# Combine Transcription with Diarization
# ============================================================================

def assign_speakers(
    transcription: dict,
    diarization: List[dict],
    logger: logging.Logger
) -> List[dict]:
    """Assign speaker labels to transcription segments."""
    result = []
    unknown_count = 0
    
    for seg in transcription.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_mid = (seg_start + seg_end) / 2
        
        # Находим спикера по максимальному пересечению
        speaker = "UNKNOWN"
        best_overlap = 0
        
        for d in diarization:
            overlap_start = max(seg_start, d["start"])
            overlap_end = min(seg_end, d["end"])
            overlap = max(0, overlap_end - overlap_start)
            
            if overlap > best_overlap:
                best_overlap = overlap
                speaker = d["speaker"]
        
        # Fallback: проверяем середину сегмента
        if speaker == "UNKNOWN":
            for d in diarization:
                if d["start"] <= seg_mid <= d["end"]:
                    speaker = d["speaker"]
                    break
        
        if speaker == "UNKNOWN":
            unknown_count += 1
        
        result.append({
            "start": seg_start,
            "end": seg_end,
            "speaker": speaker,
            "text": text
        })
    
    if unknown_count > 0:
        logger.warning(f"  {unknown_count} segments could not be assigned to a speaker")
    
    return result


def merge_consecutive(
    segments: List[dict],
    max_gap: float = 1.0,
    logger: logging.Logger = None
) -> List[dict]:
    """Merge consecutive segments from the same speaker."""
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
    
    if logger:
        logger.info(f"  Merged: {len(segments)} → {len(merged)} segments")
    
    return merged


# ============================================================================
# Output Writers
# ============================================================================

def save_json(
    segments: List[dict],
    speakers: Set[str],
    paths: dict,
    output_path: Path,
    metadata: dict
) -> Path:
    """Save machine-readable JSON."""
    # Вычисляем общую длительность
    total_duration = 0
    if segments:
        total_duration = max(seg["end"] for seg in segments)
    
    data = {
        "project_name": paths["project_name"],
        "source": str(paths["full_audio"]),
        "generated": datetime.now().isoformat(),
        "language": metadata.get("language"),
        "model": metadata.get("model"),
        "total_duration": total_duration,
        "num_speakers": len(speakers),
        "speakers": sorted(list(speakers)),
        "total_segments": len(segments),
        "segments": segments
    }
    
    json_path = output_path.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return json_path


def save_txt(
    segments: List[dict],
    speakers: Set[str],
    paths: dict,
    output_path: Path,
    metadata: dict
) -> Path:
    """Save human-readable transcript."""
    total_duration = 0
    if segments:
        total_duration = max(seg["end"] for seg in segments)
    
    lines = [
        "=" * 70,
        "PROJECT TRANSCRIPTION",
        "=" * 70,
        "",
        f"Project:   {paths['project_name']}",
        f"Source:    {paths['full_audio'].name}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Duration:  {format_duration(total_duration)}",
        f"Language:  {metadata.get('language', 'unknown')}",
        f"Model:     {metadata.get('model', 'unknown')}",
        f"Speakers:  {len(speakers)} ({', '.join(sorted(speakers))})",
        f"Segments:  {len(segments)}",
        "",
        "NOTE: Speakers are labeled as SPEAKER_00, SPEAKER_01, etc.",
        "      Run 03_speaker_id/process_all.py to identify real names.",
        "",
        "-" * 70,
        "TRANSCRIPT",
        "-" * 70,
        ""
    ]
    
    for seg in segments:
        ts = format_timestamp(seg["start"])
        speaker = seg.get("speaker", "UNKNOWN")
        text = seg.get("text", "")
        lines.append(f"[{ts}] {speaker}:")
        lines.append(f"    {text}")
        lines.append("")
    
    txt_path = output_path.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return txt_path


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
        
        lines.append(str(idx))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(f"[{speaker}] {text}")
        lines.append("")
        idx += 1
    
    srt_path = output_path.with_suffix(".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    return srt_path


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="YTAI: Transcribe project audio with speaker diarization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s --project "/Volumes/RYA Blue/YTCG37_Hadi_Dawani"
    %(prog)s --project "/path/to/project" -n 2
    %(prog)s --project "/path/to/project" -m medium -l en

Output:
    02_Transcripts/02_01_Runs/
    ├── ProjectName_transcript_YYYYMMDD_HHMMSS.json
    ├── ProjectName_transcript_YYYYMMDD_HHMMSS.txt
    └── ProjectName_transcript_YYYYMMDD_HHMMSS.srt
        """
    )
    
    parser.add_argument(
        "--project", required=True,
        help="Project folder path"
    )
    parser.add_argument(
        "-m", "--model",
        default=DEFAULT_WHISPER_MODEL,
        choices=["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"],
        help=f"Whisper model (default: {DEFAULT_WHISPER_MODEL})"
    )
    parser.add_argument(
        "-l", "--language",
        default="auto",
        help="Language code (en, ru, ar, etc.) or 'auto' (default: auto)"
    )
    parser.add_argument(
        "-n", "--num-speakers",
        type=int,
        help="Number of speakers (improves diarization accuracy)"
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Don't merge consecutive segments from same speaker"
    )
    parser.add_argument(
        "--skip-diarization",
        action="store_true",
        help="Skip speaker diarization (all segments labeled SPEAKER_00)"
    )
    
    args = parser.parse_args()
    
    # Проверяем зависимости
    missing = check_dependencies()
    if missing:
        print(f"ERROR: Missing packages: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        sys.exit(1)
    
    # Загружаем конфиг
    if not args.skip_diarization:
        load_env_config()
    
    # Получаем пути проекта
    try:
        paths = get_project_paths(args.project)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Создаём директории
    paths["transcripts_dir"].mkdir(parents=True, exist_ok=True)
    paths["logs_dir"].mkdir(parents=True, exist_ok=True)
    
    # Настраиваем логирование
    logger = setup_logging(paths["logs_dir"], paths["project_name"])
    
    # Генерируем имя выходного файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = paths["transcripts_dir"] / f"{paths['project_name']}_transcript_{timestamp}"
    
    # Заголовок
    logger.info("=" * 70)
    logger.info("YTAI 02_TRANSCRIBE: PROJECT TRANSCRIPTION")
    logger.info("=" * 70)
    logger.info("")
    logger.info(f"Project:  {paths['project_name']}")
    logger.info(f"Audio:    {paths['full_audio']}")
    logger.info(f"Model:    {args.model}")
    logger.info(f"Language: {args.language}")
    if args.num_speakers:
        logger.info(f"Speakers: {args.num_speakers} (expected)")
    logger.info("")
    
    # Информация об аудио
    audio_duration = get_audio_duration(paths["full_audio"])
    if audio_duration > 0:
        logger.info(f"Audio duration: {format_duration(audio_duration)}")
        logger.info("")
    
    # Фаза 1: Транскрипция
    logger.info("PHASE 1: Transcription (Whisper)")
    logger.info("-" * 40)
    
    transcription = transcribe_audio(
        paths["full_audio"],
        args.model,
        args.language if args.language != "auto" else None,
        logger
    )
    
    detected_lang = transcription.get("language", "unknown")
    logger.info("")
    
    # Фаза 2: Diarization
    if args.skip_diarization:
        logger.info("PHASE 2: Diarization (SKIPPED)")
        logger.info("-" * 40)
        logger.info("  All segments labeled as SPEAKER_00")
        diarization = []
    else:
        logger.info("PHASE 2: Speaker Diarization (Pyannote)")
        logger.info("-" * 40)
        
        diarization = perform_diarization(
            paths["full_audio"],
            args.num_speakers,
            logger
        )
    
    logger.info("")
    
    # Фаза 3: Объединение
    logger.info("PHASE 3: Combining Results")
    logger.info("-" * 40)
    
    if diarization:
        segments = assign_speakers(transcription, diarization, logger)
    else:
        # Без diarization - все сегменты от SPEAKER_00
        segments = []
        for seg in transcription.get("segments", []):
            text = seg.get("text", "").strip()
            if text:
                segments.append({
                    "start": seg["start"],
                    "end": seg["end"],
                    "speaker": "SPEAKER_00",
                    "text": text
                })
    
    logger.info(f"  Combined segments: {len(segments)}")
    
    # Merge consecutive
    if not args.no_merge:
        segments = merge_consecutive(segments, max_gap=1.0, logger=logger)
    
    # Уникальные спикеры
    speakers = set(seg.get("speaker", "UNKNOWN") for seg in segments)
    speakers.discard("UNKNOWN")
    
    logger.info(f"  Final speakers: {', '.join(sorted(speakers))}")
    logger.info("")
    
    # Метаданные
    metadata = {
        "language": detected_lang,
        "model": args.model
    }
    
    # Фаза 4: Сохранение
    logger.info("PHASE 4: Saving Results")
    logger.info("-" * 40)
    
    json_path = save_json(segments, speakers, paths, output_base, metadata)
    logger.info(f"  JSON: {json_path}")
    
    txt_path = save_txt(segments, speakers, paths, output_base, metadata)
    logger.info(f"  TXT:  {txt_path}")
    
    srt_path = save_srt(segments, output_base)
    logger.info(f"  SRT:  {srt_path}")
    
    logger.info("")
    
    # Итог
    logger.info("=" * 70)
    logger.info("TRANSCRIPTION COMPLETE")
    logger.info("=" * 70)
    logger.info("")
    logger.info(f"Language:  {detected_lang}")
    logger.info(f"Speakers:  {len(speakers)}")
    logger.info(f"Segments:  {len(segments)}")
    
    if segments:
        duration = max(seg["end"] for seg in segments)
        logger.info(f"Duration:  {format_duration(duration)}")
    
    logger.info("")
    logger.info("Output files:")
    logger.info(f"  {json_path}")
    logger.info(f"  {txt_path}")
    logger.info(f"  {srt_path}")
    logger.info("")
    logger.info("Next step:")
    logger.info(f"  python 03_speaker_id/process_all.py --project \"{paths['project_root']}\"")
    logger.info("")
    
    # Превью
    logger.info("Preview (first 5 segments):")
    for seg in segments[:5]:
        ts = format_timestamp(seg["start"])
        spk = seg.get("speaker", "?")
        txt = seg.get("text", "")[:60]
        if len(seg.get("text", "")) > 60:
            txt += "..."
        logger.info(f"  [{ts}] {spk}: {txt}")


if __name__ == "__main__":
    main()
