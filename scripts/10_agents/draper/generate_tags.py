"""Generate tags + end-screen recommendations prompt-pack."""

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
YTAI_ROOT = Path.home() / "YTAI"


def load_published_history(channel_code: str) -> str:
    """Read YTs/{channel}/published.md if it exists — list of past episodes."""
    path = YTAI_ROOT / "YTs" / channel_code / "published.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def build_prompt(resolved: dict) -> str:
    channel_code = resolved["channel_code"]
    project_id = resolved["project_id"]

    voice = (PROMPTS_DIR / "_shared" / "draper_voice.md").read_text(encoding="utf-8")
    channel_prompt = (PROMPTS_DIR / f"{channel_code}.md").read_text(encoding="utf-8")

    analysis = review_loader.load_analysis(resolved["review_analysis_json"])
    dna = dna_loader.load(channel_code)
    published = load_published_history(channel_code)

    user_block = f"""# Project: {project_id}  ·  Channel: {channel_code}

## Synopsis
{analysis.get('synopsis', '<missing>')}

## Themes
{', '.join(analysis.get('themes') or [])}

## Channel DNA — Content Pillars
{dna_loader.section(dna, 'Content Pillars') or ''}

## Channel DNA — Target Audience
{dna_loader.section(dna, 'Target Audience') or ''}

## Past episodes (for end-screen cross-recommendation)
{published if published else '<published.md не существует — поставь placeholder в end-screen и помечь "Seldon заполнит позже">'}
"""

    return f"""# SYSTEM (Draper voice)

{voice}

---

# SYSTEM (Channel overrides — {channel_code})

{channel_prompt}

---

# USER

Сделай ДВА файла:

**1. tags.txt** — 15-20 YouTube tags для этого видео. Mix:
   - 3-5 broad (channel-level: например, "Dubai real estate", "UAE business")
   - 7-10 mid-tail (тема эпизода: "broker Dubai", "Palm Jumeirah investment")
   - 3-5 long-tail (specific search query: "how to become broker Dubai 2026")

   Один тег per строка. Без хэштегов (# не нужен в tags). Без stuffing-вариаций
   ("dubai realestate", "real estate dubai", "dubai-real-estate" — это spam).

**2. end_screen.md** — 2 рекомендации для end-screen.
   Если есть `published.md` с прошлыми эпизодами — выбери 2 эпизода которые
   логично смотреть ПОСЛЕ этого. Для каждого:
   - Title эпизода (как опубликован)
   - URL (если есть в published.md)
   - 1 строка: "почему этот зритель захочет это посмотреть дальше"

   Если `published.md` отсутствует — пиши 2 placeholder'а в формате:
   "(placeholder — Seldon заполнит когда подключится к YouTube Analytics):
   тема которая логично следует за этим видео для этой аудитории."

Output language: {'en' if channel_code in ('YTCR', 'YTCG') else 'ru'}.

Формат ответа:

```
=== tags.txt ===
[15-20 tags, один per строка]

=== end_screen.md ===
[2 рекомендации]
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
