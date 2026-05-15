"""Generate description + chapters prompt-pack."""

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
    template = (PROMPTS_DIR / "_shared" / "description_template.md").read_text(encoding="utf-8")
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

## KEEP chapters with summaries ({len(keep)} chapters)
{chr(10).join(review_loader.chapter_summary_lines(keep))}

## Key quotes per chapter (use these in description hook + bullets)
{chr(10).join(f"- [{q.get('tc_in', '?')}] {q.get('title', '')}: {q.get('quote', '')}" for q in quotes)}

## Channel DNA — Content Pillars
{dna_loader.section(dna, 'Content Pillars') or '<missing>'}

## Channel DNA — Style & Tone
{dna_loader.section(dna, 'Style & Tone') or '<missing>'}
"""

    return f"""# SYSTEM (Draper voice)

{voice}

---

# SYSTEM (Description template)

{template}

---

# SYSTEM (Channel overrides — {channel_code})

{channel_prompt}

---

# USER

Сделай ДВА файла для этого видео:

**1. chapters.txt** — список глав из KEEP-chapters: "M:SS Title — конкретное
обещание". 8–15 строк. Первая начинается с 0:00.

**2. description.txt** — пять блоков по шаблону:
   - Hook (2 строки, ≤150 chars total — preview-зона)
   - Value bullets (3–5 строк, что зритель получает)
   - Chapters block (HH:MM:SS Title) — авто-detect by YouTube
   - CTA block (4–6 строк, из channel overrides)
   - Hashtags (1 строка, 3–5 тегов из channel overrides)

Total length description ~800-1,500 знаков.

Output language: {'en' if channel_code in ('YTCR', 'YTCG') else 'ru'}.

Формат ответа — два блока с заголовками:

```
=== chapters.txt ===
[содержимое]

=== description.txt ===
[содержимое]
```

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
    out_path = prompts_dir / f"step_{args.step_name}.md"
    if not args.dry_run:
        prompts_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt, encoding="utf-8")

    print(json.dumps({
        "step": args.step_name,
        "status": "ok",
        "prompt_path": str(out_path),
        "prompt_chars": len(prompt),
        "dry_run": args.dry_run,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
