"""Scene orchestrator for nested multi-scene transcription projects.

This module provides core functions for detecting scene subfolders, invoking
transcribe_project.py per-scene via subprocess, collecting the output transcript
to the canonical Transcription/ path, and checking whether a scene needs
transcription.

Usage (called by Plan 02 CLI orchestrator):
  from 0201_transcribe_nested import detect_scenes, transcribe_scene, collect_scene_transcript

Per-scene invocation pattern (per 03-RESEARCH.md):
  - transcribe_project.py is called with --project pointing at the scene subfolder
  - This runs in flat mode: writes to {scene_dir}/{scene}_transcription/{scene}_transcript.json
  - collect_scene_transcript copies the output to the canonical v3 path:
    {project}/01_Media/Source/Transcription/{scene}_transcript.json
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from merge_transcripts import merge_transcripts, generate_merged_xlsx

FALLBACK_CONFIDENCE_THRESHOLD = 0.5


def detect_scenes(project: Path) -> list:
    """Return sorted list of scene subdirectory Paths under Source/Video/.

    Excludes hidden directories (starting with "."). Does not require numeric
    prefix — matches any non-hidden subdirectory (consistent with Phase 1 + 2).

    Args:
        project: Project root path (contains 01_Media/Source/Video/).

    Returns:
        Sorted list of Path objects for each scene subdirectory.
    """
    video_dir = project / "01_Media" / "Source" / "Video"
    if not video_dir.exists():
        return []
    return sorted(
        [d for d in video_dir.iterdir() if d.is_dir() and not d.name.startswith(".")],
        key=lambda p: p.name,
    )


def should_transcribe_scene(project: Path, scene_name: str) -> bool:
    """Return True if the scene needs transcription (transcript not yet present).

    Checks two locations (canonical first, then scene-level fallback):
      1. {project}/01_Media/Source/Transcription/{scene_name}_transcript.json
      2. {project}/01_Media/Source/Video/{scene_name}/{scene_name}_transcript.json

    Args:
        project: Project root path.
        scene_name: Name of the scene subfolder (e.g. "apartment").

    Returns:
        True if transcript file does NOT exist anywhere (scene needs transcription).
        False if transcript already exists at either location.
    """
    canonical = project / "01_Media" / "Source" / "Transcription" / "scenes" / f"{scene_name}_transcript.json"
    canonical_flat = project / "01_Media" / "Source" / "Transcription" / f"{scene_name}_transcript.json"
    scene_level = project / "01_Media" / "Source" / "Video" / scene_name / f"{scene_name}_transcript.json"
    return not canonical.exists() and not canonical_flat.exists() and not scene_level.exists()


def transcribe_scene(
    scene_dir: Path,
    num_speakers: int | None = None,
    dry_run: bool = False,
    language: str | None = None,
) -> None:
    """Invoke transcribe_project.py for a single scene via subprocess.

    The script is called with the scene subfolder as --project (flat mode):
      {venv_python} transcribe_project.py --project {scene_dir} [-n {num_speakers}] -y [--dry-run] [--language {language}]

    When transcribe_project.py runs in flat mode (no 01_Media/Source/Video/ inside
    the target), it writes the transcript to:
      {scene_dir}/{scene_name}_transcription/{scene_name}_transcript.json

    After this call, collect_scene_transcript() must be used to move the output
    to the canonical Transcription/ path.

    Args:
        scene_dir: Path to the scene subfolder (e.g. Source/Video/apartment).
        num_speakers: Number of speakers for diarization (-n flag). None = auto-detect.
        dry_run: If True, passes --dry-run to the transcription script.
        language: Whisper language code (e.g. "en"). None = auto-detect.

    Raises:
        subprocess.CalledProcessError: If the subprocess exits with non-zero status.
    """
    venv_python = Path("~/YTAI/environment/.venv_transcribe/bin/python").expanduser()
    script = Path(
        "~/YTAI/scripts/02_transcribe/020101_transcribe/transcribe_project.py"
    ).expanduser()
    cmd = [str(venv_python), str(script), "--project", str(scene_dir), "-y"]
    if num_speakers is not None:
        cmd += ["-n", str(num_speakers)]
    if language:
        cmd += ["--language", language]
    if dry_run:
        cmd.append("--dry-run")
    subprocess.run(cmd, check=True)


def collect_scene_transcript(scene_dir: Path, project: Path) -> Path:
    """Copy per-scene transcript from legacy path to canonical Transcription/ path.

    transcribe_project.py (flat mode) writes to:
      {scene_dir}/{scene_name}_transcript.json

    This function copies it to the canonical v3 location:
      {project}/01_Media/Source/Transcription/{scene_name}_transcript.json

    Args:
        scene_dir: Path to the scene subfolder (e.g. Source/Video/apartment).
        project: Project root path.

    Returns:
        Path to the destination transcript file.
    """
    scene_name = scene_dir.name
    src = scene_dir / f"{scene_name}_transcript.json"
    dst_dir = project / "01_Media" / "Source" / "Transcription" / "scenes"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{scene_name}_transcript.json"
    shutil.copy2(src, dst)
    return dst


def read_scene_confidence(transcript_path: Path) -> tuple:
    """Read avg_confidence and language from a scene transcript JSON.

    Returns:
        (avg_confidence: float, language: str)
    """
    with open(transcript_path) as f:
        data = json.load(f)
    conf = data.get("stats", {}).get("avg_confidence", 0.0)
    lang = data.get("language", "unknown")
    return conf, lang


def clear_scene_transcription(scene_dir: Path, project: Path) -> None:
    """Remove scene transcript files to allow re-transcription.

    Deletes:
      - {scene_dir}/{scene}_transcript.json (scene-level)
      - Transcription/{scene}_transcript.json (canonical)
      - {scene_dir}/{scene}_transcription/ (entire dir)
    """
    scene_name = scene_dir.name
    canonical = project / "01_Media" / "Source" / "Transcription" / "scenes" / f"{scene_name}_transcript.json"
    canonical_flat = project / "01_Media" / "Source" / "Transcription" / f"{scene_name}_transcript.json"
    scene_level = scene_dir / f"{scene_name}_transcript.json"
    tx_dir = scene_dir / f"{scene_name}_transcription"

    for p in [canonical, canonical_flat, scene_level]:
        if p.exists():
            p.unlink()
    if tx_dir.exists():
        shutil.rmtree(tx_dir)


def scan_scene_durations(scenes: list) -> dict:
    """Pre-scan scenes to estimate total duration (via clip count * avg clip duration).

    Returns {scene_name: {"clips": N, "est_duration_min": float}}.
    """
    AVG_CLIP_SEC = 30  # rough estimate per clip
    result = {}
    for scene_dir in scenes:
        clips = [f for f in scene_dir.iterdir()
                 if f.is_file() and f.suffix.upper() in (".MP4", ".MOV")]
        est_min = len(clips) * AVG_CLIP_SEC / 60
        result[scene_dir.name] = {"clips": len(clips), "est_duration_min": round(est_min, 1)}
    return result


def fmt_elapsed(seconds: float) -> str:
    """Format seconds as Xh Ym or Ym Zs."""
    m = int(seconds) // 60
    s = int(seconds) % 60
    if m >= 60:
        h = m // 60
        m = m % 60
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def print_dry_run_summary(project: Path, scenes: list) -> None:
    """Print a dry-run summary listing scenes and clip counts.

    Args:
        project: Project root path.
        scenes: List of scene Path objects (from detect_scenes).
    """
    print(f"=== Nested Transcription: {project.name} ===")
    print(f"Scenes found: {len(scenes)}")
    for scene in scenes:
        count = len([
            f for f in scene.iterdir()
            if f.is_file() and f.suffix.upper() in (".MP4", ".MOV")
        ])
        print(f"  {scene.name}: {count} clips")
    print("Mode: DRY-RUN — no transcription will run")


def main():
    """CLI entry point: orchestrate per-scene transcription with merge."""
    ap = argparse.ArgumentParser(
        description="Transcribe nested multi-scene project by invoking transcribe_project.py per scene.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--project", required=True, type=Path, help="Project root path")
    ap.add_argument("--scene", default=None, help="Process single scene only (optional)")
    ap.add_argument("-n", "--speakers", type=int, default=None, help="Number of speakers for diarization (default: auto-detect)")
    ap.add_argument("--language", default=None, help="Whisper language code e.g. 'ru' (default: auto-detect)")
    ap.add_argument("--fallback", default=None, help="Fallback language if primary gives avg_confidence < 0.5 (e.g. 'en')")
    ap.add_argument("--dry-run", action="store_true", help="Show scene list and clip counts without transcribing")
    ap.add_argument("-y", action="store_true", help="Skip confirmations")
    args = ap.parse_args()

    project = args.project.resolve()

    # Validate project structure
    video_dir = project / "01_Media" / "Source" / "Video"
    if not video_dir.exists():
        print(f"Error: {video_dir} does not exist. Is this a nested project?", file=sys.stderr)
        sys.exit(1)

    scenes = detect_scenes(project)

    # Filter to single scene if --scene provided
    if args.scene:
        filtered = [s for s in scenes if s.name == args.scene]
        if not filtered:
            print(
                f"Error: Scene '{args.scene}' not found. Available: {[s.name for s in scenes]}",
                file=sys.stderr,
            )
            sys.exit(1)
        scenes = filtered

    # Dry-run: print summary and exit
    if args.dry_run:
        print_dry_run_summary(project, scenes)
        sys.exit(0)

    # Pre-scan scene durations for progress display
    scene_info = scan_scene_durations(scenes)
    total_clips = sum(v["clips"] for v in scene_info.values())
    print(f"\n=== Nested Transcription: {project.name} ===")
    print(f"Scenes: {len(scenes)} | Clips: {total_clips}")
    for s in scenes:
        info = scene_info[s.name]
        print(f"  {s.name:<25s} {info['clips']:>3d} clips  ~{info['est_duration_min']:.0f} min")
    print()

    # Process each scene
    scene_results = []  # (name, language, confidence, action, elapsed_sec)
    overall_start = time.time()
    scenes_done = 0

    for idx, scene_dir in enumerate(scenes, 1):
        scene_name = scene_dir.name
        scene_start = time.time()
        info = scene_info[scene_name]
        canonical = project / "01_Media" / "Source" / "Transcription" / "scenes" / f"{scene_name}_transcript.json"
        scene_level = scene_dir / f"{scene_name}_transcript.json"

        elapsed_total = time.time() - overall_start
        print(f"=== Scene {idx}/{len(scenes)}: {scene_name} ({info['clips']} clips) "
              f"| Elapsed: {fmt_elapsed(elapsed_total)} ===")

        if canonical.exists():
            conf, lang = read_scene_confidence(canonical)
            scene_results.append((scene_name, lang, conf, "skipped", 0))
            print(f"  Skipping (transcript exists, {lang}, conf={conf:.2f})")
            scenes_done += 1
            continue

        if scene_level.exists():
            print(f"  Collecting (already transcribed)...")
            collect_scene_transcript(scene_dir, project)
            conf, lang = read_scene_confidence(canonical)
            scene_results.append((scene_name, lang, conf, "collected", 0))
            print(f"  Collected ({lang}, conf={conf:.2f})")
            scenes_done += 1
            continue

        # Transcribe with primary language
        print(f"  Transcribing...")
        transcribe_scene(scene_dir, num_speakers=args.speakers, language=args.language)
        collect_scene_transcript(scene_dir, project)
        conf, lang = read_scene_confidence(canonical)
        action = "transcribed"

        # Fallback: if confidence too low and fallback language provided
        if args.fallback and conf < FALLBACK_CONFIDENCE_THRESHOLD:
            print(f"  Low confidence ({conf:.2f}) with '{lang}', retrying with '{args.fallback}'...")
            clear_scene_transcription(scene_dir, project)
            transcribe_scene(scene_dir, num_speakers=args.speakers, language=args.fallback)
            collect_scene_transcript(scene_dir, project)
            conf, lang = read_scene_confidence(canonical)
            action = f"fallback({args.fallback})"

        scene_elapsed = time.time() - scene_start
        scenes_done += 1
        scene_results.append((scene_name, lang, conf, action, scene_elapsed))

        # Estimate remaining time
        remaining_scenes = len(scenes) - idx
        if scenes_done > 0:
            avg_per_scene = (time.time() - overall_start) / scenes_done
            est_remaining = avg_per_scene * remaining_scenes
            print(f"  Done: {scene_name} ({lang}, conf={conf:.2f}) in {fmt_elapsed(scene_elapsed)}"
                  f" | ~{fmt_elapsed(est_remaining)} remaining")
        else:
            print(f"  Done: {scene_name} ({lang}, conf={conf:.2f}) in {fmt_elapsed(scene_elapsed)}")

    # Summary table
    total_elapsed = time.time() - overall_start
    print(f"\n{'Scene':<25s} {'Language':<8s} {'Conf':>6s}  {'Time':>8s}  {'Action'}")
    print("-" * 70)
    for name, lang, conf, action, elapsed in scene_results:
        t = fmt_elapsed(elapsed) if elapsed > 0 else "-"
        print(f"  {name:<23s} {lang:<8s} {conf:>6.2f}  {t:>8s}  {action}")
    print("-" * 70)
    print(f"  {'TOTAL':<23s} {'':8s} {'':>6s}  {fmt_elapsed(total_elapsed):>8s}")

    # Merge all scene transcripts into {project}_transcript.json
    transcribed = [s.name for s in scenes]
    merge_transcripts(project, transcribed)
    print(f"\nMerge complete: {project.name}_transcript.json ({len(transcribed)} scenes)")

    # Generate merged XLSX
    xlsx_path = generate_merged_xlsx(project, transcribed)
    print(f"XLSX complete: {xlsx_path.name}")


if __name__ == "__main__":
    main()
