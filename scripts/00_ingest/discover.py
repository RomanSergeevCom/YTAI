#!/usr/bin/env python3
"""
00_ingest: Discover — Analyze raw footage folder.

Probes all video clips, samples audio with whisper, groups into scenes,
and generates a discovery report for review before organizing.

Usage:
    python discover.py "/path/to/raw" --channel YTRF
    python discover.py "/path/to/raw" --channel YTRF --no-whisper
    python discover.py "/path/to/raw" --channel YTRF --gap-minutes 10
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for lib imports
sys.path.insert(0, str(Path(__file__).parent))

from lib.inventory import scan_media, group_scenes, build_inventory_summary
from lib.sampler import sample_clips
from lib.classifier import classify, validate_channel, load_channels
from lib.html_report import generate_html


# ── ANSI colors ──────────────────────────────────────────────────────────────

class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    DIM = '\033[2m'
    BOLD = '\033[1m'
    CYAN = '\033[96m'
    RESET = '\033[0m'


def main():
    parser = argparse.ArgumentParser(
        description="Analyze raw footage folder and generate discovery report.")
    parser.add_argument("raw_folder", type=Path,
                        help="Path to raw footage folder")
    parser.add_argument("--channel", required=True,
                        help="Channel code (e.g. YTRF, YTCR, YTCG)")
    parser.add_argument("--no-whisper", action="store_true",
                        help="Skip whisper transcription sampling")
    parser.add_argument("--gap-minutes", type=float, default=5.0,
                        help="Timestamp gap threshold for scene splitting "
                             "(default: 5)")
    parser.add_argument("--sample-clips", type=int, default=5,
                        help="Number of clips to sample with whisper "
                             "(default: 5)")
    args = parser.parse_args()

    raw_folder = args.raw_folder.resolve()
    if not raw_folder.is_dir():
        print(f"{C.RED}Error:{C.RESET} Not a directory: {raw_folder}")
        sys.exit(1)

    # Validate channel
    channel = args.channel.upper()
    if not validate_channel(channel):
        channels = load_channels()
        codes = ", ".join(ch["code"] for ch in channels)
        print(f"{C.RED}Error:{C.RESET} Unknown channel '{channel}'. "
              f"Available: {codes}")
        print(f"{C.DIM}Add new channels to "
              f"scripts/00_ingest/channels.json{C.RESET}")
        sys.exit(1)

    discovery_dir = raw_folder / "_discovery"
    discovery_dir.mkdir(exist_ok=True)

    print()
    print(f"{C.BOLD}00_ingest: Discover{C.RESET}")
    print(f"  Source:  {raw_folder}")
    print(f"  Channel: {channel}")
    print()

    # ── Step 1: Inventory ────────────────────────────────────────────────
    print(f"  {C.CYAN}[1/3]{C.RESET} Scanning media files...", flush=True)

    clip_count = [0]
    def on_probe(fname):
        clip_count[0] += 1
        print(f"\r  {C.CYAN}[1/3]{C.RESET} Probing clip "
              f"{clip_count[0]}... {C.DIM}{fname}{C.RESET}",
              end='', flush=True)

    media = scan_media(raw_folder, progress_cb=on_probe)
    clips = media["clips"]
    print()

    if not clips:
        print(f"  {C.YELLOW}No video files found.{C.RESET}")
        sys.exit(1)

    inventory = build_inventory_summary(
        clips, media["dji_audio"], media["other_files"], media["archive"])

    print(f"  {C.GREEN}✓{C.RESET} {len(clips)} clips, "
          f"{inventory['total_size_human']}, "
          f"{inventory['total_duration_human']}")
    if inventory["cameras"]:
        print(f"    Cameras: {', '.join(inventory['cameras'])}")
    if inventory["resolutions"]:
        res_str = ", ".join(f"{k} ({v})" for k, v in
                           inventory["resolutions"].items())
        print(f"    Resolutions: {res_str}")
    if media["dji_audio"]:
        print(f"    DJI audio: {len(media['dji_audio'])} files")
    if media["archive"]["has_archive"]:
        print(f"    Archive: {len(media['archive']['files'])} files")
    print()

    # ── Step 2: Scene grouping ───────────────────────────────────────────
    scenes = group_scenes(clips, gap_minutes=args.gap_minutes)
    print(f"  {C.CYAN}[2/3]{C.RESET} Scene grouping "
          f"(gap threshold: {args.gap_minutes} min)")
    print(f"  {C.GREEN}✓{C.RESET} {len(scenes)} scenes detected:")
    for s in scenes:
        type_icon = "🎬" if s["type"] == "interview" else "🎥"
        print(f"    {type_icon} {s['suggested_name']}: "
              f"{s['clip_count']} clips, {s['duration_human']} "
              f"({s['type']})")
    print()

    # ── Step 3: Content sampling ─────────────────────────────────────────
    content_samples = {
        "clips_sampled": [],
        "language": "unknown",
        "topics": [],
        "transcripts": [],
        "whisper_available": False,
    }

    if not args.no_whisper:
        print(f"  {C.CYAN}[3/3]{C.RESET} Whisper sampling...", flush=True)

        def on_sample(fname):
            print(f"    Sampling: {C.DIM}{fname}{C.RESET}")

        content_samples = sample_clips(
            clips, discovery_dir,
            max_samples=args.sample_clips,
            progress_cb=on_sample,
        )

        if content_samples["whisper_available"]:
            print(f"  {C.GREEN}✓{C.RESET} Language: "
                  f"{content_samples['language']}, "
                  f"{len(content_samples['transcripts'])} samples")
        else:
            print(f"  {C.YELLOW}⚠{C.RESET} Whisper not available, "
                  f"skipping transcription")
    else:
        print(f"  {C.CYAN}[3/3]{C.RESET} Whisper sampling "
              f"{C.DIM}(skipped){C.RESET}")
    print()

    # ── Attach transcripts to scenes ────────────────────────────────────
    if content_samples.get("transcripts"):
        # Build clip→transcript lookup
        clip_tx = {t["clip"]: t["text"] for t in content_samples["transcripts"]}
        for scene in scenes:
            scene_texts = []
            for clip_fname in scene["clips"]:
                if clip_fname in clip_tx:
                    scene_texts.append(clip_tx[clip_fname])
            scene["transcript_preview"] = " ".join(scene_texts)[:300] if scene_texts else ""

    # ── Step 4: Classification ───────────────────────────────────────────
    total_duration = sum(c["duration_sec"] for c in clips)
    classification = classify(
        channel, raw_folder, total_duration, len(scenes))

    # ── Step 5: Build organization plan ──────────────────────────────────
    target_folder = raw_folder.parent / classification["project_name"]
    moves = []
    for scene in scenes:
        for clip_fname in scene["clips"]:
            moves.append({
                "from": clip_fname,
                "to": f"01_Media/Source/Video/{scene['suggested_name']}/"
                      f"{clip_fname}",
            })

    # DJI audio moves
    for dji in media["dji_audio"]:
        moves.append({
            "from": dji["filename"],
            "to": f"99_Pipeline/DJI_Audio/{dji['filename']}",
        })

    organization_plan = {
        "target_folder": str(target_folder),
        "moves": moves,
    }

    # ── Build report ─────────────────────────────────────────────────────
    report = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "source_folder": str(raw_folder),
        "channel": channel,
        "inventory": {
            **inventory,
            "clips": clips,
            "dji_audio_files": media["dji_audio"],
        },
        "content_samples": content_samples,
        "classification": classification,
        "scenes": scenes,
        "organization_plan": organization_plan,
    }

    report_path = discovery_dir / "discovery_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── Generate HTML report ─────────────────────────────────────────────
    html_path = discovery_dir / "discovery_report.html"
    generate_html(report, html_path)

    # ── Summary ──────────────────────────────────────────────────────────
    print(f"  {C.BOLD}Classification:{C.RESET}")
    print(f"    Project name: {C.GREEN}{classification['project_name']}"
          f"{C.RESET}")
    print(f"    Type: {classification['project_type']}")
    print(f"    Target: {target_folder}")
    print()
    print(f"  {C.GREEN}✓{C.RESET} Report saved:")
    print(f"    HTML: {html_path}")
    print(f"    JSON: {report_path}")
    print()

    # Auto-open HTML in browser
    import subprocess as _sp
    _sp.Popen(['open', str(html_path)],
              stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)

    print(f"  {C.BOLD}Next steps:{C.RESET}")
    print(f"    1. Review the HTML report (opened in browser)")
    print(f"    2. Edit scene names in JSON if needed: {C.DIM}{report_path}{C.RESET}")
    print(f"    3. Dry run: python scripts/00_ingest/organize.py "
          f'"{raw_folder}" --dry-run')
    print(f"    4. Apply:   python scripts/00_ingest/organize.py "
          f'"{raw_folder}"')
    print()


if __name__ == "__main__":
    main()
