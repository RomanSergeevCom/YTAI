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
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCENE_DIR_RE = re.compile(r'^\d{2}_')
CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')


def _project_code(project_name: str) -> str:
    """Extract short code (e.g. 'YTCG37') from project name."""
    m = CODE_RE.match(project_name)
    return m.group(1) if m else project_name


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

    # Detect scene from video path (e.g. Video/03_Coffee/clip.MP4 → "03_Coffee")
    for clip in clips:
        vp = Path(clip["path"])
        parent_name = vp.parent.name
        if SCENE_DIR_RE.match(parent_name):
            clip["scene"] = parent_name

    # Check for synced DJI audio files in 01_Media/Source/Audio/ (incl. scene subdirs)
    synced_dir = work_dir / "01_Media" / "Source" / "Audio"
    if synced_dir.exists():
        for clip in clips:
            dji_files = sorted(synced_dir.rglob(f"{clip['clip_id']}_TX*.wav"))
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

    # Per-scene SRTs: look in Transcription/{scene}/
    code = _project_code(project_name)
    tr_dir = work_dir / "01_Media" / "Source" / "Transcription"
    scenes = sorted({c.get("scene", "") for c in clips if c.get("scene")})
    scene_captions = {}
    scene_transcripts = {}
    for scene in scenes:
        scene_dir = tr_dir / scene
        # Word-level captions
        cap_path = scene_dir / f"{code}_{scene}_captions.srt"
        if cap_path.exists():
            scene_captions[scene] = str(cap_path.resolve())
        # Sentence-level transcript
        tr_path = scene_dir / f"{code}_{scene}_transcript.srt"
        if tr_path.exists():
            scene_transcripts[scene] = str(tr_path.resolve())
    if scene_captions:
        files["scene_captions_srt"] = scene_captions
    if scene_transcripts:
        files["scene_transcript_srt"] = scene_transcripts

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
    code = _project_code(project_name)
    if transcript_json_path.parent.name in ("Transcription", "Setup"):
        setup_dir = transcript_json_path.parent.parent / "Setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        ingest_path = setup_dir / f"{code}_ingest.json"
    else:
        ingest_path = transcript_json_path.parent / f"{code}_ingest.json"
    with open(ingest_path, "w") as f:
        json.dump(ingest, f, indent=2, ensure_ascii=False)

    return ingest_path


VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mts", ".avi", ".mkv"}
MEDIA_DEFAULTS = {"width": 3840, "height": 2160, "fps": 25.0, "sample_rate": 48000}


def _probe_media(clip_path: Path) -> dict:
    """Use ffprobe to get width, height, fps, sample_rate from a video clip."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(clip_path)],
            stderr=subprocess.DEVNULL, timeout=10,
        )
        streams = json.loads(out).get("streams", [])
        media = {}
        for s in streams:
            if s.get("codec_type") == "video" and "width" not in media:
                media["width"] = s["width"]
                media["height"] = s["height"]
                fr = s.get("r_frame_rate") or s.get("avg_frame_rate", "25/1")
                num, den = (int(x) for x in fr.split("/"))
                media["fps"] = round(num / den, 3)
            if s.get("codec_type") == "audio" and "sample_rate" not in media:
                media["sample_rate"] = int(s.get("sample_rate", 48000))
        return {**MEDIA_DEFAULTS, **media}
    except Exception:
        return dict(MEDIA_DEFAULTS)


def _probe_duration(clip_path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
            stderr=subprocess.DEVNULL, timeout=10,
        )
        return round(float(out.strip()), 3)
    except Exception:
        return 0.0


def generate_lite(project: Path) -> Path:
    """Generate lite ingest.json from video files + DJI audio (no transcripts needed).

    Called at the end of prepare phase so UXP plugin can import media immediately.
    Transcribe phase overwrites this with full ingest.json via generate().

    Args:
        project: Absolute path to project root.

    Returns:
        Path to the written {CODE}_ingest.json in Setup/.
    """
    project = Path(project).resolve()
    video_dir = project / "01_Media" / "Source" / "Video"
    audio_dir = project / "01_Media" / "Source" / "Audio"
    setup_dir = project / "01_Media" / "Source" / "Setup"

    # Find all video files recursively (supports scene subfolders)
    videos = sorted(
        [f for f in video_dir.rglob("*")
         if f.is_file() and f.suffix.lower() in VIDEO_EXTS
         and not f.name.startswith(".")],
        key=lambda p: p.name,
    )

    if not videos:
        raise FileNotFoundError(f"No video files found in {video_dir}")

    # Probe media from first video
    media = _probe_media(videos[0])

    # Build clips list
    clips = []
    cumulative_offset = 0.0
    for v in videos:
        clip_id = v.stem
        duration = _probe_duration(v)

        clip_entry = {
            "clip_id": clip_id,
            "filename": v.name,
            "path": str(v),
            "duration": duration,
            "offset": round(cumulative_offset, 3),
        }

        # Scene from parent folder (e.g. Video/01_apartment/clip.MP4)
        parent_name = v.parent.name
        if SCENE_DIR_RE.match(parent_name):
            clip_entry["scene"] = parent_name

        # DJI synced audio
        if audio_dir.exists():
            dji_files = sorted(audio_dir.rglob(f"{clip_id}_TX*.wav"))
            if dji_files:
                clip_entry["dji_audio"] = [
                    {"tx": f.stem.split("_")[-1], "path": str(f.resolve())}
                    for f in dji_files
                ]

        clips.append(clip_entry)
        cumulative_offset += duration

    code = _project_code(project.name)
    ingest = {
        "version": VERSION,
        "type": "ingest_lite",
        "project_name": project.name,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "media": media,
        "clips": clips,
        "files": {},
        "source_folder": str(project),
    }

    setup_dir.mkdir(parents=True, exist_ok=True)
    ingest_path = setup_dir / f"{code}_ingest.json"
    with open(ingest_path, "w") as f:
        json.dump(ingest, f, indent=2, ensure_ascii=False)

    return ingest_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate ingest JSON from transcript JSON")
    parser.add_argument("transcript_json", help="Path to {project}_transcript.json")
    parser.add_argument("--lite", action="store_true",
                        help="Generate lite ingest (video+DJI only, no transcripts). "
                             "Pass project path instead of transcript path.")
    args = parser.parse_args()
    if args.lite:
        path = generate_lite(Path(args.transcript_json))
    else:
        path = generate(Path(args.transcript_json))
    print(f"Ingest JSON written: {path}")
