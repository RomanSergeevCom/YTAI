#!/usr/bin/env python3
"""
Генерация {project}_ingest.json для UXP-плагина Premiere (020201_premiere_ingest).

Читает {project}_transcript.json и создаёт упрощённый JSON с абсолютными путями
ко всем файлам, которые нужны UXP-плагину для создания проекта Premiere.

Usage:
    from ingest_json import generate
    ingest_path = generate(Path("/path/to/Interview_transcription/Interview_transcript.json"))
"""

import json
from datetime import datetime, timezone
from pathlib import Path


VERSION = "1.0"


def generate(transcript_json_path: Path) -> Path:
    """Читает transcript.json, генерирует ingest.json рядом.

    Args:
        transcript_json_path: Абсолютный путь к {project}_transcript.json
                              (внутри {project}_transcription/)

    Returns:
        Path к созданному {project}_ingest.json
    """
    transcript_json_path = Path(transcript_json_path).resolve()
    with open(transcript_json_path) as f:
        data = json.load(f)

    project_name = data["project"]
    structure = data["structure"]
    work_dir = Path(structure["work_dir"])
    clips_data = data.get("clips", [])

    # Media metadata from first clip
    media = {}
    if clips_data:
        first_media = clips_data[0].get("media", {})
        media = {
            "width": first_media.get("width", 0),
            "height": first_media.get("height", 0),
            "fps": first_media.get("fps", 0),
            "sample_rate": first_media.get("audio_sample_rate", 0),
        }

    # Clips with absolute paths
    clips = []
    for clip in clips_data:
        clip_id = clip["clip_id"]
        filename = clip["filename"]

        # Video file path
        video_files = structure.get("video_files", [])
        video_path = None
        for vf in video_files:
            if Path(vf).stem == clip_id:
                video_path = str(Path(vf).resolve())
                break
        if not video_path:
            video_path = str(work_dir / filename)

        # Premiere transcript JSON — resolve relative path from transcript.json location
        files_block = clip.get("files", {})
        premiere_rel = files_block.get("premiere_transcript", "")
        if premiere_rel:
            premiere_abs = str((transcript_json_path.parent / premiere_rel).resolve())
        else:
            premiere_abs = ""

        clips.append({
            "clip_id": clip_id,
            "filename": filename,
            "path": video_path,
            "duration": clip.get("duration", 0),
            "offset": clip.get("offset", 0),
            "premiere_transcript": premiere_abs,
        })

    # Check for synced DJI audio files in 01_Media/Source/Audio/
    synced_dir = work_dir / "01_Media" / "Source" / "Audio"
    if synced_dir.exists():
        for clip in clips:
            dji_files = sorted(synced_dir.glob(f"{clip['clip_id']}_TX*.wav"))
            if dji_files:
                clip["dji_audio"] = [
                    {"tx": f.stem.split("_")[-1], "path": str(f.resolve())}
                    for f in dji_files
                ]

    # Files block with absolute paths
    files = {
        "transcript_json": str(transcript_json_path),
        "transcript_xlsx": str(Path(structure.get("transcript_xlsx", "")).resolve())
            if structure.get("transcript_xlsx") else "",
        "transcript_srt": str(Path(structure.get("transcript_srt", "")).resolve())
            if structure.get("transcript_srt") else "",
        "captions_srt": str(Path(structure.get("captions_srt", "")).resolve())
            if structure.get("captions_srt") else "",
    }

    ingest = {
        "version": VERSION,
        "type": "ingest",
        "project_name": project_name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "media": media,
        "clips": clips,
        "files": files,
        "source_folder": str(work_dir),
    }

    # v3.0 structure: ingest.json → Setup/; legacy: next to transcript
    if transcript_json_path.parent.name == "Transcription":
        setup_dir = transcript_json_path.parent.parent / "Setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        ingest_path = setup_dir / f"{project_name}_ingest.json"
    else:
        ingest_path = transcript_json_path.parent / f"{project_name}_ingest.json"
    with open(ingest_path, "w") as f:
        json.dump(ingest, f, indent=2, ensure_ascii=False)

    return ingest_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate ingest JSON from transcript JSON")
    parser.add_argument("transcript_json", help="Path to {project}_transcript.json")
    args = parser.parse_args()
    path = generate(Path(args.transcript_json))
    print(f"Ingest JSON written: {path}")
