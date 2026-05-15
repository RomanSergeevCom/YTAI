"""Generate the titles prompt-pack — ready to paste into Claude/LLM.

Writes {youtube_dir}/_prompts/step_01_titles.md with:
- The Draper voice + title formulas + per-channel overrides (system prompt)
- The Review analysis + DNA + key quotes (user content)
- The expected output format

Roman pastes this into Claude and saves reply to {youtube_dir}/titles.txt.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LIB_PARENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB_PARENT))

from _lib import dna_loader, review_loader  # noqa: E402

DRAPER_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = DRAPER_DIR / "prompts"


def build_prompt(resolved: dict) -> str:
    channel_code = resolved["channel_code"]
    project_id = resolved["project_id"]

    voice = (PROMPTS_DIR / "_shared" / "draper_voice.md").read_text(encoding="utf-8")
    formulas = (PROMPTS_DIR / "_shared" / "title_formulas.md").read_text(encoding="utf-8")
    channel_prompt = (PROMPTS_DIR / f"{channel_code}.md").read_text(encoding="utf-8")

    analysis = review_loader.load_analysis(resolved["review_analysis_json"])
    dna = dna_loader.load(channel_code)

    keep = review_loader.keep_chapters(analysis)
    quotes = review_loader.key_quotes(analysis)

    user_block = f"""# Project: {project_id}  ·  Channel: {channel_code}

## Synopsis
{analysis.get('synopsis', '<missing>')}

## Story arc
{analysis.get('story_arc', '<missing>')}

## Themes
{', '.join(analysis.get('themes') or [])}

## Key strengths (with timestamps)
{chr(10).join(f"- {s}" for s in (analysis.get('key_strengths') or [])[:8])}

## KEEP chapters ({len(keep)} total)
{chr(10).join(review_loader.chapter_summary_lines(keep))}

## Key quotes
{chr(10).join(f"- [{q.get('tc_in', '?')}] {q.get('quote', '')}" for q in quotes[:10])}

## Channel DNA — Target Audience
{dna_loader.section(dna, 'Target Audience') or '<missing>'}

## Channel DNA — Pain Points / Unique Patterns
{dna_loader.section(dna, 'Unique Patterns') or ''}
"""

    return f"""# SYSTEM (Draper voice)

{voice}

---

# SYSTEM (Title formulas)

{formulas}

---

# SYSTEM (Channel overrides — {channel_code})

{channel_prompt}

---

# USER

Дай 5 названий для этого видео — каждый по своей формуле (Contradiction /
Specific number / Curiosity gap / Direct contrarian claim / First-person
reveal). Под каждым — одна строка обоснования (какая формула, почему она
именно для этой аудитории и этого видео).

50–70 символов на title. Без emoji. Без all-caps. Без "Ultimate".

Output language: {'en' if channel_code in ('YTCR', 'YTCG') else 'ru'}.

{user_block}
"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resolved-json", required=True)
    parser.add_argument("--step-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    resolved = json.loads(args.resolved_json)
    prompt = build_prompt(resolved)

    youtube_dir = Path(resolved["youtube_dir"])
    prompts_dir = youtube_dir / "_prompts"
    if not args.dry_run:
        prompts_dir.mkdir(parents=True, exist_ok=True)
        out_path = prompts_dir / f"step_{args.step_name}.md"
        out_path.write_text(prompt, encoding="utf-8")
    else:
        out_path = prompts_dir / f"step_{args.step_name}.md"

    result = {
        "step": args.step_name,
        "status": "ok",
        "prompt_path": str(out_path),
        "prompt_chars": len(prompt),
        "dry_run": args.dry_run,
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
