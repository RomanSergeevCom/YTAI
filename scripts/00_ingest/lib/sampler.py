"""
Whisper sampling: extract audio from a few clips and transcribe.
"""

import subprocess
from pathlib import Path

WHISPER_MODEL = "base"

# Cached model instance (loaded once per run)
_whisper_model = None
_whisper_version = None


def _select_sample_clips(clips: list, max_samples: int = 5) -> list:
    """
    Select clips to sample: first, longest, last, and middle.
    Returns list of clip dicts from the clips list.
    """
    if not clips:
        return []
    if len(clips) <= max_samples:
        return list(clips)

    selected = {}

    # First clip
    selected[0] = clips[0]
    # Last clip
    selected[len(clips) - 1] = clips[-1]
    # Longest clip
    longest_idx = max(range(len(clips)), key=lambda i: clips[i]["duration_sec"])
    selected[longest_idx] = clips[longest_idx]
    # Middle clip
    mid = len(clips) // 2
    selected[mid] = clips[mid]

    # Fill remaining slots if needed
    if len(selected) < max_samples:
        quarter = len(clips) // 4
        if quarter not in selected:
            selected[quarter] = clips[quarter]

    # Return sorted by index
    return [selected[k] for k in sorted(selected)]


def _extract_audio_sample(video_path: Path, output_path: Path,
                          duration_sec: int = 60) -> bool:
    """Extract first N seconds of audio as mono 16kHz WAV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-ss', '0', '-i', str(video_path),
             '-t', str(duration_sec), '-vn',
             '-ac', '1', '-ar', '16000', '-acodec', 'pcm_s16le',
             str(output_path)],
            capture_output=True, timeout=60,
        )
        return output_path.exists() and output_path.stat().st_size > 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _load_whisper():
    """Load whisper model once and cache it."""
    global _whisper_model, _whisper_version
    if _whisper_model is not None:
        return _whisper_model

    try:
        import whisper
        _whisper_version = getattr(whisper, '__version__', 'unknown')
        _whisper_model = whisper.load_model(WHISPER_MODEL)
        return _whisper_model
    except ImportError:
        return None


def _transcribe_whisper(audio_path: Path) -> dict | None:
    """
    Transcribe audio file using cached whisper model.
    Returns dict with language and text, or None if whisper unavailable.
    """
    model = _load_whisper()
    if model is None:
        return None

    try:
        result = model.transcribe(
            str(audio_path),
            language=None,  # auto-detect
            fp16=False,
        )
        return {
            "language": result.get("language", "unknown"),
            "text": result.get("text", "").strip(),
        }
    except Exception:
        return None


def sample_clips(clips: list, discovery_dir: Path, *,
                 max_samples: int = 5, progress_cb=None) -> dict:
    """
    Sample a few clips: extract audio and transcribe with whisper.

    Returns dict with:
        - clips_sampled: list of filenames sampled
        - language: detected language
        - transcripts: list of {clip, language, text}
        - whisper_available: bool
        - whisper_model: model name used
        - whisper_version: whisper package version
    """
    selected = _select_sample_clips(clips, max_samples)
    audio_dir = discovery_dir / "audio_samples"

    transcripts = []
    languages = []
    whisper_available = True

    for clip in selected:
        fname = clip["filename"]
        stem = Path(fname).stem

        if progress_cb:
            progress_cb(fname)

        # Extract audio sample
        audio_path = audio_dir / f"{stem}_sample.wav"
        video_path = Path(clip["path"])

        if not _extract_audio_sample(video_path, audio_path):
            continue

        # Transcribe
        result = _transcribe_whisper(audio_path)
        if result is None:
            whisper_available = False
            break

        languages.append(result["language"])
        transcripts.append({
            "clip": fname,
            "language": result["language"],
            "text": result["text"][:500],
        })

    # Most common language
    language = "unknown"
    if languages:
        from collections import Counter
        language = Counter(languages).most_common(1)[0][0]

    return {
        "clips_sampled": [c["filename"] for c in selected],
        "language": language,
        "transcripts": transcripts,
        "whisper_available": whisper_available,
        "whisper_model": WHISPER_MODEL,
        "whisper_version": _whisper_version or "N/A",
    }
