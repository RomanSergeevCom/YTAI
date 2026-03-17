#!/usr/bin/env python3
"""
0105_generate_uxp_ingest.py — Convert Phase 2 per-scene ingest.json files to
UXP-compatible format for Premiere Pro plugin (0500_uxp).

Reads {scene}_ingest.json files from Setup/ and generates {project}_ingest.json
in the format expected by buildMultiSceneIngest() in the UXP plugin.

UXP format produced:
    {
      "project_name": "YTCR01_Arty_Dzis",
      "project_code": "YTCR01",
      "media": { "width": 3840, "height": 2160, "fps": 25.0, "sample_rate": 48000 },
      "clips": [
        {
          "clip_id": "C5210",
          "filename": "C5210.MP4",
          "path": "/absolute/path/C5210.MP4",
          "duration": 13.92,
          "scene": "apartment",
          "dji_audio": [
            { "path": "/absolute/path/C5210_TX01.wav", "tx": "TX01" },
            { "path": "/absolute/path/C5210_TX02.wav", "tx": "TX02" }
          ]
        }
      ],
      "files": { "transcript_json": null, "transcript_srt": null, "transcript_xlsx": null }
    }

Multi-scene detection in UXP: clips with a "scene" field trigger buildMultiSceneIngest().
DJI audio: clip.dji_audio[].tx maps TX01 → A2, TX02 → A3 on the timeline.
Sequence name per scene: {project_code}_1_{scene} e.g. "YTCR_1_1_apartment".

Usage:
    python3 0105_generate_uxp_ingest.py --project "/Volumes/RYA T7 Black/YTCR01_Arty_Dzis"
    python3 0105_generate_uxp_ingest.py --project "/path/to/project" --scene drive_home
    python3 0105_generate_uxp_ingest.py --project "/path/to/project" --dry-run
    python3 0105_generate_uxp_ingest.py --project "/path/to/project" --max-delta 1.0
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────────

SETUP_SUBDIR = "01_Media/Source/Setup"
VIDEO_EXTS = {".mp4", ".MP4", ".mov", ".MOV"}

# Sony FX3 defaults — used if ffprobe unavailable or clip not found
MEDIA_DEFAULTS = {"width": 3840, "height": 2160, "fps": 25.0, "sample_rate": 48000}

# Regex to extract short project code:
#   "YTCG37_Setup_UAE_Company_Remotely" → "YTCG37"
#   "YTCR01_Arty_Dzis" → "YTCR01"
PROJECT_CODE_RE = re.compile(r'^(YT[A-Z]{2,4}\d+)_')

# Max sync delta (frames) — TX audio with larger delta is excluded from the timeline.
# Target: ≤1F (AUD-06). Beyond this the audio is clearly mis-matched.
DEFAULT_MAX_DELTA = 1.0


# ── Media detection ────────────────────────────────────────────────────────────

def _probe_media(clip_path: Path) -> dict:
    """Use ffprobe to get width, height, fps, sample_rate from a video clip."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", str(clip_path),
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        streams = json.loads(out).get("streams", [])
        media = {}
        for s in streams:
            if s.get("codec_type") == "video" and "width" not in media:
                media["width"] = s["width"]
                media["height"] = s["height"]
                # fps from r_frame_rate "25/1" or avg_frame_rate
                fr = s.get("r_frame_rate") or s.get("avg_frame_rate", "25/1")
                num, den = (int(x) for x in fr.split("/"))
                media["fps"] = round(num / den, 3)
            if s.get("codec_type") == "audio" and "sample_rate" not in media:
                media["sample_rate"] = int(s.get("sample_rate", 48000))
        return {**MEDIA_DEFAULTS, **media}
    except Exception:
        return dict(MEDIA_DEFAULTS)


# ── Core conversion ────────────────────────────────────────────────────────────

def _extract_tx(track_type: str) -> str | None:
    """'TX01_SYNC' → 'TX01', 'TX02_SYNC' → 'TX02', else None."""
    m = re.match(r'^(TX\d+)', track_type or "")
    return m.group(1) if m else None


def convert_scene(scene_data: dict, project: Path,
                  max_delta: float = DEFAULT_MAX_DELTA) -> list[dict]:
    """Convert one per-scene ingest dict to a list of UXP clip dicts."""
    scene_name = scene_data["scene"]
    clips_out = []

    for cr in scene_data["clips"]:
        clip_id = cr["clip_id"]

        # ── Absolute video path ──
        clip_rel = cr.get("clip_path", "")
        abs_clip = project / clip_rel
        if not abs_clip.exists():
            # Fallback: scan Video/{scene}/ for any matching stem
            video_dir = project / "01_Media" / "Source" / "Video" / scene_name
            found = next((p for p in video_dir.glob(f"{clip_id}.*")
                          if p.suffix in VIDEO_EXTS), None) if video_dir.exists() else None
            abs_clip = found or abs_clip

        filename = abs_clip.name

        # ── DJI audio: A2/A3 tracks → dji_audio list ──
        # Skip tracks where sync delta exceeds max_delta (mis-matched audio).
        dji_audio = []
        skipped_tx = []
        for key in ("A2", "A3"):
            track = cr.get("tracks", {}).get(key, {})
            tx = _extract_tx(track.get("type", ""))
            path_rel = track.get("path")
            if not tx or not path_rel:
                continue
            delta = track.get("sync_delta_frames")
            if delta is not None and abs(delta) > max_delta:
                skipped_tx.append(f"{tx}({delta:.2f}F)")
                continue
            abs_audio = project / path_rel
            dji_audio.append({"path": str(abs_audio), "tx": tx})

        clip_entry = {
            "clip_id": clip_id,
            "filename": filename,
            "path": str(abs_clip),
            "duration": cr["duration_sec"],
            "scene": scene_name,
        }
        if dji_audio:
            clip_entry["dji_audio"] = dji_audio
        if skipped_tx:
            clip_entry["_skipped_audio"] = skipped_tx  # informational, ignored by UXP

        clips_out.append(clip_entry)

    return clips_out


def generate_uxp_ingest(
    project: Path,
    scene_filter: str | None = None,
    dry_run: bool = False,
    max_delta: float = DEFAULT_MAX_DELTA,
) -> Path:
    """Build UXP-format ingest.json from per-scene ingest.json files.

    Args:
        project:       Absolute project root path.
        scene_filter:  If set, include only this scene name.
        dry_run:       Print plan without writing files.

    Returns:
        Path to the written {project}_ingest.json (or would-be path in dry-run).
    """
    setup_dir = project / SETUP_SUBDIR
    m_code = PROJECT_CODE_RE.match(project.name)
    code = m_code.group(1) if m_code else project.name
    out_path = setup_dir / f"{code}_ingest.json"

    # ── Find per-scene ingest.json files ──────────────────────────────────────
    project_global_stem = f"{project.name}_ingest"
    scene_files = sorted(
        f for f in setup_dir.glob("*_ingest.json")
        if f.stem != project_global_stem   # skip own output file
    )

    if not scene_files:
        print(f"ERROR: No per-scene ingest.json files found in {setup_dir}", file=sys.stderr)
        sys.exit(1)

    if scene_filter:
        scene_files = [f for f in scene_files if f.stem == f"{scene_filter}_ingest"]
        if not scene_files:
            print(f"ERROR: No ingest.json for scene '{scene_filter}' in {setup_dir}", file=sys.stderr)
            sys.exit(1)

    print(f"Project : {project.name}")
    print(f"Setup   : {setup_dir.relative_to(project)}")
    print(f"Scenes  : {[f.stem.replace('_ingest', '') for f in scene_files]}")
    print(f"Output  : {out_path.relative_to(project)}")
    if dry_run:
        print("\n*** DRY RUN — no files will be written ***\n")

    # ── Convert per-scene data ────────────────────────────────────────────────
    all_clips: list[dict] = []
    media: dict = {}

    for sf in scene_files:
        with open(sf) as f:
            scene_data = json.load(f)

        scene_clips = convert_scene(scene_data, project, max_delta=max_delta)
        all_clips.extend(scene_clips)

        # Probe media from first clip in first scene processed
        if not media and scene_clips:
            first_path = Path(scene_clips[0]["path"])
            if first_path.exists():
                media = _probe_media(first_path)
                print(f"Media   : {media['width']}x{media['height']} "
                      f"@ {media['fps']}fps  {media['sample_rate']}Hz "
                      f"(probed from {first_path.name})")
            else:
                media = dict(MEDIA_DEFAULTS)
                print(f"Media   : {media} (defaults — clip not found)")

        # Per-scene summary
        n_dji = sum(len(c.get("dji_audio", [])) for c in scene_clips)
        n_skipped = sum(len(c.get("_skipped_audio", [])) for c in scene_clips)
        skip_str = f"  {n_skipped} skipped (delta>{max_delta}F)" if n_skipped else ""
        print(f"  {scene_data['scene']:25s} {len(scene_clips):3d} clips  "
              f"{n_dji} DJI WAVs{skip_str}")

    # ── Build project code ────────────────────────────────────────────────────
    project_code = code  # already computed above from PROJECT_CODE_RE

    # ── Assemble output ───────────────────────────────────────────────────────
    uxp_ingest = {
        "project_name": project.name,
        "project_code": project_code,
        "media": media or MEDIA_DEFAULTS,
        "clips": all_clips,
        "files": {
            "transcript_json": None,
            "transcript_srt": None,
            "transcript_xlsx": None,
        },
    }

    total_dji = sum(len(c.get("dji_audio", [])) for c in all_clips)
    print(f"\nTotal   : {len(all_clips)} clips  {total_dji} DJI WAVs")
    print(f"Scenes  : {len(set(c['scene'] for c in all_clips))}")
    print(f"\nUXP will create sequences named: "
          f"{project_code}_{{scene}}  (e.g. {project_code}_{scene_files[0].stem.replace('_ingest','')})")

    if dry_run:
        print(f"\n[dry-run] Would write: {out_path}")
        return out_path

    setup_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(uxp_ingest, f, indent=2)

    print(f"\n✓  Written: {out_path}")
    return out_path


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate UXP-compatible ingest.json from Phase 2 per-scene files"
    )
    ap.add_argument("--project", type=Path, required=True,
                    help="Absolute path to project root")
    ap.add_argument("--scene", default=None,
                    help="Include only this scene (default: all scenes)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print plan without writing files")
    ap.add_argument("--max-delta", type=float, default=DEFAULT_MAX_DELTA,
                    help=f"Max sync delta in frames — TX audio above this is excluded "
                         f"(default: {DEFAULT_MAX_DELTA}F)")
    args = ap.parse_args()

    project = args.project.resolve()
    if not project.exists():
        print(f"ERROR: Project path not found: {project}", file=sys.stderr)
        sys.exit(1)

    generate_uxp_ingest(project, scene_filter=args.scene, dry_run=args.dry_run,
                        max_delta=args.max_delta)


if __name__ == "__main__":
    main()
