"""Cross-scene transcript merger for nested multi-scene projects.

Reads per-scene transcript JSON files from 01_Media/Source/Transcription/ and
combines them into a single merged_transcript.json with scene_id and local
timecodes on every word.

Output schema (merged_transcript.json):
  {
    "version": "1.0",
    "project": "YTCR01_Arty_Dzis",
    "scenes": ["apartment", "volleyball", ...],   # sorted alphabetically
    "words": [
      { "scene_id": "volleyball", "word": "hello", "start": 1.46, "end": 1.82,
        "duration": 0.36, "confidence": 0.987, "speaker": "SPEAKER_00" }
    ]
  }

CRITICAL: start/end are LOCAL timecodes within the scene, never global.
The UXP plugin (Phase 4) routes by scene_id, then seeks within that scene's
Premiere timeline using local start/end.
"""
import json
from pathlib import Path


def read_scene_words(transcript_path: Path, scene_id: str) -> list:
    """Extract all words from a scene transcript JSON, tagging each with scene_id.

    Traverses: data["clips"] -> clip["transcript_segments"] -> segment["words_data"]
    and builds a flat list of word dicts.

    Args:
        transcript_path: Path to {scene}_transcript.json.
        scene_id: Scene name to tag each word with (e.g. "volleyball").

    Returns:
        List of word dicts, each with: scene_id, word, start, end, duration,
        confidence, speaker. start/end are LOCAL timecodes from the source.
    """
    with open(transcript_path) as f:
        data = json.load(f)

    words = []
    for clip in data.get("clips", []):
        for segment in clip.get("transcript_segments", []):
            speaker = segment.get("speaker", "UNKNOWN")
            for word in segment.get("words_data", []):
                words.append({
                    "scene_id": scene_id,
                    "word": word["word"],
                    "start": word["start"],
                    "end": word["end"],
                    "duration": word.get("duration", word["end"] - word["start"]),
                    "confidence": word.get("confidence", 0.0),
                    "speaker": speaker,
                })
    return words


def merge_transcripts(project: Path, scene_names: list) -> Path:
    """Merge per-scene transcripts into a single merged_transcript.json.

    For each scene in scene_names, checks whether {scene}_transcript.json exists
    under Transcription/. If present, reads all words via read_scene_words().
    Missing scene transcript files are silently skipped (idempotent for partial
    transcription runs).

    Output is written to:
      {project}/01_Media/Source/Transcription/merged_transcript.json

    Args:
        project: Project root path.
        scene_names: List of scene names to include in the merge.

    Returns:
        Path to the written merged_transcript.json.
    """
    tr_dir = project / "01_Media" / "Source" / "Transcription"
    all_words = []

    for scene in scene_names:
        transcript_path = tr_dir / f"{scene}_transcript.json"
        if transcript_path.exists():
            all_words.extend(read_scene_words(transcript_path, scene_id=scene))

    merged = {
        "version": "1.0",
        "project": project.name,
        "scenes": sorted(scene_names),
        "words": all_words,
    }

    out_path = tr_dir / "merged_transcript.json"
    with open(out_path, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    return out_path
