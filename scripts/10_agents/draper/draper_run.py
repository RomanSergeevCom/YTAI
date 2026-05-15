"""Draper orchestrator — packaging pipeline for a finished YouTube video.

Two execution modes:

1. **Telegram-agent path (primary).** Roman writes "упакуй YTCR01" to
   @rya_draper_bot. The Mad Draper agent (~/.claude/agents/rya-draper.md)
   runs in tmux, reads everything, writes the 4 artefacts directly via Claude
   tools. This script is not invoked.

2. **Headless prompt-pack path (this script).** Roman runs:
       python draper_run.py --id YTCR01 --channel YTCR
   This builds 4 ready-to-paste prompts in {youtube_dir}/_prompts/, plus
   prefills DNA + Review context. Roman can then paste them into any LLM
   (Claude / GPT-4 / local model) for offline content generation. The
   produced artefacts (titles.txt, description.txt, etc.) need to be saved
   manually OR run `draper_run.py --collect` after pasting back replies into
   _prompts/replies/.

For MVP the primary path is the Telegram agent — this script makes the
headless flow possible without Claude API integration.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2].parent  # ~/YTAI
LIB_DIR = REPO_ROOT / "scripts" / "10_agents" / "_lib"
DRAPER_DIR = REPO_ROOT / "scripts" / "10_agents" / "draper"
sys.path.insert(0, str(LIB_DIR.parent))

from _lib import dna_loader, project_resolver, review_loader, report_writer  # noqa: E402

STEPS = [
    ("01_titles", "generate_titles.py"),
    ("02_description", "generate_description.py"),
    ("03_thumbnail", "generate_thumbnail_concepts.py"),
    ("04_tags_endscreen", "generate_tags.py"),
]


def resolve(project_id: str, explicit_root: str | None) -> dict:
    cmd = ["python3", str(LIB_DIR / "project_resolver.py"), "--id", project_id, "--json"]
    if explicit_root:
        cmd += ["--root", explicit_root]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        try:
            err = json.loads(result.stdout)
        except json.JSONDecodeError:
            err = {"error": result.stdout or result.stderr}
        raise SystemExit(json.dumps(err, indent=2, ensure_ascii=False))
    return json.loads(result.stdout)


def run_step(step_name: str, script_name: str, resolved: dict, dry_run: bool) -> dict:
    script = DRAPER_DIR / script_name
    cmd = [
        "python3", str(script),
        "--resolved-json", json.dumps(resolved, ensure_ascii=False),
        "--step-name", step_name,
    ]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return {"step": step_name, "status": "error", "stdout": result.stdout, "stderr": result.stderr}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"step": step_name, "status": "ok", "raw": result.stdout}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--id", dest="project_id", required=True)
    parser.add_argument("--channel", dest="channel_code", default=None,
                        help="optional override; inferred from project_id by default")
    parser.add_argument("--root", dest="explicit_root", default=None)
    parser.add_argument("--only", choices=[s[0] for s in STEPS], default=None,
                        help="run only one step (e.g. 01_titles)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would happen, write nothing")
    args = parser.parse_args(argv)

    resolved = resolve(args.project_id, args.explicit_root)
    if args.channel_code and args.channel_code != resolved["channel_code"]:
        print(f"⚠️  channel override: {resolved['channel_code']} → {args.channel_code}", file=sys.stderr)
        resolved["channel_code"] = args.channel_code

    # Validate DNA exists before running anything
    try:
        dna_loader.load(resolved["channel_code"])
    except dna_loader.DNANotFoundError as e:
        raise SystemExit(json.dumps({"error": str(e), "hint": "fill YTs/{channel}/{channel}.md first"}, indent=2))

    # Validate Review exists (required for description/chapters/thumbnails)
    if not resolved.get("review_analysis_json"):
        raise SystemExit(json.dumps({
            "error": "no Review/review_analysis.json found",
            "hint": "run scripts/05_editing/0508_review first",
            "project_root": resolved.get("project_root"),
        }, indent=2, ensure_ascii=False))

    # Run steps
    results: list[dict] = []
    steps = [s for s in STEPS if (args.only is None or s[0] == args.only)]
    for step_name, script_name in steps:
        print(f"→ {step_name} ({script_name})…", file=sys.stderr)
        r = run_step(step_name, script_name, resolved, args.dry_run)
        results.append(r)
        if r.get("status") == "error":
            print(f"  ✗ {r.get('stderr', 'unknown error')[:200]}", file=sys.stderr)
        else:
            print(f"  ✓ wrote {r.get('prompt_path', '?')}", file=sys.stderr)

    # Write report
    if not args.dry_run:
        youtube_dir = Path(resolved["youtube_dir"])
        youtube_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_writer.write(
            agent="draper",
            project_code=args.project_id,
            channel_code=resolved["channel_code"],
            inputs={
                "review_analysis": resolved.get("review_analysis_json"),
                "review_transcript": resolved.get("review_transcript_json"),
                "dna": str(dna_loader.dna_path(resolved["channel_code"])),
            },
            artifacts={
                "prompts_dir": str(youtube_dir / "_prompts"),
                **{f"step_{r.get('step', '?')}": r.get("prompt_path") for r in results},
            },
            summary={
                "mode": "prompt-pack (headless)",
                "steps_run": [r.get("step") for r in results],
                "next_action": "paste each _prompts/step_*.md into Claude/LLM, save replies to titles.txt/description.txt/etc.",
            },
            warnings=resolved.get("warnings", []),
            out_path=youtube_dir / "draper_report.json",
        )
        print(f"\n📋 Report: {report_path}", file=sys.stderr)

    print(json.dumps({"resolved": resolved, "steps": results}, indent=2, ensure_ascii=False))
    return 0 if all(r.get("status") != "error" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
